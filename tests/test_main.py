"""Tests for the reconciliation loop path selection."""

from __future__ import annotations

from pathlib import Path
import importlib
from unittest.mock import MagicMock

import pytest

engine_main = importlib.import_module("engine.main")


class FakeNagios:
    def __init__(self, congested_hosts):
        self._congested_hosts = congested_hosts

    def congested_hosts(self):
        return self._congested_hosts


class FakeRyu:
    def __init__(self, switches):
        self._switches = switches
        self.calls = []

    def list_switches(self):
        return self._switches

    def activate_path(self, dpid, profile):
        self.calls.append((dpid, profile))
        return {"dpid": dpid, "profile": profile}


def _fake_renderer(tmp_path: Path):
    renderer = MagicMock()
    bundle_path = tmp_path / "bundle.txt"
    bundle_path.write_text("dummy", encoding="utf-8")
    renderer.write_bundle.return_value = {"bundle.txt": bundle_path}
    return renderer


def test_reconcile_activates_primary_when_clear(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_main, "load_intent", lambda path: {"services": {"monitoring": {"nagios_url": "http://nagios"}}})
    monkeypatch.setattr(engine_main, "TemplateRenderer", lambda templates: _fake_renderer(tmp_path))
    monkeypatch.setattr(engine_main, "Provisioner", MagicMock())
    monkeypatch.setattr(engine_main, "NagiosClient", lambda url: FakeNagios([]))
    fake_ryu = FakeRyu([1, 2])
    monkeypatch.setattr(engine_main, "RyuClient", lambda url: fake_ryu)

    exit_code = engine_main.reconcile("intent.yaml", "templates", str(tmp_path / "out"), monitor=True)

    assert exit_code == 0
    assert fake_ryu.calls == [(1, "primary"), (2, "primary")]


def test_reconcile_activates_backup_when_congested(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_main, "load_intent", lambda path: {"services": {"monitoring": {"nagios_url": "http://nagios"}}})
    monkeypatch.setattr(engine_main, "TemplateRenderer", lambda templates: _fake_renderer(tmp_path))
    monkeypatch.setattr(engine_main, "Provisioner", MagicMock())
    monkeypatch.setattr(engine_main, "NagiosClient", lambda url: FakeNagios(["router2"]))
    fake_ryu = FakeRyu([7])
    monkeypatch.setattr(engine_main, "RyuClient", lambda url: fake_ryu)

    exit_code = engine_main.reconcile("intent.yaml", "templates", str(tmp_path / "out"), monitor=True)

    assert exit_code == 0
    assert fake_ryu.calls == [(7, "backup")]
