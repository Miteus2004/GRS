"""Provision rendered configurations over SSH using Netmiko."""

from __future__ import annotations

from typing import Any


class Provisioner:
    """Apply rendered configuration to routers and services.

    Netmiko integration will be filled in once the templates are stable
    and the lab environment is available.
    """

    def __init__(self, inventory: dict[str, Any] | None = None) -> None:
        self.inventory = inventory or {}

    def apply(self, rendered_configs: dict[str, str]) -> None:
        """Apply the rendered configuration bundle to devices.

        Placeholder — real implementation sends each config to the
        corresponding device via Netmiko ConnectHandler.send_config_set().
        """
        raise NotImplementedError(
            "Provisioning is not implemented yet. "
            "Use write_bundle() from TemplateRenderer to inspect rendered files first."
        )