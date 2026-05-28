"""Tests for dashboard observability helpers."""

from __future__ import annotations

from pathlib import Path

from engine.activity import append_event
from engine.observability import collect_last_delta, collect_path_state, collect_service_health
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