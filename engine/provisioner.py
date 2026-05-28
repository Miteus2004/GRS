"""Provision rendered configurations to routers over SSH using Netmiko."""

from __future__ import annotations

import re
import warnings
from typing import Any

warnings.filterwarnings(
    "ignore",
    message=r"Python 3\.8 is no longer supported by the Python core team.*",
    category=DeprecationWarning,
)

try:
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
except ImportError as exc:
    ConnectHandler = None
    _netmiko_error = exc
else:
    _netmiko_error = None

try:
    import paramiko
except ImportError as exc:
    paramiko = None
    _paramiko_error = exc
else:
    _paramiko_error = None


class ProvisionError(RuntimeError):
    """Raised when a device cannot be provisioned."""


class Provisioner:
    """SSH into router containers and apply Quagga configuration via vtysh."""

    DEFAULT_PORT     = 22
    DEFAULT_USER     = "root"
    DEFAULT_PASSWORD = "root"

    def __init__(self, inventory: dict[str, dict[str, Any]]) -> None:
        # inventory: {router_name: {host, port, username, password}}
        self.inventory = inventory

    @classmethod
    def from_intent(cls, intent: dict[str, Any]) -> "Provisioner":
        """Build inventory from the intent's management section."""
        inventory: dict[str, dict[str, Any]] = {}
        for entry in intent.get("management", []):
            inventory[entry["name"]] = {
                "host":     entry["host"],
                "port":     entry.get("port",     cls.DEFAULT_PORT),
                "username": entry.get("username", cls.DEFAULT_USER),
                "password": entry.get("password", cls.DEFAULT_PASSWORD),
            }
        return cls(inventory)

    def _connect(self, name: str):
        if ConnectHandler is None:
            raise RuntimeError("netmiko is required") from _netmiko_error
        dev = self.inventory[name]
        # Allow overriding the per-connection timeout via env for faster failures
        try:
            import os

            timeout = int(os.getenv("STATUS_PROVISIONER_TIMEOUT", os.getenv("PROVISIONER_TIMEOUT", "30")))
        except Exception:
            timeout = 30
        return ConnectHandler(
            device_type="linux",
            host=dev["host"],
            port=dev["port"],
            username=dev["username"],
            password=dev["password"],
            timeout=timeout,
        )

    def _exec_command(self, name: str, command: str) -> str:
        if paramiko is None:
            raise RuntimeError("paramiko is required") from _paramiko_error
        dev = self.inventory[name]
        try:
            import os

            timeout = int(os.getenv("STATUS_PROVISIONER_TIMEOUT", os.getenv("PROVISIONER_TIMEOUT", "8")))
        except Exception:
            timeout = 8
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=dev["host"],
            port=dev["port"],
            username=dev["username"],
            password=dev["password"],
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        try:
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            output = stdout.read().decode("utf-8", errors="replace")
            error = stderr.read().decode("utf-8", errors="replace")
            return output or error
        finally:
            client.close()

    def push_vtysh(self, router: str, commands: list[str]) -> str:
        """Send a list of vtysh config commands to a router and write memory."""
        conn = self._connect(router)
        try:
            full = ["configure terminal"] + commands + ["end", "write memory"]
            joined = " -c ".join(f"'{c}'" for c in full)
            return conn.send_command(f"vtysh -c {joined}", expect_string=r"\$")
        finally:
            conn.disconnect()

    def reload_quagga(self, router: str) -> str:
        """Signal Quagga to re-read its config files."""
        conn = self._connect(router)
        try:
            out = ""
            for daemon in ("zebra", "ospfd", "bgpd"):
                out += conn.send_command(f"killall -HUP {daemon} 2>/dev/null; echo {daemon} ok")
            return out
        finally:
            conn.disconnect()

    def check_ospf_neighbors(self, router: str, use_exec: bool = False) -> str:
        command = "vtysh -c 'show ip ospf neighbor'"
        if use_exec:
            return self._exec_command(router, command)
        conn = self._connect(router)
        try:
            send_timing = getattr(conn, "send_command_timing", None)
            if callable(send_timing):
                result = send_timing(command, strip_prompt=False, strip_command=False)
                if isinstance(result, str):
                    return result
            return conn.send_command(command)
        finally:
            conn.disconnect()

    def check_bgp_summary(self, router: str, use_exec: bool = False) -> str:
        command = "vtysh -c 'show bgp summary'"
        if use_exec:
            return self._exec_command(router, command)
        conn = self._connect(router)
        try:
            send_timing = getattr(conn, "send_command_timing", None)
            if callable(send_timing):
                result = send_timing(command, strip_prompt=False, strip_command=False)
                if isinstance(result, str):
                    return result
            return conn.send_command(command)
        finally:
            conn.disconnect()

    def inspect_qdisc(self, router: str) -> str:
        """Return `tc qdisc show` output for a router."""
        return self._exec_command(router, "tc qdisc show")

    @staticmethod
    def parse_qdisc_delays(output: str) -> list[dict[str, Any]]:
        """Extract netem delay signals from tc qdisc output."""
        delay_re = re.compile(r"\bdelay\s+(?P<delay>\d+(?:\.\d+)?)\s*(?P<unit>us|ms|s)?", re.IGNORECASE)
        iface_re = re.compile(r"\bdev\s+(?P<iface>\S+)", re.IGNORECASE)
        signals: list[dict[str, Any]] = []
        for line in output.splitlines():
            delay_match = delay_re.search(line)
            if not delay_match:
                continue
            iface_match = iface_re.search(line)
            unit = delay_match.group("unit") or "ms"
            delay = float(delay_match.group("delay"))
            if unit == "us":
                delay /= 1000.0
            elif unit == "s":
                delay *= 1000.0
            signals.append(
                {
                    "interface": iface_match.group("iface") if iface_match else None,
                    "delay_ms": round(delay, 1),
                    "raw": line.strip(),
                }
            )
        return signals

    def detect_netem_congestion(self, threshold_ms: float = 100.0) -> list[dict[str, Any]]:
        """Return routers whose qdisc delay exceeds the threshold."""
        congested: list[dict[str, Any]] = []
        for name in self.inventory:
            try:
                output = self.inspect_qdisc(name)
            except Exception:
                continue
            signals = self.parse_qdisc_delays(output)
            for signal in signals:
                if signal["delay_ms"] >= threshold_ms:
                    congested.append({"router": name, **signal})
        return congested

    def apply(self, rendered_configs: dict[str, str]) -> dict[str, str]:
        """Reload Quagga on every router in the inventory after configs are written."""
        results: dict[str, str] = {}
        for name in self.inventory:
            try:
                results[name] = self.reload_quagga(name)
            except (ProvisionError, Exception) as exc:
                results[name] = f"ERROR: {exc}"
        return results
