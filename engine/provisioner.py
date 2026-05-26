"""Provision rendered configurations to routers over SSH using Netmiko."""

from __future__ import annotations

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
        return ConnectHandler(
            device_type="linux",
            host=dev["host"],
            port=dev["port"],
            username=dev["username"],
            password=dev["password"],
            timeout=30,
        )

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

    def check_ospf_neighbors(self, router: str) -> str:
        conn = self._connect(router)
        try:
            return conn.send_command("vtysh -c 'show ip ospf neighbor'")
        finally:
            conn.disconnect()

    def check_bgp_summary(self, router: str) -> str:
        conn = self._connect(router)
        try:
            return conn.send_command("vtysh -c 'show bgp summary'")
        finally:
            conn.disconnect()

    def apply(self, rendered_configs: dict[str, str]) -> dict[str, str]:
        """Reload Quagga on every router in the inventory after configs are written."""
        results: dict[str, str] = {}
        for name in self.inventory:
            try:
                results[name] = self.reload_quagga(name)
            except (ProvisionError, Exception) as exc:
                results[name] = f"ERROR: {exc}"
        return results
