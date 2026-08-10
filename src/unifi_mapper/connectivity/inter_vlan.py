"""Inter-VLAN routing checks between UniFi endpoints."""

from __future__ import annotations

import ipaddress
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, Literal, cast
from unifi_mapper.core.utils.client import UniFiClient


Verdict = Literal['allow', 'deny', 'unknown']


class InterVLANEndpoint(BaseModel):
    """Resolved endpoint for an inter-VLAN routing check."""

    identifier: str
    resolved: bool = False
    name: str = ''
    ip: str = ''
    mac: str = ''
    vlan_id: int | None = None
    network_id: str | None = None
    network_name: str = ''


class InterVLANRoutingReport(BaseModel):
    """Inter-VLAN routing verdict between two endpoints."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    source: InterVLANEndpoint
    destination: InterVLANEndpoint
    source_vlan: int | None = None
    destination_vlan: int | None = None
    route_required: bool = False
    verdict: Verdict = 'unknown'
    validation_passed: bool = False
    matching_rules: list[str] = Field(default_factory=list)
    blocking_rule: str | None = None
    recommendations: list[str] = Field(default_factory=list)


async def check_inter_vlan_routing(
    source: str,
    destination: str,
    protocol: str = 'icmp',
    port: str | None = None,
) -> InterVLANRoutingReport:
    """Fetch UniFi data and check whether two endpoints can route across VLANs."""
    async with UniFiClient() as client:
        devices = _data_list(await client.get(client.build_path('stat/device')))
        clients = _data_list(await client.get(client.build_path('stat/sta')))
        networks = _data_list(await client.get(client.build_path('rest/networkconf')))
        firewall_rules = _data_list(await client.get(client.build_path('rest/firewallrule')))

    return check_inter_vlan_routing_from_data(
        source=source,
        destination=destination,
        protocol=protocol,
        port=port,
        clients=clients,
        devices=devices,
        networks=networks,
        firewall_rules=firewall_rules,
    )


def check_inter_vlan_routing_from_data(
    source: str,
    destination: str,
    clients: list[dict[str, Any]],
    devices: list[dict[str, Any]],
    networks: list[dict[str, Any]],
    firewall_rules: list[dict[str, Any]],
    protocol: str = 'icmp',
    port: str | None = None,
) -> InterVLANRoutingReport:
    """Check endpoint VLANs and first matching LAN firewall rule from supplied data."""
    source_endpoint = _resolve_endpoint(source, clients, devices, networks)
    destination_endpoint = _resolve_endpoint(destination, clients, devices, networks)
    recommendations: list[str] = []

    if not source_endpoint.resolved:
        recommendations.append('Resolve the source endpoint before checking inter-VLAN routing.')
    if not destination_endpoint.resolved:
        recommendations.append(
            'Resolve the destination endpoint before checking inter-VLAN routing.'
        )

    source_vlan = source_endpoint.vlan_id
    destination_vlan = destination_endpoint.vlan_id
    route_required = (
        source_endpoint.resolved
        and destination_endpoint.resolved
        and source_vlan != destination_vlan
    )

    verdict: Verdict = 'unknown'
    matching_rule_names: list[str] = []
    blocking_rule: str | None = None

    if source_endpoint.resolved and destination_endpoint.resolved:
        if not route_required:
            verdict = 'allow'
            recommendations.append(
                'Endpoints are in the same VLAN; inter-VLAN routing is not required.'
            )
        else:
            matching_rules = _matching_firewall_rules(
                source_endpoint,
                destination_endpoint,
                firewall_rules,
                protocol,
                port,
            )
            matching_rule_names = [
                str(rule.get('name') or rule.get('_id') or 'Unnamed rule')
                for rule in matching_rules
            ]
            if matching_rules:
                first_rule = matching_rules[0]
                verdict = _action_to_verdict(str(first_rule.get('action', 'accept')))
                if verdict == 'deny':
                    blocking_rule = str(first_rule.get('name') or first_rule.get('_id'))
                    recommendations.append(
                        f'Traffic is blocked by "{blocking_rule}"; review rule order or intent.'
                    )
            else:
                verdict = 'allow'
                recommendations.append(
                    'No specific LAN firewall rule matched; default inter-VLAN policy appears to allow.'
                )

    return InterVLANRoutingReport(
        source=source_endpoint,
        destination=destination_endpoint,
        source_vlan=source_vlan,
        destination_vlan=destination_vlan,
        route_required=route_required,
        verdict=verdict,
        validation_passed=verdict == 'allow',
        matching_rules=matching_rule_names,
        blocking_rule=blocking_rule,
        recommendations=recommendations,
    )


def _resolve_endpoint(
    identifier: str,
    clients: list[dict[str, Any]],
    devices: list[dict[str, Any]],
    networks: list[dict[str, Any]],
) -> InterVLANEndpoint:
    normalized = identifier.strip().lower()

    for item in [*clients, *devices]:
        if _endpoint_matches(normalized, item):
            vlan_id = _endpoint_vlan(item)
            network = _network_for_vlan_or_ip(vlan_id, str(item.get('ip') or ''), networks)
            return InterVLANEndpoint(
                identifier=identifier,
                resolved=True,
                name=str(
                    item.get('hostname') or item.get('display_name') or item.get('name') or ''
                ),
                ip=str(item.get('ip') or ''),
                mac=str(item.get('mac') or ''),
                vlan_id=vlan_id,
                network_id=network.get('_id') if network else None,
                network_name=str(network.get('name') if network else ''),
            )

    network = _network_for_ip(identifier, networks)
    if network is not None:
        return InterVLANEndpoint(
            identifier=identifier,
            resolved=True,
            ip=identifier,
            vlan_id=_as_int(network.get('vlan'), default=1),
            network_id=str(network.get('_id') or ''),
            network_name=str(network.get('name') or ''),
        )

    return InterVLANEndpoint(identifier=identifier)


def _endpoint_matches(normalized: str, item: dict[str, Any]) -> bool:
    candidates = [
        item.get('ip'),
        item.get('mac'),
        item.get('hostname'),
        item.get('display_name'),
        item.get('name'),
    ]
    return any(str(candidate).lower() == normalized for candidate in candidates if candidate)


def _endpoint_vlan(item: dict[str, Any]) -> int | None:
    if item.get('vlan') is not None:
        return _as_int(item.get('vlan'), default=1)
    config = item.get('config')
    if isinstance(config, dict):
        config_data = cast(dict[str, Any], config)
        if config_data.get('vlan') is not None:
            return _as_int(config_data.get('vlan'), default=1)
    return 1


def _network_for_vlan_or_ip(
    vlan_id: int | None,
    ip: str,
    networks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if vlan_id is not None:
        for network in networks:
            if _as_int(network.get('vlan'), default=1) == vlan_id:
                return network
    return _network_for_ip(ip, networks)


def _network_for_ip(identifier: str, networks: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        ip_address = ipaddress.IPv4Address(identifier)
    except ipaddress.AddressValueError:
        return None

    for network in networks:
        subnet = network.get('ip_subnet')
        if not subnet:
            continue
        try:
            if ip_address in ipaddress.IPv4Network(str(subnet), strict=False):
                return network
        except ValueError:
            continue
    return None


def _matching_firewall_rules(
    source: InterVLANEndpoint,
    destination: InterVLANEndpoint,
    firewall_rules: list[dict[str, Any]],
    protocol: str,
    port: str | None,
) -> list[dict[str, Any]]:
    rules = [
        rule for rule in firewall_rules if _rule_matches(rule, source, destination, protocol, port)
    ]
    return sorted(rules, key=lambda rule: _as_int(rule.get('rule_index'), default=9999))


def _rule_matches(
    rule: dict[str, Any],
    source: InterVLANEndpoint,
    destination: InterVLANEndpoint,
    protocol: str,
    port: str | None,
) -> bool:
    if not _as_bool(rule.get('enabled'), default=True):
        return False
    if str(rule.get('ruleset', 'LAN_IN')).upper() not in ('LAN_IN', 'LAN_LOCAL'):
        return False
    rule_protocol = str(rule.get('protocol', 'all')).lower()
    if rule_protocol not in ('all', protocol.lower()):
        return False
    rule_port = str(rule.get('dst_port') or '')
    if port and rule_port and rule_port != str(port):
        return False

    source_id = str(rule.get('src_networkconf_id') or 'any')
    destination_id = str(rule.get('dst_networkconf_id') or 'any')
    source_matches = source_id in ('any', '', str(source.network_id))
    destination_matches = destination_id in ('any', '', str(destination.network_id))
    return source_matches and destination_matches


def _action_to_verdict(action: str) -> Verdict:
    return 'deny' if action.lower() in ('drop', 'reject', 'deny') else 'allow'


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ('', '0', 'false', 'no', 'off')
    return bool(value)


def _data_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = cast(dict[str, object], value).get('data', [])
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]
