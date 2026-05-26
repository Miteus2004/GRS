"""Render configuration files from the parsed intent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
except ImportError as exc:  # pragma: no cover
    Environment = None
    FileSystemLoader = None
    StrictUndefined = None
    _jinja_import_error = exc
else:
    _jinja_import_error = None

TEMPLATE_MAP = {
    "ospfd.conf.j2":         "ospfd.conf",
    "zebra.conf.j2":         "zebra.conf",
    "bgpd.conf.j2":          "bgpd.conf",
    "named.conf.options.j2": "named.conf.options",
    "named.conf.local.j2":   "named.conf.local",
    "zone.j2":               None,   # → db.<domain>
    "zone_reverse.j2":       None,   # → db.<reverse_prefix>
    "nginx_upstream.j2":     "nginx.conf",
}


class TemplateRenderer:
    def __init__(self, template_dir: str | Path) -> None:
        self.template_dir = Path(template_dir)

    def render(self, template_name: str, context: dict[str, Any]) -> str:
        if Environment is None:
            raise RuntimeError("Jinja2 is required") from _jinja_import_error
        env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        return env.get_template(template_name).render(**context)

    def render_bundle(self, intent: dict[str, Any]) -> dict[str, str]:
        domain         = intent.get("organization", {}).get("domain", "example.net")
        reverse_prefix = intent.get("routing", {}).get("ospf", {}).get("reverse_prefix", "reverse")
        context = {
            "organization": intent.get("organization", {}),
            "networks":     intent.get("networks", []),
            "routing":      intent.get("routing", {}),
            "services":     intent.get("services", {}),
        }
        dynamic = {"zone.j2": f"db.{domain}", "zone_reverse.j2": f"db.{reverse_prefix}"}
        results: dict[str, str] = {}
        for tmpl, out in TEMPLATE_MAP.items():
            if out is None:
                out = dynamic[tmpl]
            results[out] = self.render(tmpl, context)
        return results

    def write_bundle(self, intent: dict[str, Any], output_dir: str | Path) -> dict[str, Path]:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        written: dict[str, Path] = {}

        # Write global files
        bundle = self.render_bundle(intent)
        for filename, content in bundle.items():
            dest = out / filename
            dest.write_text(content, encoding="utf-8")
            written[filename] = dest

        # Render per-router configs (ospfd/zebra) when management inventory exists.
        # Use each router's host IP as its OSPF router-id.
        for entry in intent.get("management", []):
            name = entry.get("name")
            host = entry.get("host")
            if not name or not host:
                continue
            router_dir = out / name
            router_dir.mkdir(parents=True, exist_ok=True)

            # Build a context copy and set router-specific router-id
            context = {
                "organization": intent.get("organization", {}),
                "networks": intent.get("networks", []),
                "routing": dict(intent.get("routing", {})),
                "services": intent.get("services", {}),
            }
            routing = context.setdefault("routing", {})
            ospf = routing.setdefault("ospf", {})
            ospf["router_id"] = host

            # Render ospfd and zebra for this router
            for tmpl_name, out_name in (("ospfd.conf.j2", "ospfd.conf"), ("zebra.conf.j2", "zebra.conf")):
                rendered = self.render(tmpl_name, context)
                dest = router_dir / out_name
                dest.write_text(rendered, encoding="utf-8")
                written[f"{name}/{out_name}"] = dest

        return written
