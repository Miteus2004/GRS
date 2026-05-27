"""Validation tests for the YAML intent parser."""

from __future__ import annotations

import pytest

from engine.parser import IntentValidationError, validate_intent


def _base_intent() -> dict:
    return {
        "organization": {"domain": "myorg.net", "as_number": 65001},
        "networks": [
            {"name": "net1", "cidr": "10.0.1.0/29", "gateways": [{"name": "r1", "ip": "10.0.1.2"}]},
            {"name": "net2", "cidr": "10.0.1.8/29", "gateways": [{"name": "r2", "ip": "10.0.1.10"}]},
        ],
        "routing": {
            "ospf": {"area": 0, "router_id": "1.1.1.1", "networks": ["10.0.1.0/29", "10.0.1.8/29"]},
            "bgp": {"neighbors": [{"as": 65002, "neighbor_ip": "172.31.255.252"}]},
        },
        "services": {
            "dns": {"zones": {"myorg.net": [{"name": "dns", "ip": "172.16.123.138"}]}},
            "web": {"replicas": 1, "servers": [{"name": "www1", "ip": "172.16.123.130"}]},
            "monitoring": {"nagios_url": "http://172.16.123.139/nagios"},
        },
        "management": [{"name": "router1", "host": "10.0.1.2"}],
    }


def test_validate_rejects_invalid_as_number():
    intent = _base_intent()
    intent["organization"]["as_number"] = 0
    with pytest.raises(IntentValidationError, match="organization.as_number"):
        validate_intent(intent)


def test_validate_rejects_overlapping_subnets():
    intent = _base_intent()
    intent["networks"][1]["cidr"] = "10.0.1.4/30"
    with pytest.raises(IntentValidationError, match="overlaps"):
        validate_intent(intent)


def test_validate_rejects_duplicate_management_ips():
    intent = _base_intent()
    intent["management"].append({"name": "router2", "host": "10.0.1.2"})
    with pytest.raises(IntentValidationError, match="Duplicate management host IP"):
        validate_intent(intent)
