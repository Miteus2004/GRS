"""Tests for dashboard observability helpers."""

from __future__ import annotations

from pathlib import Path

from engine.activity import append_event
from engine.observability import collect_demo_results, collect_last_delta, collect_path_state, collect_service_health
from engine.parser import load_intent


PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
INTENT_FILE = PROJECT_ROOT / "intent.yaml"


def test_collect_path_state_detects_qdisc_delay():
    class FakeNagios:
        def __init__(self, url):
            self.url = url

        def congested_hosts(self):
            return []

    class FakeProvisioner:
        @classmethod
        def from_intent(cls, intent):
            return cls()

        def inspect_qdisc(self, router):
            if router == "router2":
                return "qdisc netem 8001: dev eth0 root refcnt 2 limit 1000 delay 200ms"
            return "qdisc pfifo_fast 0: dev eth0 root refcnt 2 bands 3 priomap 1 2 3"

    intent = load_intent(INTENT_FILE)
    state = collect_path_state(intent, nagios_client_cls=FakeNagios, provisioner_cls=FakeProvisioner)

    assert state["actual"]["active_path"] == "backup"
    assert state["actual"]["congested_hosts"] == ["router2"]
    assert state["actual"]["signals"][0]["source"] == "qdisc"


def test_collect_service_health_reports_timings(monkeypatch):
    monkeypatch.setattr(
        "engine.observability._measure_dns",
        lambda nameserver, query_name: {
            "up": True,
            "response_ms": 12.3,
            "query": query_name,
            "nameserver": nameserver,
            "answers": ["172.16.123.136"],
            "error": None,
        },
    )
    monkeypatch.setattr(
        "engine.observability._measure_http",
        lambda url: {
            "up": True,
            "status_code": 200,
            "response_ms": 4.5,
            "url": url,
            "error": None,
        },
    )

    intent = load_intent(INTENT_FILE)
    health = collect_service_health(intent)

    assert health["overall_up"] is True
    assert any(item["kind"] == "dns" for item in health["checks"])
    assert all("response_ms" in item for item in health["checks"])


def test_collect_last_delta_reads_recent_event(tmp_path):
    intent = load_intent(INTENT_FILE)
    append_event(tmp_path, "provision", "Updated Nginx upstream", {"changed_files": ["nginx.conf"]})

    delta = collect_last_delta(TEMPLATES_DIR, tmp_path, intent)

    assert delta["last_run_summary"] == "Updated Nginx upstream"
    assert delta["last_run_details"]["changed_files"] == ["nginx.conf"]


def test_collect_demo_results_combines_fault_tolerance_and_sdn(monkeypatch, tmp_path):
    intent = load_intent(INTENT_FILE)

    monkeypatch.setattr(
        "engine.observability.collect_sync_status",
        lambda *args, **kwargs: {
            "overall_in_sync": True,
            "routers": {
                "router1": {"in_sync": True, "actual": {"ospf": True, "bgp": True}},
                "router2": {"in_sync": True, "actual": {"ospf": True, "bgp": False}},
                "router3": {"in_sync": True, "actual": {"ospf": True, "bgp": False}},
            },
            "dns": {"in_sync": True},
            "nginx": {"in_sync": True},
            "ryu": {"in_sync": True},
        },
    )
    monkeypatch.setattr(
        "engine.observability.collect_service_health",
        lambda *_args, **_kwargs: {
            "overall_up": True,
            "checks": [
                {"kind": "dns", "up": True, "response_ms": 2.5},
                {"kind": "lb", "up": True, "response_ms": 4.0},
                {"kind": "web", "up": True, "response_ms": 2.0},
                {"kind": "web", "up": False, "response_ms": 8.0},
            ],
        },
    )
    monkeypatch.setattr(
        "engine.observability.collect_path_state",
        lambda *_args, **_kwargs: {
            "actual": {"active_path": "backup", "congested_hosts": ["router2"], "signals": []},
            "details": {},
        },
    )
    monkeypatch.setattr(
        "engine.observability.collect_last_delta",
        lambda *_args, **_kwargs: {"drift_detected": False, "changed_files": [], "changed_routers": []},
    )

    summary = collect_demo_results(intent, TEMPLATES_DIR, tmp_path, "http://ryu")

    assert summary["fault_tolerance"]["routers_in_sync"] == 3
    assert summary["fault_tolerance"]["bgp_up"] == 1
    assert summary["service_times_ms"]["dns"] == 2.5
    assert summary["sdn_comparison"]["with_sdn"]["active_path"] == "backup"
    assert summary["sdn_comparison"]["without_sdn"]["active_path"] == "primary"