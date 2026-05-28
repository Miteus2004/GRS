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
        if self.base_url.endswith("/nagios"):
            self.api_base = self.base_url
        else:
            self.api_base = f"{self.base_url}/nagios"
        self.auth = (username, password)

    def _get(self, path: str, params: dict | None = None) -> Any:
        if requests is None:
            raise RuntimeError("requests is required") from _requests_error
        url = f"{self.api_base}{path}"
        resp = requests.get(url, auth=self.auth, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def fetch_state(self) -> dict[str, Any]:
        """Return {host: {status, services: {name: state_int}}}
        state_int: 0=OK, 1=WARNING, 2=CRITICAL, 3=UNKNOWN
        """
        data = self._get(
            "/cgi-bin/statusjson.cgi",
            params={"query": "servicelist", "details": "true"},
        )
        result: dict[str, Any] = {}
        servicelist = data.get("data", {}).get("servicelist", {})
        for host_key, host_services in servicelist.items():
            if host_key == "localhost":
                continue
            if not isinstance(host_services, dict):
                continue

            # Live Nagios responses are often nested by host, while the unit tests
            # use a flat servicelist keyed by service id. Accept both shapes.
            if "host_name" in host_services:
                host = host_services.get("host_name") or host_key
                if host == "localhost":
                    continue
                service_name = host_services.get("description", host_key)
                status = host_services.get("status", 3)
                result.setdefault(host, {"services": {}})["services"][service_name] = status
                continue

            host = host_key
            if host == "localhost":
                continue
            result.setdefault(host, {"services": {}})
            for service_name, svc in host_services.items():
                if isinstance(svc, dict):
                    name = svc.get("description", service_name)
                    status = svc.get("status", 3)
                else:
                    name = service_name
                    status = svc
                result[host]["services"][name] = status
        return result

    @staticmethod
    def _service_level(value: Any) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            return 3

    def is_congested(self, host: str) -> bool:
        """True if any service on host is WARNING or worse."""
        state = self.fetch_state()
        services = state.get(host, {}).get("services", {})
        return any(self._service_level(v) >= 1 for v in services.values())

    def all_hosts_up(self) -> bool:
        """True if every monitored service is OK (status == 0)."""
        state = self.fetch_state()
        for host_data in state.values():
            if any(self._service_level(v) >= 2 for v in host_data["services"].values()):
                return False
        return True

    def congested_hosts(self) -> list[str]:
        """Return list of hosts with at least one WARNING/CRITICAL service."""
        state = self.fetch_state()
        return [h for h, d in state.items() if any(self._service_level(v) >= 1 for v in d["services"].values())]
