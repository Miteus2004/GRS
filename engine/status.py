"""Derive desired-vs-actual sync status for the dashboard."""

from __future__ import annotations

import concurrent.futures
import os
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError as exc:
    requests = None
    _requests_error = exc
else:
    _requests_error = None

from .parser import load_intent
from .planner import build_reconcile_plan
from .provisioner import Provisioner
from .sdn import RyuClient


def _http_ok(url: str) -> bool:
    if requests is None:
        raise RuntimeError("requests is required") from _requests_error
    return requests.get(url, timeout=2).status_code == 200


def _router_status(provisioner: Provisioner, router: str) -> dict[str, Any]:
    try:
        ospf_raw = provisioner.check_ospf_neighbors(router, use_exec=True)
    except Exception as exc:
        return {
            "desired": "in sync",
            "actual": {"ospf": False, "bgp": False},
            "in_sync": False,
            "details": {"error": str(exc)},
        }

    expected_bgp = router == "router1"
    try:
        bgp_raw = provisioner.check_bgp_summary(router, use_exec=True) if expected_bgp else ""
    except Exception:
        bgp_raw = ""

    ospf_ok = "Full" in ospf_raw or "FULL" in ospf_raw
    bgp_ok = True if not expected_bgp else ("Established sessions 1" in bgp_raw or "Established" in bgp_raw)
    return {
        "desired": "in sync",
        "actual": {"ospf": ospf_ok, "bgp": bgp_ok},
        "in_sync": ospf_ok and bgp_ok,
        "details": {"ospf": ospf_raw, "bgp": bgp_raw},
    }


def _dns_status(intent: dict[str, Any], bundle_in_sync: bool) -> dict[str, Any]:
    domain = intent.get("organization", {}).get("domain", "")
    zones = intent.get("services", {}).get("dns", {}).get("zones", {})
    checks: dict[str, bool] = {}
    for zone_name, records in zones.items():
        if zone_name != domain:
            continue
        for record in records:
            checks[f"{record['name']}.{domain}"] = bundle_in_sync
    return {
        "desired": "DNS bundle matches intent",
        "actual": checks,
        "in_sync": all(checks.values()) if checks else False,
        "details": {"domain": domain, "mode": "bundle-match"},
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
    dns_bundle_in_sync = not any(name.startswith(("named.conf", "db.")) for name in plan.changed_files)

    if os.getenv("IBN_SKIP_LIVE_CHECKS", "0") in ("1", "true", "True"):
        routers = {
            entry.get("name"): {"in_sync": False, "details": {"skipped": True}}
            for entry in intent.get("management", [])
            if entry.get("name")
        }
        dns_status = _dns_status(intent, dns_bundle_in_sync)
        nginx_status = {"desired": f"{intent.get('services', {}).get('web', {}).get('replicas', 0)} replicas reachable", "actual": {}, "in_sync": False, "details": {"skipped": True}}
        ryu_status = {"desired": "Ryu controller reachable and switches connected", "actual": {}, "in_sync": False, "details": {"skipped": True}}
    else:
        provisioner = Provisioner.from_intent(intent)
        routers = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures: dict[concurrent.futures.Future, str] = {}
            for entry in intent.get("management", []):
                name = entry.get("name")
                if not name:
                    continue
                futures[executor.submit(_router_status, provisioner, name)] = name

            done, pending = concurrent.futures.wait(futures, timeout=4)
            for fut in done:
                name = futures[fut]
                try:
                    routers[name] = fut.result()
                except Exception as exc:
                    routers[name] = {"desired": "in sync", "actual": {"ospf": False, "bgp": False}, "in_sync": False, "details": {"error": str(exc)}}

            for fut in pending:
                routers[futures[fut]] = {"desired": "in sync", "actual": {"ospf": False, "bgp": False}, "in_sync": False, "details": {"error": "timed out while checking router status"}}

        dns_status = _dns_status(intent, dns_bundle_in_sync)
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
