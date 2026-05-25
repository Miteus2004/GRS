"""Query Nagios monitoring and feed state back into the reconciliation loop."""

from __future__ import annotations

from typing import Any

try:
    import requests
except ImportError as exc:
    requests = None
    _requests_error = exc
else:
    _requests_error = None


class NagiosClient:
    """HTTP client for the Nagios CGI status API."""

    def __init__(
        self,
        base_url: str,
        username: str = "nagiosadmin",
        password: str = "nagios",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = (username, password)

    def _get(self, path: str, params: dict | None = None) -> Any:
        if requests is None:
            raise RuntimeError("requests is required") from _requests_error
        url = f"{self.base_url}{path}"
        resp = requests.get(url, auth=self.auth, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def fetch_state(self) -> dict[str, Any]:
        """Return {host: {status, services: {name: state_int}}}
        state_int: 0=OK, 1=WARNING, 2=CRITICAL, 3=UNKNOWN
        """
        data = self._get(
            "/nagios/cgi-bin/statusjson.cgi",
            params={"query": "servicelist", "details": "true"},
        )
        result: dict[str, Any] = {}
        for svc in data.get("data", {}).get("servicelist", {}).values():
            host = svc["host_name"]
            if host not in result:
                result[host] = {"services": {}}
            result[host]["services"][svc["description"]] = svc["status"]
        return result

    def is_congested(self, host: str) -> bool:
        """True if any service on host is WARNING or worse."""
        state = self.fetch_state()
        services = state.get(host, {}).get("services", {})
        return any(v >= 1 for v in services.values())

    def all_hosts_up(self) -> bool:
        """True if every monitored service is OK (status == 0)."""
        state = self.fetch_state()
        for host_data in state.values():
            if any(v >= 2 for v in host_data["services"].values()):
                return False
        return True

    def congested_hosts(self) -> list[str]:
        """Return list of hosts with at least one WARNING/CRITICAL service."""
        state = self.fetch_state()
        return [h for h, d in state.items() if any(v >= 1 for v in d["services"].values())]
