"""Query monitoring data and feed it back into the reconciliation loop."""

from __future__ import annotations

from typing import Any


class NagiosClient:
    """Minimal client wrapper for Nagios polling."""

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def fetch_state(self) -> dict[str, Any]:
        """Return the monitoring snapshot.

        The real HTTP call will be added after the Nagios container is
        running in the lab environment.
        """
        raise NotImplementedError("Nagios polling is not implemented yet")