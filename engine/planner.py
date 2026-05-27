"""Build reconcile plans and human-readable diffs for the IBN engine."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
import copy
from pathlib import Path
import tempfile
from typing import Any

from .renderer import TemplateRenderer


@dataclass(frozen=True)
class PlanStep:
    kind: str
    target: str
    action: str
    command: str | None = None
    before: str | None = None
    after: str | None = None
    diff: str | None = None


@dataclass(frozen=True)
class ReconcilePlan:
    steps: list[PlanStep]
    changed_files: list[str]
    changed_routers: list[str]

    @property
    def has_changes(self) -> bool:
        return bool(self.steps)


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _render_preview(intent: dict[str, Any], template_dir: str | Path) -> tuple[dict[str, str], dict[str, Path]]:
    renderer = TemplateRenderer(template_dir)
    with tempfile.TemporaryDirectory() as tmp_dir:
        written = renderer.write_bundle(intent, tmp_dir)
        rendered = {name: path.read_text(encoding="utf-8") for name, path in written.items()}
    return rendered, {}


def _normalize_intent(intent: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(intent)
    organization = normalized.setdefault("organization", {})
    organization.setdefault("domain", "example.net")
    organization.setdefault("as_number", 65001)

    routing = normalized.setdefault("routing", {})
    ospf = routing.setdefault("ospf", {})
    ospf.setdefault("router_id", "1.1.1.1")
    ospf.setdefault("area", 0)
    ospf.setdefault("networks", [])
    ospf.setdefault("reverse_zone", "123.16.172.in-addr.arpa")
    ospf.setdefault("reverse_prefix", "172.16.123")
    routing.setdefault("bgp", {}).setdefault("neighbors", [])

    services = normalized.setdefault("services", {})
    dns = services.setdefault("dns", {})
    dns.setdefault("primary", "dns.example.net")
    dns.setdefault("ns2_ip", "172.16.123.139")
    dns.setdefault("zones", {})
    web = services.setdefault("web", {})
    web.setdefault("upstream_name", "www_pool")
    web.setdefault("servers", [])
    web.setdefault("replicas", len(web["servers"]))
    services.setdefault("monitoring", {})

    normalized.setdefault("management", [])
    return normalized


def _bundle_for_router(intent: dict[str, Any], router_name: str, template_dir: str | Path) -> dict[str, str]:
    renderer = TemplateRenderer(template_dir)
    context = {
        "organization": intent.get("organization", {}),
        "networks": intent.get("networks", []),
        "routing": dict(intent.get("routing", {})),
        "services": intent.get("services", {}),
    }
    host = None
    for entry in intent.get("management", []):
        if entry.get("name") == router_name:
            host = entry.get("host")
            break
    if host:
        routing = context.setdefault("routing", {})
        ospf = routing.setdefault("ospf", {})
        ospf["router_id"] = host
    return {
        "ospfd.conf": renderer.render("ospfd.conf.j2", context),
        "zebra.conf": renderer.render("zebra.conf.j2", context),
    }


def build_reconcile_plan(
    intent: dict[str, Any],
    template_dir: str | Path,
    output_dir: str | Path,
) -> ReconcilePlan:
    """Compare the desired bundle against the current output directory."""
    renderer = TemplateRenderer(template_dir)
    desired_bundle = renderer.render_bundle(_normalize_intent(intent))
    output_root = Path(output_dir)

    steps: list[PlanStep] = []
    changed_files: list[str] = []

    for filename, desired_text in desired_bundle.items():
        current_text = _read_text(output_root / filename)
        if current_text == desired_text:
            continue
        changed_files.append(filename)
        action = "create" if current_text is None else "update"
        diff_text = "\n".join(
            unified_diff(
                (current_text or "").splitlines(),
                desired_text.splitlines(),
                fromfile=f"{filename} (current)",
                tofile=f"{filename} (desired)",
                lineterm="",
            )
        )
        steps.append(
            PlanStep(
                kind="file",
                target=filename,
                action=action,
                before=current_text,
                after=desired_text,
                diff=diff_text,
            )
        )

    changed_routers: list[str] = []
    router_names = [entry.get("name") for entry in intent.get("management", []) if entry.get("name")]
    for router_name in router_names:
        desired_router_bundle = _bundle_for_router(intent, router_name, template_dir)
        router_changed = False
        for filename, desired_text in desired_router_bundle.items():
            current_text = _read_text(output_root / router_name / filename)
            if current_text != desired_text:
                router_changed = True
                changed_files.append(f"{router_name}/{filename}")
        if router_changed:
            changed_routers.append(router_name)
            steps.append(
                PlanStep(
                    kind="command",
                    target=router_name,
                    action="reload quagga daemons",
                    command="killall -HUP zebra 2>/dev/null; killall -HUP ospfd 2>/dev/null; killall -HUP bgpd 2>/dev/null",
                )
            )

    return ReconcilePlan(steps=steps, changed_files=sorted(set(changed_files)), changed_routers=sorted(set(changed_routers)))


def colorize(text: str, color: str) -> str:
    palette = {
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "cyan": "\033[36m",
        "dim": "\033[2m",
        "reset": "\033[0m",
    }
    return f"{palette[color]}{text}{palette['reset']}"


def format_plan(plan: ReconcilePlan) -> str:
    if not plan.steps:
        return colorize("No drift detected. The current output bundle already matches intent.", "green")

    lines: list[str] = [colorize("Reconcile plan", "cyan")]
    for step in plan.steps:
        if step.kind == "file":
            header = f"{step.action.upper()}: {step.target}"
            lines.append(colorize(header, "yellow"))
            if step.diff:
                lines.append(step.diff)
        elif step.kind == "command":
            lines.append(colorize(f"RELOAD: {step.target}", "yellow"))
            if step.command:
                lines.append(colorize(f"  {step.command}", "dim"))
        else:
            lines.append(f"{step.action}: {step.target}")
    return "\n".join(lines)
