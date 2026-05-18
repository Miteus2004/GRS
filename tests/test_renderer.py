"""Offline tests for the template renderer — no lab environment needed."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from engine.parser import load_intent, validate_intent, IntentValidationError
from engine.renderer import TemplateRenderer

PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
INTENT_FILE   = PROJECT_ROOT / "intent.example.yaml"


# ── Parser ──────────────────────────────────────────────────────────────────

def test_load_intent_returns_dict():
    assert isinstance(load_intent(INTENT_FILE), dict)

def test_intent_has_required_sections():
    intent = load_intent(INTENT_FILE)
    for section in ("organization", "networks", "routing", "services"):
        assert section in intent

def test_networks_is_a_list():
    assert isinstance(load_intent(INTENT_FILE)["networks"], list)

def test_validate_rejects_missing_section():
    with pytest.raises(IntentValidationError, match="Missing required sections"):
        validate_intent({"organization": {}, "networks": [], "routing": {}})

def test_validate_rejects_networks_as_dict():
    with pytest.raises(IntentValidationError):
        validate_intent({
            "organization": {"domain": "x.net"},
            "networks": {"bad": "dict"},
            "routing": {},
            "services": {},
        })


# ── Renderer ────────────────────────────────────────────────────────────────

def test_render_bundle_produces_all_files():
    intent = load_intent(INTENT_FILE)
    domain = intent["organization"]["domain"]
    bundle = TemplateRenderer(TEMPLATES_DIR).render_bundle(intent)
    reverse_prefix = intent["routing"]["ospf"]["reverse_prefix"]
    expected = {
        "ospfd.conf", "zebra.conf",
        "named.conf.options", "named.conf.local",
        f"db.{domain}",
        f"db.{reverse_prefix}",
        "nginx.conf",
    }
    assert set(bundle.keys()) == expected

def test_named_conf_local_contains_domain():
    intent = load_intent(INTENT_FILE)
    bundle = TemplateRenderer(TEMPLATES_DIR).render_bundle(intent)
    assert intent["organization"]["domain"] in bundle["named.conf.local"]

def test_named_conf_options_has_directory():
    bundle = TemplateRenderer(TEMPLATES_DIR).render_bundle(load_intent(INTENT_FILE))
    assert "directory" in bundle["named.conf.options"]

def test_nginx_upstream_contains_all_server_ips():
    intent = load_intent(INTENT_FILE)
    bundle = TemplateRenderer(TEMPLATES_DIR).render_bundle(intent)
    upstream = bundle["nginx.conf"]
    for server in intent["services"]["web"]["servers"]:
        assert server["ip"] in upstream

def test_ospfd_conf_contains_all_networks():
    intent = load_intent(INTENT_FILE)
    bundle = TemplateRenderer(TEMPLATES_DIR).render_bundle(intent)
    ospfd = bundle["ospfd.conf"]
    for net in intent["routing"]["ospf"]["networks"]:
        assert net in ospfd

def test_ospfd_conf_contains_bgp_neighbor():
    intent = load_intent(INTENT_FILE)
    bundle = TemplateRenderer(TEMPLATES_DIR).render_bundle(intent)
    neighbor_ip = intent["routing"]["bgp"]["neighbors"][0]["neighbor_ip"]
    assert neighbor_ip in bundle["ospfd.conf"]

def test_zone_file_has_correct_records():
    intent = load_intent(INTENT_FILE)
    bundle = TemplateRenderer(TEMPLATES_DIR).render_bundle(intent)
    domain = intent["organization"]["domain"]
    zone = bundle[f"db.{domain}"]
    for records in intent["services"]["dns"]["zones"].values():
        for r in records:
            assert r["name"] in zone
            assert r["ip"] in zone

def test_write_bundle_creates_files_on_disk():
    intent = load_intent(INTENT_FILE)
    with tempfile.TemporaryDirectory() as tmpdir:
        written = TemplateRenderer(TEMPLATES_DIR).write_bundle(intent, tmpdir)
        assert len(written) == 7
        for path in written.values():
            assert path.exists() and path.stat().st_size > 0