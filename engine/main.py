"""Command-line entry point for the IBN reconciliation loop."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .parser import load_intent
from .renderer import TemplateRenderer
from .provisioner import Provisioner
from .monitor import NagiosClient
from .sdn import RyuClient


def build_argument_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="IBN reconciliation loop")
    p.add_argument("--intent",    default="intent.example.yaml")
    p.add_argument("--templates", default="templates")
    p.add_argument("--outdir",    default="out")
    p.add_argument("--provision", action="store_true",
                   help="SSH into routers and reload Quagga after rendering")
    p.add_argument("--monitor",   action="store_true",
                   help="Poll Nagios and trigger SDN rerouting if congestion detected")
    p.add_argument("--ryu-url",   default="http://localhost:8080")
    return p


def reconcile(
    intent_path: str,
    template_dir: str,
    output_dir: str,
    provision: bool = False,
    monitor: bool = False,
    ryu_url: str = "http://localhost:8080",
) -> int:
    print(f"[IBN] Loading intent from {intent_path}")
    intent = load_intent(intent_path)

    print("[IBN] Rendering configuration bundle")
    renderer = TemplateRenderer(template_dir)
    written  = renderer.write_bundle(intent, output_dir)
    for name, path in written.items():
        print(f"  {name} → {path}")
    print(f"[IBN] {len(written)} files written to '{output_dir}'")

    if provision:
        print("[IBN] Provisioning routers via SSH")
        provisioner = Provisioner.from_intent(intent)
        results = provisioner.apply({n: Path(p).read_text() for n, p in written.items()})
        for router, status in results.items():
            tag = "OK" if "ERROR" not in status else "FAIL"
            print(f"  [{tag}] {router}")

    if monitor:
        nagios_url = intent.get("services", {}).get("monitoring", {}).get("nagios_url", "")
        if not nagios_url:
            print("[IBN] No nagios_url in intent, skipping monitor check")
        else:
            print(f"[IBN] Polling Nagios at {nagios_url}")
            try:
                client = NagiosClient(nagios_url)
                bad = client.congested_hosts()
                if bad:
                    print(f"[IBN] Congestion detected on: {bad} — activating backup path")
                    ryu = RyuClient(ryu_url)
                    for dpid in ryu.list_switches():
                        ryu.activate_path(dpid, "backup")
                else:
                    print("[IBN] All hosts OK — primary path active")
            except Exception as exc:
                print(f"[IBN] Monitor check failed: {exc}", file=sys.stderr)

    return 0


def main() -> int:
    args = build_argument_parser().parse_args()
    return reconcile(
        args.intent, args.templates, args.outdir,
        provision=args.provision,
        monitor=args.monitor,
        ryu_url=args.ryu_url,
    )


if __name__ == "__main__":
    raise SystemExit(main())
