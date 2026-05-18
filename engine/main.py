"""Command-line entry point for the IBN reconciliation loop."""

from __future__ import annotations

import argparse

from .parser import load_intent
from .renderer import TemplateRenderer


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the IBN reconciliation loop")
    parser.add_argument(
        "--intent",
        default="intent.example.yaml",
        help="Path to the YAML intent file",
    )
    parser.add_argument(
        "--templates",
        default="templates",
        help="Path to the Jinja2 template directory",
    )
    parser.add_argument(
        "--outdir",
        default="out",
        help="Directory to write rendered config files into",
    )
    return parser


def reconcile(intent_path: str, template_dir: str, output_dir: str) -> int:
    """Core reconciliation logic: load intent → render → write files."""
    intent = load_intent(intent_path)
    renderer = TemplateRenderer(template_dir)
    written = renderer.write_bundle(intent, output_dir)
    for filename, path in written.items():
        print(f"  wrote {filename} → {path}")
    print(f"Rendered {len(written)} config files into '{output_dir}'")
    return 0


def main() -> int:
    args = build_argument_parser().parse_args()
    return reconcile(args.intent, args.templates, args.outdir)


if __name__ == "__main__":
    raise SystemExit(main())