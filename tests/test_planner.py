"""Dry-run planning tests for the IBN engine."""

from __future__ import annotations

from pathlib import Path

from engine.parser import load_intent
from engine.planner import build_reconcile_plan
from engine.renderer import TemplateRenderer


PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
INTENT_FILE = PROJECT_ROOT / "intent.yaml"


def test_plan_is_empty_when_output_matches(tmp_path):
    intent = load_intent(INTENT_FILE)
    TemplateRenderer(TEMPLATES_DIR).write_bundle(intent, tmp_path)
    plan = build_reconcile_plan(intent, TEMPLATES_DIR, tmp_path)
    assert plan.has_changes is False
    assert plan.steps == []


def test_plan_detects_changed_bundle_file(tmp_path):
    intent = load_intent(INTENT_FILE)
    TemplateRenderer(TEMPLATES_DIR).write_bundle(intent, tmp_path)
    target = tmp_path / "nginx.conf"
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    plan = build_reconcile_plan(intent, TEMPLATES_DIR, tmp_path)
    assert plan.has_changes is True
    assert any(step.target == "nginx.conf" for step in plan.steps)
