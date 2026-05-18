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

# Maps template filename → output filename (None = computed dynamically)
TEMPLATE_MAP = {
    "ospfd.conf.j2":          "ospfd.conf",
    "zebra.conf.j2":          "zebra.conf",
    "named.conf.options.j2":  "named.conf.options",
    "named.conf.local.j2":    "named.conf.local",
    "zone.j2":                None,   # → db.<domain>
    "zone_reverse.j2":        None,   # → db.<reverse_prefix>
    "nginx_upstream.j2":      "nginx.conf",
}


class TemplateRenderer:
    """Render the Jinja2 templates used by the provisioning pipeline."""

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
        """Render all templates. Returns {output_filename: content}."""
        domain         = intent.get("organization", {}).get("domain", "example.net")
        reverse_prefix = intent.get("routing", {}).get("ospf", {}).get("reverse_prefix", "reverse")

        context = {
            "organization": intent.get("organization", {}),
            "networks":     intent.get("networks", []),
            "routing":      intent.get("routing", {}),
            "services":     intent.get("services", {}),
        }

        dynamic_names = {
            "zone.j2":         f"db.{domain}",
            "zone_reverse.j2": f"db.{reverse_prefix}",
        }

        results: dict[str, str] = {}
        for tmpl_name, out_name in TEMPLATE_MAP.items():
            if out_name is None:
                out_name = dynamic_names[tmpl_name]
            results[out_name] = self.render(tmpl_name, context)

        return results

    def write_bundle(self, intent: dict[str, Any], output_dir: str | Path) -> dict[str, Path]:
        """Render and write all files to output_dir. Returns {filename: Path}."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        written: dict[str, Path] = {}
        for filename, content in self.render_bundle(intent).items():
            dest = out / filename
            dest.write_text(content, encoding="utf-8")
            written[filename] = dest

        return written