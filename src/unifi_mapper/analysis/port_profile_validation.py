"""Port profile validation for UniFi switch ports."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, cast
from unifi_mapper.core.utils.client import UniFiClient


class PortProfileFinding(BaseModel):
    """A port profile validation finding."""

    severity: str = Field(description='INFO, WARNING, or CRITICAL')
    category: str = Field(description='Finding category')
    device_name: str = Field(description='Switch name')
    port_idx: int = Field(description='Switch port index')
    port_name: str = Field(default='', description='Port name')
    profile_name: str = Field(default='', description='Applied port profile name')
    message: str = Field(description='Human-readable finding')
    recommendation: str = Field(description='Recommended action')


class PortProfileValidationReport(BaseModel):
    """Report for port profile safety validation."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    devices_analyzed: int = 0
    ports_analyzed: int = 0
    findings_count: int = 0
    validation_passed: bool = True
    findings: list[PortProfileFinding] = Field(default_factory=lambda: [])


async def validate_port_profiles() -> PortProfileValidationReport:
    """Fetch UniFi switch data and validate applied port profiles."""
    async with UniFiClient() as client:
        devices = _data_list(await client.get(client.build_path('stat/device')))
        port_profiles = _data_list(await client.get(client.build_path('rest/portconf')))
    return validate_port_profiles_from_data(devices, port_profiles)


def validate_port_profiles_from_data(
    devices: list[dict[str, Any]],
    port_profiles: list[dict[str, Any]],
) -> PortProfileValidationReport:
    """Validate port profile safety from already-fetched UniFi API data."""
    profiles_by_id = {
        str(profile.get('_id')): profile
        for profile in port_profiles
        if profile.get('_id') is not None
    }
    findings: list[PortProfileFinding] = []
    devices_analyzed = 0
    ports_analyzed = 0

    for device in devices:
        if not _is_switch_like_device(device):
            continue

        devices_analyzed += 1
        device_name = str(device.get('name') or device.get('mac') or 'Unknown')
        lldp_ports = _lldp_ports(device)

        for port in _port_table(device):
            ports_analyzed += 1
            port_idx = _as_int(port.get('port_idx'))
            port_name = str(port.get('name') or f'Port {port_idx}')
            profile_id = _profile_id_for_port(port, device)
            if not profile_id:
                continue
            profile = profiles_by_id.get(profile_id)

            if profile is None:
                findings.append(
                    PortProfileFinding(
                        severity='INFO',
                        category='Port Profile',
                        device_name=device_name,
                        port_idx=port_idx,
                        port_name=port_name,
                        message=f'{device_name} port {port_idx} references an unknown port profile.',
                        recommendation='Fetch current port profiles or verify the port override manually.',
                    )
                )
                continue

            profile_name = str(profile.get('name') or profile_id)
            stp_edge = _profile_bool(profile, ('stp_edge', 'stp_portfast', 'edge'))
            bpdu_guard = _profile_bool(profile, ('bpdu_guard', 'stp_bpdu_guard'))
            bpdu_detected = _profile_bool(port, ('bpdu_detected', 'bpdu_rx', 'stp_bpdu_detected'))
            is_uplink = _is_uplink_port(port, port_idx, lldp_ports)
            is_client_only = _is_client_only_port(port, port_idx, lldp_ports)

            if is_client_only and stp_edge is False:
                findings.append(
                    PortProfileFinding(
                        severity='WARNING',
                        category='STP Edge',
                        device_name=device_name,
                        port_idx=port_idx,
                        port_name=port_name,
                        profile_name=profile_name,
                        message=f'{device_name} port {port_idx} appears client-only but STP edge is disabled.',
                        recommendation='Use a client/access profile with STP Edge enabled.',
                    )
                )

            if stp_edge is True and bpdu_guard is False:
                findings.append(
                    PortProfileFinding(
                        severity='WARNING',
                        category='BPDU Guard',
                        device_name=device_name,
                        port_idx=port_idx,
                        port_name=port_name,
                        profile_name=profile_name,
                        message=f'{device_name} port {port_idx} is edge but BPDU Guard is disabled.',
                        recommendation='Enable BPDU Guard on edge/client access profiles.',
                    )
                )

            if stp_edge is True and bpdu_detected:
                findings.append(
                    PortProfileFinding(
                        severity='CRITICAL',
                        category='BPDU Guard',
                        device_name=device_name,
                        port_idx=port_idx,
                        port_name=port_name,
                        profile_name=profile_name,
                        message=f'{device_name} port {port_idx} is an edge port receiving BPDUs.',
                        recommendation='Investigate for an unmanaged switch, loop, or wrong port profile.',
                    )
                )

            if is_uplink and stp_edge is True:
                findings.append(
                    PortProfileFinding(
                        severity='WARNING',
                        category='Uplink Edge',
                        device_name=device_name,
                        port_idx=port_idx,
                        port_name=port_name,
                        profile_name=profile_name,
                        message=f'{device_name} port {port_idx} appears to be an uplink but uses STP edge.',
                        recommendation='Use an infrastructure/trunk profile without STP Edge on uplinks.',
                    )
                )

    critical_count = sum(1 for finding in findings if finding.severity == 'CRITICAL')
    return PortProfileValidationReport(
        devices_analyzed=devices_analyzed,
        ports_analyzed=ports_analyzed,
        findings_count=len(findings),
        validation_passed=critical_count == 0,
        findings=findings,
    )


def _port_table(device: dict[str, Any]) -> list[dict[str, Any]]:
    value = device.get('port_table')
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]


def _is_switch_like_device(device: dict[str, Any]) -> bool:
    device_type = str(device.get('type') or '').lower()
    return device_type in ('usw', 'switch', 'udm', 'udmpro') or bool(_port_table(device))


def _lldp_ports(device: dict[str, Any]) -> set[int]:
    table = device.get('lldp_table')
    if not isinstance(table, list):
        return set()
    items = cast(list[object], table)
    entries = [cast(dict[str, Any], entry) for entry in items if isinstance(entry, dict)]
    return {
        _as_int(entry.get('local_port_idx'))
        for entry in entries
        if entry.get('local_port_idx') is not None
    }


def _profile_id_for_port(port: dict[str, Any], device: dict[str, Any]) -> str:
    for key in ('portconf_id', 'port_conf_id', 'profile_id'):
        value = port.get(key)
        if value:
            return str(value)

    port_idx = _as_int(port.get('port_idx'))
    overrides = device.get('port_overrides')
    if isinstance(overrides, list):
        override_values = cast(list[object], overrides)
        override_items = [
            cast(dict[str, Any], override)
            for override in override_values
            if isinstance(override, dict)
        ]
        for override in override_items:
            if _as_int(override.get('port_idx')) == port_idx:
                override_value = override.get('portconf_id') or override.get('port_conf_id')
                if override_value:
                    return str(override_value)

    return ''


def _is_uplink_port(port: dict[str, Any], port_idx: int, lldp_ports: set[int]) -> bool:
    return (
        _profile_bool(port, ('is_uplink', 'uplink')) is True
        or bool(port.get('uplink_mac'))
        or port_idx in lldp_ports
    )


def _is_client_only_port(port: dict[str, Any], port_idx: int, lldp_ports: set[int]) -> bool:
    if not _as_bool(port.get('up'), default=True):
        return False
    if _is_uplink_port(port, port_idx, lldp_ports):
        return False
    if _profile_bool(port, ('is_trunk', 'trunk')) is True:
        return False
    return True


def _profile_bool(data: dict[str, Any], keys: tuple[str, ...]) -> bool | None:
    for key in keys:
        if key in data:
            return _as_bool(data.get(key))
    return None


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ('', '0', 'false', 'no', 'off')
    return bool(value)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _data_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = cast(dict[str, object], value).get('data', [])
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]
