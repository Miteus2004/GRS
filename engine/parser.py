"""Load and validate the declarative network intent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    yaml = None
    _yaml_import_error = exc
else:
    _yaml_import_error = None


REQUIRED_TOP_LEVEL_KEYS = ("organization", "networks", "routing", "services")


class IntentValidationError(ValueError):
    """Raised when the intent file is structurally invalid."""


def load_intent(intent_path: str | Path) -> dict[str, Any]:
    """Load the YAML intent file and validate the minimum contract."""
    if yaml is None:
        raise RuntimeError("PyYAML is required") from _yaml_import_error

    path = Path(intent_path)
    with path.open("r", encoding="utf-8") as fh:
        intent_data = yaml.safe_load(fh) or {}

    validate_intent(intent_data)
    return intent_data


def validate_intent(intent_data: Any) -> None:
    """Check the coarse shape of the YAML document."""
    if not isinstance(intent_data, dict):
        raise IntentValidationError("The intent must be a mapping at the top level")

    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in intent_data]
    if missing:
        raise IntentValidationError(f"Missing required sections: {', '.join(missing)}")

    # networks is a list, not a dict — check it separately
    if not isinstance(intent_data["networks"], list):
        raise IntentValidationError("Section 'networks' must be a list")

    for key in ("organization", "routing", "services"):
        if not isinstance(intent_data[key], dict):
            raise IntentValidationError(f"Section '{key}' must be a mapping")

    if "domain" not in intent_data["organization"]:
        raise IntentValidationError("organization.domain is required")