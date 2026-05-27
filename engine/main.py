"""Command-line entry point for the IBN reconciliation loop."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .parser import load_intent
from .renderer import TemplateRenderer
from .provisioner import Provisioner
from .monitor import NagiosClient
from .sdn import RyuClient, choose_path, path_summary
from .planner import build_reconcile_plan, format_plan


def build_argument_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="IBN reconciliation loop")
    p.add_argument("--intent",    default="intent.yaml")
    p.add_argument("--templates", default="templates")
    p.add_argument("--outdir",    default="out")
    p.add_argument("--dry-run", "--plan", action="store_true",
                   help="Render and diff the desired state without applying changes")
    p.add_argument("--provision", action="store_true",
                   help="SSH into routers and reload Quagga after rendering")
    p.add_argument("--monitor",   action="store_true",
                   help="Poll Nagios and trigger SDN rerouting if congestion detected")
    p.add_argument("--loop", action="store_true",
                   help="Run reconciliation continuously instead of once")
    p.add_argument("--interval", type=int, default=30,
                   help="Seconds between reconciliation passes in loop mode")
    p.add_argument("--ryu-url",   default="http://localhost:8080")
    return p


def reconcile(
    intent_path: str,
    template_dir: str,
    output_dir: str,
    provision: bool = False,
    monitor: bool = False,
    dry_run: bool = False,
    ryu_url: str = "http://localhost:8080",
) -> int:
    print(f"[IBN] Loading intent from {intent_path}")
    intent = load_intent(intent_path)

    plan = build_reconcile_plan(intent, template_dir, output_dir)
    if dry_run:
        print(format_plan(plan))
        return 0

    if plan.has_changes:
        print("[IBN] Drift detected; rendering updated configuration bundle")
    else:
        print("[IBN] Desired state already matches the current output bundle")

    print("[IBN] Rendering configuration bundle")
    renderer = TemplateRenderer(template_dir)
    written  = renderer.write_bundle(intent, output_dir)
    for name, path in written.items():
        print(f"  {name} → {path}")
    print(f"[IBN] {len(written)} files written to '{output_dir}'")

    if provision and plan.has_changes:
        print("[IBN] Provisioning routers via SSH")
        provisioner = Provisioner.from_intent(intent)
        results = provisioner.apply({n: Path(p).read_text() for n, p in written.items()})
        for router, status in results.items():
            tag = "OK" if "ERROR" not in status else "FAIL"
            print(f"  [{tag}] {router}")
    elif provision:
        print("[IBN] Provisioning skipped because no drift was detected")

    if monitor:
        nagios_url = intent.get("services", {}).get("monitoring", {}).get("nagios_url", "")
        if not nagios_url:
            print("[IBN] No nagios_url in intent, skipping monitor check")
        else:
            print(f"[IBN] Polling Nagios at {nagios_url}")
            try:
                client = NagiosClient(nagios_url)
                bad = client.congested_hosts()
                ryu = RyuClient(ryu_url)
                switches = ryu.list_switches()
                if bad:
                    decision = path_summary(bad)
                    path = choose_path(bad)
                    print(f"[IBN] Congestion detected on: {bad} — activating {path} path")
                    for dpid in switches:
                        ryu.activate_path(dpid, path)
                else:
                    print("[IBN] All hosts OK — activating primary path")
                    for dpid in switches:
                        ryu.activate_path(dpid, "primary")
            except Exception as exc:
                print(f"[IBN] Monitor check failed: {exc}", file=sys.stderr)

    return 0


def reconcile_loop(
    intent_path: str,
    template_dir: str,
    output_dir: str,
    provision: bool = False,
    monitor: bool = False,
    dry_run: bool = False,
    ryu_url: str = "http://localhost:8080",
    interval: int = 30,
) -> int:
    while True:
        try:
            exit_code = reconcile(
                intent_path,
                template_dir,
                output_dir,
                provision=provision,
                monitor=monitor,
                dry_run=dry_run,
                ryu_url=ryu_url,
            )
            if not dry_run:
                print(f"[IBN] Sleeping {interval}s before next reconciliation pass")
                time.sleep(interval)
            else:
                return exit_code
        except KeyboardInterrupt:
            print("[IBN] Loop interrupted by user")
            return 0


def main() -> int:
    args = build_argument_parser().parse_args()
    runner = reconcile_loop if args.loop else reconcile
    return runner(
        args.intent,
        args.templates,
        args.outdir,
        provision=args.provision,
        monitor=args.monitor,
        dry_run=args.dry_run,
        ryu_url=args.ryu_url,
        **({"interval": args.interval} if args.loop else {}),
    )


if __name__ == "__main__":
    raise SystemExit(main())
