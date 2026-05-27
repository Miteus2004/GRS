"""Derive desired-vs-actual sync status for the dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .parser import load_intent
from .planner import build_reconcile_plan
from .provisioner import Provisioner
from .sdn import RyuClient

try:
    import dns.resolver
except ImportError as exc:
    dns = None
    _dns_error = exc
else:
    _dns_error = None

try:
    import requests
except ImportError as exc:
    requests = None
    _requests_error = exc
else:
    _requests_error = None


def _resolver(nameserver: str):
    if dns is None:
        raise RuntimeError("dnspython is required") from _dns_error
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = [nameserver]
    resolver.timeout = 2
    resolver.lifetime = 3
    return resolver


def _http_ok(url: str) -> bool:
    if requests is None:
        raise RuntimeError("requests is required") from _requests_error
    return requests.get(url, timeout=5).status_code == 200


def _router_status(provisioner: Provisioner, router: str) -> dict[str, Any]:
    ospf_raw = provisioner.check_ospf_neighbors(router)
    bgp_raw = provisioner.check_bgp_summary(router)
    ospf_ok = "Full" in ospf_raw
    bgp_ok = True if router != "router1" else ("Established" in bgp_raw)
    return {
        "desired": "in sync",
        "actual": {
            "ospf": ospf_ok,
            "bgp": bgp_ok,
        },
        "in_sync": ospf_ok and bgp_ok,
        "details": {
            "ospf": ospf_raw,
            "bgp": bgp_raw,
        },
    }


def _dns_status(intent: dict[str, Any]) -> dict[str, Any]:
    dns_section = intent.get("services", {}).get("dns", {})
    zones = dns_section.get("zones", {})
    domain = intent.get("organization", {}).get("domain", "")
    nameserver = None
    for records in zones.values():
        for record in records:
            if record.get("name") == "dns":
                nameserver = record.get("ip")
                break
        if nameserver:
            break
    checks: dict[str, bool] = {}
    if nameserver and domain:
        resolver = _resolver(nameserver)
        for zone_name, records in zones.items():
            if zone_name != domain:
                continue
            for record in records:
                fqdn = f"{record['name']}.{domain}"
                try:
                    answer = resolver.resolve(fqdn, "A")
                    checks[fqdn] = any(r.to_text() == record["ip"] for r in answer)
                except Exception:
                    checks[fqdn] = False
    return {
        "desired": "DNS records resolve to configured IPs",
        "actual": checks,
        "in_sync": all(checks.values()) if checks else False,
        "details": {"nameserver": nameserver, "domain": domain},
    }


def _nginx_status(intent: dict[str, Any]) -> dict[str, Any]:
    web = intent.get("services", {}).get("web", {})
    lb_ip = None
    for record in intent.get("services", {}).get("dns", {}).get("zones", {}).get(intent.get("organization", {}).get("domain", ""), []):
        if record.get("name") == "lb":
            lb_ip = record.get("ip")
            break
    checks: dict[str, bool] = {}
    if lb_ip:
        checks[f"lb@{lb_ip}"] = _http_ok(f"http://{lb_ip}")
    for server in web.get("servers", []):
        checks[server["name"]] = _http_ok(f"http://{server['ip']}")
    return {
        "desired": f"{web.get('replicas', 0)} replicas reachable",
        "actual": checks,
        "in_sync": all(checks.values()) if checks else False,
        "details": {"lb_ip": lb_ip},
    }


def _ryu_status(ryu_url: str) -> dict[str, Any]:
    client = RyuClient(ryu_url)
    switches = client.list_switches()
    return {
        "desired": "Ryu controller reachable and switches connected",
        "actual": {"switches": switches},
        "in_sync": bool(switches),
        "details": {},
    }


def collect_sync_status(
    intent: dict[str, Any],
    template_dir: str | Path,
    output_dir: str | Path,
    ryu_url: str,
) -> dict[str, Any]:
    """Return component sync state plus current drift summary."""
    plan = build_reconcile_plan(intent, template_dir, output_dir)
    provisioner = Provisioner.from_intent(intent)

    routers: dict[str, Any] = {}
    for entry in intent.get("management", []):
        name = entry.get("name")
        if not name:
            continue
        routers[name] = _router_status(provisioner, name)

    dns_status = _dns_status(intent)
    nginx_status = _nginx_status(intent)
    ryu_status = _ryu_status(ryu_url)

    overall = all(item.get("in_sync", False) for item in routers.values())
    overall = overall and dns_status["in_sync"] and nginx_status["in_sync"] and ryu_status["in_sync"] and not plan.has_changes

    return {
        "overall_in_sync": overall,
        "drift_detected": plan.has_changes,
        "changed_files": plan.changed_files,
        "changed_routers": plan.changed_routers,
        "routers": routers,
        "dns": dns_status,
        "nginx": nginx_status,
        "ryu": ryu_status,
    }
