"""Tests for the persistent activity log and demo path-state helper."""

from __future__ import annotations

from engine.activity import append_event, read_events
from engine.app import _path_state


def test_activity_log_round_trip(tmp_path):
    append_event(tmp_path, "render", "Rendered bundle", {"files": ["a.conf"]})
    append_event(tmp_path, "provision", "Reloaded router1", {"status": "OK"})

    events = read_events(tmp_path, limit=10)

    assert len(events) == 2
    assert events[0]["kind"] == "render"
    assert events[1]["message"] == "Reloaded router1"


def test_path_state_reports_backup_when_congested(monkeypatch):
    class FakeNagiosClient:
        def __init__(self, url):
            self.url = url

        def congested_hosts(self):
            return ["router2"]

    monkeypatch.setattr("engine.app.NagiosClient", FakeNagiosClient)

    state = _path_state({"services": {"monitoring": {"nagios_url": "http://nagios"}}})

    assert state["actual"]["active_path"] == "backup"
    assert state["actual"]["congested_hosts"] == ["router2"]