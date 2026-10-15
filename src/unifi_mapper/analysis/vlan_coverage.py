"""VLAN coverage audit for UniFi trunk and planned uplink ports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, cast
from unifi_mapper.analysis.link_settings import effective_profile_id, port_override
from unifi_mapper.analysis.vlan_diagnostics import (
    PROFILE_VLAN_FIELDS,
    VLAN_LIST_KEYS,
    is_trunk_profile,
)
from unifi_mapper.core.utils.client import UniFiClient


class VLANCoverageFinding(BaseModel):
    """VLAN coverage audit finding."""

    severity: str = Field(description='WARNING or CRITICAL')
    device: str = Field(description='Device name')
    port: int = Field(description='Switch port index')
    missing_vlans: list[int] = Field(description='Required VLANs absent from the port')
    message: str = Field(description='Human-readable finding')
    recommendation: str = Field(description='Recommended action')


class VLANCoverageReport(BaseModel):
    """VLAN coverage audit report."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    devices_analyzed: int = 0
    ports_analyzed: int = 0
    required_vlans: list[int] = Field(default_factory=lambda: [])
    findings_count: int = 0
    validation_passed: bool = True
    findings: list[VLANCoverageFinding] = Field(default_factory=lambda: [])


async def audit_vlan_coverage(
    required_vlans: Iterable[int],
    planned_uplinks: Sequence[str | Mapping[str, Any]] | None = None,
) -> VLANCoverageReport:
    """Fetch UniFi devices and audit VLAN coverage on trunk/planned uplink ports."""
    async with UniFiClient() as client:
        devices = await client.get_devices()
        port_profiles = cast(
            list[dict[str, Any]], await client.get(client.build_path('rest/portconf'))
        )
        networks = await client.get_networks()
    return audit_vlan_coverage_from_data(
        devices, required_vlans, planned_uplinks, port_profiles, networks
    )


def audit_vlan_coverage_from_data(
    devices: list[dict[str, Any]],
    required_vlans: Iterable[int],
    planned_uplinks: Sequence[str | Mapping[str, Any]] | None = None,
    port_profiles: list[dict[str, Any]] | None = None,
    networks: list[dict[str, Any]] | None = None,
) -> VLANCoverageReport:
    """Audit VLAN coverage from already-fetched UniFi device dictionaries."""
    required = sorted({_as_int(vlan) for vlan in required_vlans if _as_int(vlan) > 0})
    planned_targets = [_planned_target(target) for target in planned_uplinks or []]
    profiles_by_id = {
        str(profile.get('_id')): profile
        for profile in port_profiles or []
        if profile.get('_id') is not None
    }
    network_vlan_by_id = _network_vlan_by_id(networks or [])
    all_network_vlans = set(network_vlan_by_id.values())
    findings: list[VLANCoverageFinding] = []
    devices_analyzed = 0
    ports_analyzed = 0

    for device in devices:
        if not _is_switch(device):
            continue

        devices_analyzed += 1
        device_name = str(device.get('name') or device.get('mac') or 'Unknown')
        lldp_by_port = _lldp_by_port(device)

        for port in _port_table(device):
            port_idx = _as_int(port.get('port_idx'))
            profile_id, _source = effective_profile_id(device, port, port_idx)
            profile = profiles_by_id.get(profile_id or '')
            override = port_override(device, port_idx)
            effective_port = _running_port(port, profile, override)
            lldp_entry = lldp_by_port.get(port_idx)
            matched_target = _matching_planned_target(effective_port, lldp_entry, planned_targets)
            trunk = _is_trunk(port, profile, override)

            if not _should_audit_port(effective_port, port_idx, lldp_entry, matched_target, trunk):
                continue

            ports_analyzed += 1
            carried_vlans = _carried_vlans(effective_port, network_vlan_by_id, all_network_vlans)
            missing = [vlan for vlan in required if vlan not in carried_vlans]
            if not missing:
                continue

            port_name = str(port.get('name') or f'Port {port_idx}')
            severity = (
                'CRITICAL'
                if _is_critical_target(matched_target, effective_port, lldp_entry)
                else 'WARNING'
            )
            findings.append(
                VLANCoverageFinding(
                    severity=severity,
                    device=device_name,
                    port=port_idx,
                    missing_vlans=missing,
                    message=(
                        f'{device_name} {port_name} is missing required VLANs '
                        f'{_format_vlans(missing)}.'
                    ),
                    recommendation=(
                        'Update the UniFi port profile/override so this trunk or planned '
                        f'uplink carries VLANs {_format_vlans(missing)}.'
                    ),
                )
            )

    return VLANCoverageReport(
        devices_analyzed=devices_analyzed,
        ports_analyzed=ports_analyzed,
        required_vlans=required,
        findings_count=len(findings),
        validation_passed=not any(finding.severity == 'CRITICAL' for finding in findings),
        findings=findings,
    )


def _is_switch(device: dict[str, Any]) -> bool:
    device_type = str(device.get('type') or '').lower()
    return device_type in ('usw', 'switch', 'udm', 'udmpro') or bool(_port_table(device))


def _port_table(device: dict[str, Any]) -> list[dict[str, Any]]:
    value = device.get('port_table')
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]


def _lldp_by_port(device: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        _as_int(entry.get('local_port_idx')): entry
        for entry in _dict_list(device.get('lldp_table'))
        if entry.get('local_port_idx') is not None
    }


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]


def _planned_target(target: str | Mapping[str, Any]) -> dict[str, str]:
    if isinstance(target, str):
        return {'name': target, 'model': ''}
    return {
        'name': str(target.get('name') or target.get('device_name') or ''),
        'model': str(target.get('model') or target.get('device_model') or ''),
    }


def _matching_planned_target(
    port: dict[str, Any],
    lldp_entry: dict[str, Any] | None,
    planned_targets: list[dict[str, str]],
) -> dict[str, str] | None:
    haystack = _search_text(
        (
            port.get('name'),
            port.get('uplink_name'),
            port.get('uplink_device_name'),
            port.get('uplink_model'),
            port.get('uplink_device_model'),
            lldp_entry.get('system_name') if lldp_entry else None,
            lldp_entry.get('device_name') if lldp_entry else None,
            lldp_entry.get('chassis_name') if lldp_entry else None,
            lldp_entry.get('model') if lldp_entry else None,
        )
    )
    for target in planned_targets:
        target_text = _search_text((target.get('name'), target.get('model')))
        if target_text and target_text in haystack:
            return target
        if target.get('name') and _normalize_text(target['name']) in haystack:
            return target
        if target.get('model') and _normalize_text(target['model']) in haystack:
            return target
    return None


def _should_audit_port(
    port: dict[str, Any],
    port_idx: int,
    lldp_entry: dict[str, Any] | None,
    matched_target: dict[str, str] | None,
    is_trunk: bool,
) -> bool:
    if _as_bool(port.get('up'), default=True) is False and matched_target is None:
        return False
    if matched_target is not None:
        return True
    return is_trunk or _is_inter_switch_port(port, port_idx, lldp_entry)


def _is_trunk(
    port: dict[str, Any],
    profile: dict[str, Any] | None,
    override: dict[str, Any] | None,
) -> bool:
    """``vlan_diagnostics.is_trunk_profile`` over the settings the port runs (issue 089).

    The profile with the override on top, as ``diagnose vlans`` reads them. The port table
    entry's own keys come first, so a hand-built record's ``is_trunk``, ``is_access`` or VLAN
    lists still count, but not its copies of the profile's VLAN fields: a live port table
    says ``forward: 'all'`` under an access profile.
    """
    settings = {key: value for key, value in port.items() if key not in PROFILE_VLAN_FIELDS}
    settings.update(profile or {})
    settings.update(override or {})
    return is_trunk_profile(settings)


def _is_inter_switch_port(
    port: dict[str, Any],
    port_idx: int,
    lldp_entry: dict[str, Any] | None,
) -> bool:
    if _profile_bool(port, ('is_uplink', 'uplink')) is True or bool(port.get('uplink_mac')):
        return True
    if lldp_entry is None:
        return False
    remote_text = _normalize_text(
        lldp_entry.get('system_name')
        or lldp_entry.get('device_name')
        or lldp_entry.get('chassis_name')
        or lldp_entry.get('model')
        or ''
    )
    return port_idx > 0 and any(token in remote_text for token in ('usw', 'switch', 'flex'))


_VLAN_KEYS = VLAN_LIST_KEYS


def _carried_vlans(
    port: dict[str, Any],
    network_vlan_by_id: dict[str, int] | None = None,
    all_network_vlans: set[int] | None = None,
) -> set[int]:
    vlans: set[int] = set()
    for key in _VLAN_KEYS:
        vlans.update(_parse_vlans(port.get(key)))
    for key in ('native_networkconf_id', 'networkconf_id'):
        network_id = port.get(key)
        if network_id and network_vlan_by_id and str(network_id) in network_vlan_by_id:
            vlans.add(network_vlan_by_id[str(network_id)])
    mgmt = str(port.get('tagged_vlan_mgmt') or '').lower()
    forward_all = str(port.get('forward') or '').lower() == 'all' and mgmt != 'block_all'
    if mgmt == 'auto' or forward_all:
        # Every VLAN, as diagnose vlans reads a forward 'all' trunk (issue 089)
        vlans.update(all_network_vlans or set())
        for network_id in _parse_string_list(port.get('excluded_networkconf_ids')):
            if network_vlan_by_id and network_id in network_vlan_by_id:
                vlans.discard(network_vlan_by_id[network_id])
    return vlans


def _parse_vlans(value: Any) -> set[int]:
    if value is None or value is False:
        return set()
    if isinstance(value, int):
        return {value} if value > 0 else set()
    if isinstance(value, str):
        vlans: set[int] = set()
        for item in value.replace(';', ',').split(','):
            item = item.strip()
            if not item:
                continue
            if '-' in item:
                start, _, end = item.partition('-')
                start_id = _as_int(start)
                end_id = _as_int(end)
                if start_id > 0 and end_id >= start_id:
                    vlans.update(range(start_id, end_id + 1))
                continue
            vlan_id = _as_int(item)
            if vlan_id > 0:
                vlans.add(vlan_id)
        return vlans
    if isinstance(value, (list, tuple, set)):
        vlans = set()
        for item in cast(Iterable[Any], value):
            vlans.update(_parse_vlans(item))
        return vlans
    return set()


def _is_critical_target(
    matched_target: dict[str, str] | None,
    port: dict[str, Any],
    lldp_entry: dict[str, Any] | None,
) -> bool:
    if matched_target is None:
        return False
    text = _search_text(
        (
            matched_target.get('name'),
            matched_target.get('model'),
            port.get('name'),
            lldp_entry.get('system_name') if lldp_entry else None,
            lldp_entry.get('model') if lldp_entry else None,
        )
    )
    return 'flexxg' in text or 'uswflexxg' in text


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


def _search_text(values: Iterable[Any]) -> str:
    return ''.join(_normalize_text(value) for value in values if value is not None)


def _normalize_text(value: Any) -> str:
    return ''.join(char for char in str(value).lower() if char.isalnum())


def _format_vlans(vlans: Sequence[int]) -> str:
    return ', '.join(str(vlan) for vlan in vlans)


def _network_vlan_by_id(networks: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for network in networks:
        network_id = network.get('_id')
        vlan = _as_int(network.get('vlan'))
        if network_id and vlan > 0:
            result[str(network_id)] = vlan
    return result


def _merge_profile_port(
    port: dict[str, Any],
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    if profile is None:
        return port
    merged = dict(profile)
    merged.update(port)
    if not merged.get('portconf_name'):
        merged['portconf_name'] = profile.get('name')
    return merged


def _running_port(
    port: dict[str, Any],
    profile: dict[str, Any] | None,
    override: dict[str, Any] | None,
) -> dict[str, Any]:
    """The port table entry with the VLAN settings the port runs (issue 089).

    :func:`_merge_profile_port`, then the profile's and the override's
    :data:`PROFILE_VLAN_FIELDS` over the port table's copies, as ``diagnose vlans`` reads
    them. The port table's own ``forward`` is dropped: a live controller reports
    ``forward: 'all'`` there under access profiles. (``uplink_transparency`` keeps
    :func:`_merge_profile_port` as it was.)
    """
    merged = dict(_merge_profile_port(port, profile))
    merged.pop('forward', None)
    for source in (profile or {}, override or {}):
        for key in PROFILE_VLAN_FIELDS:
            if key in source:
                merged[key] = source[key]
    return merged


def _parse_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [str(item) for item in items if item]
