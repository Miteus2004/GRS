"""Dashboard-facing observability helpers for service health, path state, and deltas."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

try:
    import dns.resolver
except ImportError as exc:
    dns = None
    _dns_error = exc
else:
    dns = dns.resolver
    _dns_error = None

try:
    import requests
except ImportError as exc:
    requests = None
    _requests_error = exc
else:
    _requests_error = None

from .activity import read_events
from .monitor import NagiosClient
from .parser import load_intent
from .planner import build_reconcile_plan
from .provisioner import Provisioner
from .sdn import choose_path, path_summary


QDISC_DELAY_RE = re.compile(r"\bdelay\s+(?P<delay>\d+(?:\.\d+)?)\s*(?P<unit>us|ms|s)?", re.IGNORECASE)
QDISC_DEV_RE = re.compile(r"\bdev\s+(?P<iface>\S+)", re.IGNORECASE)


def _service_level(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 3


def _measure_http(url: str) -> dict[str, Any]:
    if requests is None:
        raise RuntimeError("requests is required") from _requests_error
    start = time.perf_counter()
    try:
        response = requests.get(url, timeout=5)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return {
            "up": response.status_code == 200,
            "status_code": response.status_code,
            "response_ms": round(elapsed_ms, 1),
            "url": url,
            "error": None,
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return {
            "up": False,
            "status_code": None,
            "response_ms": round(elapsed_ms, 1),
            "url": url,
            "error": str(exc),
        }


def _measure_dns(nameserver: str, query_name: str) -> dict[str, Any]:
    start = time.perf_counter()
    if dns is not None:
        try:
            resolver = dns.Resolver()
            resolver.nameservers = [nameserver]
            resolver.timeout = 2
            resolver.lifetime = 4
            lookup = getattr(resolver, "resolve", None) or getattr(resolver, "query", None)
            if lookup is None:
                raise AttributeError("Resolver has no resolve/query method")
            answer = lookup(query_name, "A")
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            values = [record.to_text() for record in answer]
            return {
                "up": True,
                "response_ms": round(elapsed_ms, 1),
                "query": query_name,
                "nameserver": nameserver,
                "answers": values,
                "error": None,
            }
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return {
                "up": False,
                "response_ms": round(elapsed_ms, 1),
                "query": query_name,
                "nameserver": nameserver,
                "answers": [],
                "error": str(exc),
            }

    if shutil.which("dig"):
        try:
            result = subprocess.run(
                ["dig", f"@{nameserver}", query_name, "A", "+short"],
                check=False,
                capture_output=True,
                text=True,
                timeout=4,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            values = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            return {
                "up": result.returncode == 0 and bool(values),
                "response_ms": round(elapsed_ms, 1),
                "query": query_name,
                "nameserver": nameserver,
                "answers": values,
                "error": None if result.returncode == 0 else result.stderr.strip() or "dig failed",
            }
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return {
                "up": False,
                "response_ms": round(elapsed_ms, 1),
                "query": query_name,
                "nameserver": nameserver,
                "answers": [],
                "error": str(exc),
            }

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return {
        "up": False,
        "response_ms": round(elapsed_ms, 1),
        "query": query_name,
        "nameserver": nameserver,
        "answers": [],
        "error": "No DNS client available",
    }


def _find_zone_records(intent: dict[str, Any]) -> list[dict[str, Any]]:
    domain = intent.get("organization", {}).get("domain", "")
    zones = intent.get("services", {}).get("dns", {}).get("zones", {})
    return zones.get(domain, []) if isinstance(zones, dict) else []


def collect_service_health(intent: dict[str, Any]) -> dict[str, Any]:
    """Measure DNS, load balancer, and web backend responsiveness."""
    domain = intent.get("organization", {}).get("domain", "")
    records = _find_zone_records(intent)

    dns_ip = None
    dns_query = f"www.{domain}" if domain else "www"
    lb_ip = None
    web_servers: list[dict[str, Any]] = []
    for record in records:
        name = record.get("name")
        ip = record.get("ip")
        if name in {"dns", "ns1"} and ip and dns_ip is None:
            dns_ip = ip
        if name == "lb" and ip and lb_ip is None:
            lb_ip = ip
        if name == "www" and ip:
            lb_ip = lb_ip or ip
        if name and name.startswith("www") and name != "www" and ip:
            web_servers.append({"name": name, "ip": ip})

    checks: list[dict[str, Any]] = []
    if dns_ip:
        dns_result = _measure_dns(dns_ip, dns_query)
        checks.append(
            {
                "kind": "dns",
                "name": dns_query,
                "endpoint": dns_ip,
                "up": dns_result["up"],
                "response_ms": dns_result["response_ms"],
                "detail": ", ".join(dns_result["answers"]) if dns_result["answers"] else dns_result["error"],
            }
        )
    if lb_ip:
        lb_result = _measure_http(f"http://{lb_ip}")
        checks.append(
            {
                "kind": "lb",
                "name": "load balancer",
                "endpoint": lb_ip,
                "up": lb_result["up"],
                "response_ms": lb_result["response_ms"],
                "detail": f"HTTP {lb_result['status_code']}" if lb_result["status_code"] is not None else lb_result["error"],
            }
        )

    for server in intent.get("services", {}).get("web", {}).get("servers", []):
        if not isinstance(server, dict):
            continue
        ip = server.get("ip")
        if not ip:
            continue
        result = _measure_http(f"http://{ip}")
        checks.append(
            {
                "kind": "web",
                "name": server.get("name", ip),
                "endpoint": ip,
                "up": result["up"],
                "response_ms": result["response_ms"],
                "detail": f"HTTP {result['status_code']}" if result["status_code"] is not None else result["error"],
            }
        )

    return {
        "overall_up": all(item["up"] for item in checks) if checks else False,
        "checks": checks,
    }


def _parse_qdisc_output(output: str) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for line in output.splitlines():
        delay_match = QDISC_DELAY_RE.search(line)
        if not delay_match:
            continue
        iface_match = QDISC_DEV_RE.search(line)
        unit = delay_match.group("unit") or "ms"
        delay = float(delay_match.group("delay"))
        if unit == "us":
            delay = delay / 1000.0
        elif unit == "s":
            delay = delay * 1000.0
        signals.append(
            {
                "interface": iface_match.group("iface") if iface_match else None,
                "delay_ms": round(delay, 1),
                "raw": line.strip(),
            }
        )
    return signals


def collect_path_state(
    intent: dict[str, Any],
    delay_threshold_ms: float = 100.0,
    nagios_client_cls: type[NagiosClient] = NagiosClient,
    provisioner_cls: type[Provisioner] = Provisioner,
) -> dict[str, Any]:
    """Combine Nagios alerts and tc netem inspection into one path decision."""
    congested_hosts: list[str] = []
    signals: list[dict[str, Any]] = []
    nagios_url = intent.get("services", {}).get("monitoring", {}).get("nagios_url", "")

    if nagios_url:
        try:
            nagios_hosts = nagios_client_cls(nagios_url).congested_hosts()
            congested_hosts.extend(nagios_hosts)
            signals.extend({"source": "nagios", "host": host} for host in nagios_hosts)
        except Exception as exc:
            signals.append({"source": "nagios_error", "error": str(exc)})

    try:
        provisioner = provisioner_cls.from_intent(intent)
        for entry in intent.get("management", []):
            name = entry.get("name") if isinstance(entry, dict) else None
            if not name:
                continue
            try:
                qdisc_output = provisioner.inspect_qdisc(name)
            except Exception as exc:
                signals.append({"source": "qdisc_error", "host": name, "error": str(exc)})
                continue
            for signal in _parse_qdisc_output(qdisc_output):
                if signal["delay_ms"] >= delay_threshold_ms:
                    congested_hosts.append(name)
                    signals.append({"source": "qdisc", "host": name, **signal})
    except Exception as exc:
        signals.append({"source": "qdisc_error", "error": str(exc)})

    congested_hosts = sorted(set(congested_hosts))
    summary = path_summary(congested_hosts)
    return {
        "desired": "primary when clear, backup when congested",
        "actual": {
            "active_path": summary["path"],
            "congested_hosts": summary["congested_hosts"],
            "signals": signals,
        },
        "in_sync": True,
        "details": {
            "nagios_url": nagios_url,
            "delay_threshold_ms": delay_threshold_ms,
            "decision": summary,
        },
    }


def collect_last_delta(template_dir: str | Path, output_dir: str | Path, intent: dict[str, Any]) -> dict[str, Any]:
    """Expose the most recent reconcile change summary for the dashboard."""
    plan = build_reconcile_plan(intent, template_dir, output_dir)
    events = read_events(output_dir, limit=50)
    last_event = None
    for event in reversed(events):
        if event.get("kind") in {"plan", "render", "provision"}:
            last_event = event
            break

    return {
        "drift_detected": plan.has_changes,
        "changed_files": plan.changed_files,
        "changed_routers": plan.changed_routers,
        "last_run": last_event,
        "last_run_summary": last_event.get("message") if last_event else "No engine run recorded yet",
        "last_run_details": last_event.get("details", {}) if last_event else {},
    }