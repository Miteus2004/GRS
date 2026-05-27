"""Ryu REST API client — push OpenFlow rules from the IBN engine."""

from __future__ import annotations

import os
from typing import Any

from .policy import PATH_PROFILES, build_flow_payload, decide_path, summarize_decision

try:
    import requests
except ImportError as exc:
    requests = None
    _requests_error = exc
else:
    _requests_error = None

class RyuClient:
    """Thin wrapper around the Ryu REST API for flow rule management."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("RYU_URL", "http://ibn_ryu:8080")).rstrip("/")

    def _post(self, path: str, payload: dict) -> Any:
        if requests is None:
            raise RuntimeError("requests is required") from _requests_error
        r = requests.post(f"{self.base_url}{path}", json=payload, timeout=5)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str, payload: dict) -> Any:
        if requests is None:
            raise RuntimeError("requests is required") from _requests_error
        r = requests.delete(f"{self.base_url}{path}", json=payload, timeout=5)
        r.raise_for_status()
        return r.json()

    def _get(self, path: str) -> Any:
        if requests is None:
            raise RuntimeError("requests is required") from _requests_error
        r = requests.get(f"{self.base_url}{path}", timeout=5)
        r.raise_for_status()
        return r.json()

    def push_flow(self, dpid: int, priority: int, match: dict, actions: list) -> Any:
        return self._post("/ibn/flow", {
            "dpid": dpid, "priority": priority,
            "match": match, "actions": actions,
        })

    def delete_flow(self, dpid: int, match: dict) -> Any:
        return self._delete("/ibn/flow", {"dpid": dpid, "match": match})

    def get_flows(self, dpid: int) -> Any:
        return self._get(f"/stats/flow/{dpid}")

    def activate_path(self, dpid: int, profile: str) -> Any:
        """Activate a named path profile (primary or backup)."""
        payload = build_flow_payload(dpid, profile)
        return self.push_flow(payload["dpid"], payload["priority"], payload["match"], payload["actions"])

    def list_switches(self) -> list[int]:
        data = self._get("/ibn/switches")
        if isinstance(data, dict):
            return data.get("switches", [])
        return data


def choose_path(congested_hosts: list[str]) -> str:
    """Return the path name the engine should activate."""
    return decide_path(congested_hosts).path


def path_summary(congested_hosts: list[str]) -> dict[str, Any]:
    """Return a compact summary for status output and tests."""
    return summarize_decision(congested_hosts)
