"""Phase 2 congestion policy and path selection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PATH_PROFILES: dict[str, dict[str, Any]] = {
    "primary": {
        "name": "primary",
        "description": "Default low-latency path",
        "priority": 200,
        "match": {"eth_type": 0x0800},
        "actions": [{"type": "OUTPUT", "port": 1}],
    },
    "backup": {
        "name": "backup",
        "description": "Failover path used when congestion is detected",
        "priority": 250,
        "match": {"eth_type": 0x0800},
        "actions": [{"type": "OUTPUT", "port": 2}],
    },
}


@dataclass(frozen=True)
class CongestionDecision:
    path: str
    congested_hosts: list[str]


def decide_path(congested_hosts: list[str]) -> CongestionDecision:
    """Choose backup path whenever at least one host is congested."""
    path = "backup" if congested_hosts else "primary"
    return CongestionDecision(path=path, congested_hosts=sorted(congested_hosts))


def flow_profile(path: str) -> dict[str, Any]:
    """Return the named flow profile or raise KeyError."""
    return PATH_PROFILES[path]


def build_flow_payload(dpid: int, path: str) -> dict[str, Any]:
    """Serialize the named path profile into the Ryu REST payload."""
    profile = flow_profile(path)
    return {
        "dpid": dpid,
        "priority": profile["priority"],
        "match": profile["match"],
        "actions": profile["actions"],
    }


def summarize_decision(congested_hosts: list[str]) -> dict[str, Any]:
    """Convenience wrapper for engine status output and tests."""
    decision = decide_path(congested_hosts)
    return {
        "path": decision.path,
        "congested_hosts": decision.congested_hosts,
        "profiles": list(PATH_PROFILES.keys()),
    }