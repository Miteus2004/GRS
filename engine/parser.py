"""Load and validate the declarative network intent."""

from __future__ import annotations

import ipaddress
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


def _require_mapping(section: Any, name: str) -> dict[str, Any]:
    if not isinstance(section, dict):
        raise IntentValidationError(f"Section '{name}' must be a mapping")
    return section


def _require_list(section: Any, name: str) -> list[Any]:
    if not isinstance(section, list):
        raise IntentValidationError(f"Section '{name}' must be a list")
    return section


def _parse_network(cidr: Any, label: str) -> ipaddress._BaseNetwork:
    if not isinstance(cidr, str):
        raise IntentValidationError(f"{label} must be a CIDR string")
    try:
        return ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        raise IntentValidationError(f"{label} is not a valid network: {cidr}") from exc


def _parse_ip(value: Any, label: str) -> ipaddress._BaseAddress:
    if not isinstance(value, str):
        raise IntentValidationError(f"{label} must be an IP address string")
    try:
        return ipaddress.ip_address(value)
    except ValueError as exc:
        raise IntentValidationError(f"{label} is not a valid IP address: {value}") from exc


def _ensure_positive_int(value: Any, label: str, minimum: int = 1, maximum: int = 4294967295) -> int:
    if not isinstance(value, int):
        raise IntentValidationError(f"{label} must be an integer")
    if not (minimum <= value <= maximum):
        raise IntentValidationError(f"{label} must be between {minimum} and {maximum}")
    return value


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

    organization = _require_mapping(intent_data["organization"], "organization")
    networks = _require_list(intent_data["networks"], "networks")
    routing = _require_mapping(intent_data["routing"], "routing")
    services = _require_mapping(intent_data["services"], "services")

    if "domain" not in organization:
        raise IntentValidationError("organization.domain is required")

    _ensure_positive_int(organization.get("as_number"), "organization.as_number")

    seen_networks: list[ipaddress._BaseNetwork] = []
    seen_management_hosts: set[str] = set()
    seen_gateway_ips: set[str] = set()
    seen_bgp_neighbors: set[str] = set()

    for entry in networks:
        if not isinstance(entry, dict):
            raise IntentValidationError("Each item in 'networks' must be a mapping")
        network_name = entry.get("name")
        if not isinstance(network_name, str) or not network_name:
            raise IntentValidationError("Each network must have a non-empty 'name'")
        network = _parse_network(entry.get("cidr"), f"networks[{network_name}].cidr")
        for other in seen_networks:
            if network.overlaps(other):
                raise IntentValidationError(f"Network {network} overlaps with {other}")
        seen_networks.append(network)

        gateways = _require_list(entry.get("gateways", []), f"networks[{network_name}].gateways")
        for gateway in gateways:
            if not isinstance(gateway, dict):
                raise IntentValidationError(f"Gateways for network '{network_name}' must be mappings")
            gateway_name = gateway.get("name")
            if not isinstance(gateway_name, str) or not gateway_name:
                raise IntentValidationError(f"network '{network_name}' gateways require a name")
            gateway_ip = _parse_ip(gateway.get("ip"), f"networks[{network_name}].gateways[{gateway_name}].ip")
            if gateway_ip not in network:
                raise IntentValidationError(
                    f"Gateway IP {gateway_ip} for network '{network_name}' is outside {network}"
                )
            if gateway_ip.compressed in seen_gateway_ips:
                raise IntentValidationError(f"Duplicate gateway IP detected: {gateway_ip}")
            seen_gateway_ips.add(gateway_ip.compressed)

    ospf = _require_mapping(routing.get("ospf", {}), "routing.ospf")
    if "area" in ospf:
        _ensure_positive_int(ospf["area"], "routing.ospf.area", minimum=0)
    if "router_id" in ospf:
        _parse_ip(ospf["router_id"], "routing.ospf.router_id")
    ospf_networks = _require_list(ospf.get("networks", []), "routing.ospf.networks")
    for idx, cidr in enumerate(ospf_networks):
        ospf_net = _parse_network(cidr, f"routing.ospf.networks[{idx}]")
        if not any(ospf_net.subnet_of(network) or ospf_net == network for network in seen_networks):
            raise IntentValidationError(
                f"routing.ospf.networks[{idx}] ({ospf_net}) must match a declared top-level network"
            )

    bgp = _require_mapping(routing.get("bgp", {}), "routing.bgp")
    bgp_neighbors = _require_list(bgp.get("neighbors", []), "routing.bgp.neighbors")
    for idx, neighbor in enumerate(bgp_neighbors):
        if not isinstance(neighbor, dict):
            raise IntentValidationError("Each BGP neighbor must be a mapping")
        as_number = _ensure_positive_int(neighbor.get("as"), f"routing.bgp.neighbors[{idx}].as")
        if as_number in (0,):
            raise IntentValidationError(f"routing.bgp.neighbors[{idx}].as must be positive")
        neighbor_ip = _parse_ip(neighbor.get("neighbor_ip"), f"routing.bgp.neighbors[{idx}].neighbor_ip")
        if neighbor_ip.compressed in seen_bgp_neighbors:
            raise IntentValidationError(f"Duplicate BGP neighbor IP detected: {neighbor_ip}")
        seen_bgp_neighbors.add(neighbor_ip.compressed)

    dns = _require_mapping(services.get("dns", {}), "services.dns")
    zones = _require_mapping(dns.get("zones", {}), "services.dns.zones")
    for zone_name, records in zones.items():
        if not isinstance(records, list):
            raise IntentValidationError(f"services.dns.zones['{zone_name}'] must be a list")
        for idx, record in enumerate(records):
            if not isinstance(record, dict):
                raise IntentValidationError(f"services.dns.zones['{zone_name}'][{idx}] must be a mapping")
            if "ip" in record:
                _parse_ip(record["ip"], f"services.dns.zones['{zone_name}'][{idx}].ip")

    web = _require_mapping(services.get("web", {}), "services.web")
    if "replicas" in web:
        _ensure_positive_int(web["replicas"], "services.web.replicas")
    servers = _require_list(web.get("servers", []), "services.web.servers")
    seen_web_ips: set[str] = set()
    for idx, server in enumerate(servers):
        if not isinstance(server, dict):
            raise IntentValidationError("Each web server entry must be a mapping")
        server_ip = _parse_ip(server.get("ip"), f"services.web.servers[{idx}].ip")
        if server_ip.compressed in seen_web_ips:
            raise IntentValidationError(f"Duplicate web server IP detected: {server_ip}")
        seen_web_ips.add(server_ip.compressed)

    management = _require_list(intent_data.get("management", []), "management")
    for idx, entry in enumerate(management):
        if not isinstance(entry, dict):
            raise IntentValidationError("Each management entry must be a mapping")
        if "name" not in entry:
            raise IntentValidationError(f"management[{idx}].name is required")
        host_ip = _parse_ip(entry.get("host"), f"management[{idx}].host")
        if host_ip.compressed in seen_management_hosts:
            raise IntentValidationError(f"Duplicate management host IP detected: {host_ip}")
        seen_management_hosts.add(host_ip.compressed)