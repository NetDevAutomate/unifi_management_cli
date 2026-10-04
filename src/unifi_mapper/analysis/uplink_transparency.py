"""Uplink VLAN-transparency audit for UniFi switches.

Catches a failure mode no other check covers: a switch whose *elected* uplink port
cannot carry tagged VLANs. UniFi elects an uplink from whatever port has a path
upstream — including an access port. When the real trunk drops, a switch can
silently re-home onto an access port with ``tagged_vlan_mgmt='block_all'``. The
untagged network keeps working, so clients look fine, while every tagged VLAN
behind that switch is severed. If the management VLAN is one of them the switch
becomes unreachable and cannot be reconfigured over the API at all.

Observed on 2026-07-29: ``Switch F USW Lite 16 PoE`` lost its trunk to
``Switch B USW Flex 2.5G 8 PoE`` and re-homed onto an eero-facing access port.
VLAN 125 (untagged) stayed up; VLAN 255 (management) and VLAN 10 (CCTV) went dark.
"""

from __future__ import annotations

import time
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, cast
from unifi_mapper.analysis.link_settings import effective_profile_id
from unifi_mapper.analysis.vlan_coverage import (
    _as_int,
    _carried_vlans,
    _dict_list,
    _merge_profile_port,
    _network_vlan_by_id,
    _port_table,
)
from unifi_mapper.core.utils.client import UniFiClient


# Forwarding modes that cannot carry tagged VLANs at all.
_UNTAGGED_ONLY_FORWARD = ('native', 'disabled')

# Beyond this age, a non-informing device's port snapshot is not treated as evidence of
# current topology. 30 minutes is many multiples of the ~90s inform interval, so a device
# quiet for longer than this has genuinely stopped reporting rather than merely skipped one.
_DEFAULT_STALE_AFTER_SECONDS = 1800

# Profile keys that enumerate tagged VLANs explicitly as numbers.
_EXPLICIT_VLAN_KEYS = (
    'allowed_vlans',
    'allowed_vlan_ids',
    'tagged_vlans',
    'tagged_vlan_ids',
    'trunk_vlans',
    'vlan_ids',
)


class UplinkTransparencyFinding(BaseModel):
    """A switch whose elected uplink cannot carry the site's tagged VLANs."""

    severity: str = Field(description='WARNING or CRITICAL')
    device: str = Field(description='Device name')
    device_mac: str = Field(default='', description='Device MAC')
    uplink_port: int = Field(description='Local port index elected as the uplink')
    uplink_port_name: str = Field(default='', description='Local uplink port name')
    profile_name: str = Field(default='', description='Port profile applied to the uplink port')
    forward_mode: str = Field(
        default='', description="Profile 'forward' mode (all/native/customize)"
    )
    tagged_vlan_mgmt: str = Field(
        default='', description="Profile 'tagged_vlan_mgmt' (auto/block_all/custom)"
    )
    severed_vlans: list[int] = Field(
        default_factory=lambda: [],
        description='Tagged VLANs that cannot reach anything behind this switch',
    )
    management_vlan_severed: bool = Field(
        default=False,
        description='True when the management VLAN is severed, making the switch unreachable',
    )
    remote_uplink_mac: str = Field(default='', description='MAC at the far end of the uplink')
    remote_is_unifi: bool | None = Field(
        default=None,
        description='False when the uplink terminates on a non-adopted (third-party) bridge',
    )
    device_informing: bool = Field(
        default=True,
        description='False when the device is not reporting to the controller, so data is stale',
    )
    topology_verifiable: bool = Field(
        default=True,
        description=(
            'False when the snapshot is too old to assert current topology from. When False, '
            'severed_vlans and remote_is_unifi are deliberately not asserted.'
        ),
    )
    data_age_seconds: float | None = Field(
        default=None,
        description="Age of the device's last_seen at audit time, when known",
    )
    message: str = Field(description='Human-readable finding')
    recommendation: str = Field(description='Recommended action')


class UplinkTransparencyReport(BaseModel):
    """Uplink VLAN-transparency audit report."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    devices_analyzed: int = 0
    uplinks_analyzed: int = 0
    tagged_vlans: list[int] = Field(default_factory=lambda: [])
    management_vlan: int | None = None
    findings_count: int = 0
    validation_passed: bool = True
    findings: list[UplinkTransparencyFinding] = Field(default_factory=lambda: [])


async def audit_uplink_transparency(
    mgmt_vlan: int | None = None,
    stale_after_seconds: int = _DEFAULT_STALE_AFTER_SECONDS,
) -> UplinkTransparencyReport:
    """Fetch UniFi devices and audit whether each switch's uplink carries tagged VLANs."""
    async with UniFiClient() as client:
        devices = await client.get_devices()
        port_profiles = cast(
            list[dict[str, Any]], await client.get(client.build_path('rest/portconf'))
        )
        networks = await client.get_networks()
    return audit_uplink_transparency_from_data(
        devices,
        port_profiles=port_profiles,
        networks=networks,
        mgmt_vlan=mgmt_vlan,
        stale_after_seconds=stale_after_seconds,
    )


def audit_uplink_transparency_from_data(
    devices: list[dict[str, Any]],
    port_profiles: list[dict[str, Any]] | None = None,
    networks: list[dict[str, Any]] | None = None,
    mgmt_vlan: int | None = None,
    stale_after_seconds: int = _DEFAULT_STALE_AFTER_SECONDS,
    now: float | None = None,
) -> UplinkTransparencyReport:
    """Audit uplink VLAN transparency from already-fetched UniFi data.

    ``now`` is injectable so staleness behaviour is deterministically testable.
    """
    current_time = time.time() if now is None else now
    profiles_by_id = {
        str(profile.get('_id')): profile
        for profile in port_profiles or []
        if profile.get('_id') is not None
    }
    network_vlan_by_id = _network_vlan_by_id(networks or [])
    tagged_vlans = sorted({vlan for vlan in network_vlan_by_id.values() if vlan > 0})
    resolved_mgmt_vlan = (
        mgmt_vlan if mgmt_vlan is not None else _infer_mgmt_vlan(devices, networks or [])
    )
    unifi_macs = {str(device.get('mac') or '').lower() for device in devices if device.get('mac')}

    findings: list[UplinkTransparencyFinding] = []
    devices_analyzed = 0
    uplinks_analyzed = 0

    for device in devices:
        if not _is_switch(device):
            continue
        devices_analyzed += 1

        uplink_port = _elected_uplink_port(device)
        if uplink_port is None:
            continue
        uplinks_analyzed += 1

        profile_id, _source = effective_profile_id(
            device, uplink_port, _as_int(uplink_port.get('port_idx'))
        )
        profile = profiles_by_id.get(profile_id or '')
        effective = _merge_profile_port(uplink_port, profile)
        forward_mode = str(effective.get('forward') or '').lower()
        tagged_mgmt = str(effective.get('tagged_vlan_mgmt') or '').lower()

        carried = _uplink_carried_vlans(effective, network_vlan_by_id, tagged_vlans)
        severed = [vlan for vlan in tagged_vlans if vlan not in carried]

        remote_mac = _remote_uplink_mac(device, uplink_port)
        remote_is_unifi = (remote_mac in unifi_macs) if remote_mac else None
        informing = _is_informing(device)
        age = _data_age_seconds(device, current_time)
        verifiable = informing or age is None or age <= stale_after_seconds

        if not verifiable:
            findings.append(
                _unverifiable_finding(
                    device=device,
                    uplink_port=uplink_port,
                    profile=profile,
                    forward_mode=forward_mode,
                    tagged_mgmt=tagged_mgmt,
                    age=age,
                )
            )
            continue

        finding = _build_finding(
            device=device,
            uplink_port=uplink_port,
            profile=profile,
            forward_mode=forward_mode,
            tagged_mgmt=tagged_mgmt,
            severed=severed,
            tagged_vlans=tagged_vlans,
            mgmt_vlan=resolved_mgmt_vlan,
            remote_mac=remote_mac,
            remote_is_unifi=remote_is_unifi,
            informing=informing,
            age=age,
        )
        if finding is not None:
            findings.append(finding)

    return UplinkTransparencyReport(
        devices_analyzed=devices_analyzed,
        uplinks_analyzed=uplinks_analyzed,
        tagged_vlans=tagged_vlans,
        management_vlan=resolved_mgmt_vlan,
        findings_count=len(findings),
        validation_passed=not any(finding.severity == 'CRITICAL' for finding in findings),
        findings=findings,
    )


def _build_finding(
    *,
    device: dict[str, Any],
    uplink_port: dict[str, Any],
    profile: dict[str, Any] | None,
    forward_mode: str,
    tagged_mgmt: str,
    severed: list[int],
    tagged_vlans: list[int],
    mgmt_vlan: int | None,
    remote_mac: str,
    remote_is_unifi: bool | None,
    informing: bool,
    age: float | None = None,
) -> UplinkTransparencyFinding | None:
    """Produce a finding for one elected uplink, or None when the uplink is healthy."""
    blocks_tagged = bool(severed) and bool(tagged_vlans)
    foreign_bridge = remote_is_unifi is False
    if not blocks_tagged and not foreign_bridge:
        return None

    device_name = str(device.get('name') or device.get('mac') or 'Unknown')
    port_idx = _as_int(uplink_port.get('port_idx'))
    port_name = str(uplink_port.get('name') or f'Port {port_idx}')
    profile_name = str((profile or {}).get('name') or uplink_port.get('portconf_name') or '')
    mgmt_severed = mgmt_vlan is not None and mgmt_vlan in severed

    stale_note = (
        ''
        if informing
        else ' Device is not reporting to the controller, so this port data is stale '
        'and reflects its last known state.'
    )

    # A 'custom' tagged profile whose VLAN set is not enumerable in the payload cannot be
    # judged. Reporting CRITICAL here would raise a false alarm on a healthy trunk, so the
    # uncertainty is surfaced as a WARNING instead.
    if blocks_tagged and _is_unresolvable_custom(forward_mode, tagged_mgmt, uplink_port, profile):
        return UplinkTransparencyFinding(
            severity='WARNING',
            device=device_name,
            device_mac=str(device.get('mac') or ''),
            uplink_port=port_idx,
            uplink_port_name=port_name,
            profile_name=profile_name,
            forward_mode=forward_mode,
            tagged_vlan_mgmt=tagged_mgmt,
            severed_vlans=[],
            remote_uplink_mac=remote_mac,
            remote_is_unifi=remote_is_unifi,
            device_informing=informing,
            topology_verifiable=True,
            data_age_seconds=age,
            message=(
                f'{device_name} is uplinked through {port_name} using profile '
                f"'{profile_name}' (forward={forward_mode or 'unknown'}, "
                f'tagged_vlan_mgmt={tagged_mgmt}), whose tagged VLAN set could not be resolved '
                f'from the controller payload. VLAN transparency was not verified.' + stale_note
            ),
            recommendation=(
                'Confirm manually in the UniFi UI that this uplink profile carries every '
                f'tagged VLAN ({_format_vlans(tagged_vlans)}).'
            ),
        )

    if blocks_tagged:
        severity = 'CRITICAL'
        reason = _blocking_reason(forward_mode, tagged_mgmt)
        message = (
            f'{device_name} is uplinked through {port_name} '
            f"(profile '{profile_name}', forward={forward_mode or 'unknown'}, "
            f'tagged_vlan_mgmt={tagged_mgmt or "unknown"}) which {reason}. '
            f'Tagged VLAN(s) {_format_vlans(severed)} cannot reach anything behind this switch, '
            f'while untagged traffic continues to work.'
        )
        if mgmt_severed:
            message += (
                f' The management VLAN ({mgmt_vlan}) is among them, so this switch is '
                f'unreachable and cannot be reconfigured over the API.'
            )
        if foreign_bridge:
            message += (
                f' The uplink terminates on {remote_mac}, which is not an adopted UniFi device '
                f'(third-party bridge).'
            )
        recommendation = (
            f'Restore the switch trunk uplink. Physically verify the intended trunk link, then '
            f'confirm the elected uplink port uses a profile with forward=all and '
            f'tagged_vlan_mgmt=auto so VLAN(s) {_format_vlans(severed)} are carried.'
        )
        if mgmt_severed:
            recommendation += (
                ' This requires physical intervention: the management path is down, so no API '
                'change can reach the device.'
            )
    else:
        severity = 'WARNING'
        message = (
            f'{device_name} is uplinked through {port_name} to {remote_mac}, which is '
            f'not an adopted UniFi device (third-party bridge). Such a bridge does not '
            f'participate in RSTP, so it can close L2 loops the controller cannot break.'
        )
        recommendation = (
            'Uplink this switch directly to a UniFi switch instead of through a third-party '
            'bridge, and enable BPDU Guard on the bridge-facing access port.'
        )

    return UplinkTransparencyFinding(
        severity=severity,
        device=device_name,
        device_mac=str(device.get('mac') or ''),
        uplink_port=port_idx,
        uplink_port_name=port_name,
        profile_name=profile_name,
        forward_mode=forward_mode,
        tagged_vlan_mgmt=tagged_mgmt,
        severed_vlans=severed,
        management_vlan_severed=mgmt_severed,
        remote_uplink_mac=remote_mac,
        remote_is_unifi=remote_is_unifi,
        device_informing=informing,
        topology_verifiable=True,
        data_age_seconds=age,
        message=message + stale_note,
        recommendation=recommendation,
    )


def _remote_uplink_mac(device: dict[str, Any], uplink_port: dict[str, Any]) -> str:
    """MAC at the far end of the elected uplink port.

    LLDP for that specific port index is preferred: it reflects what is physically on the
    port right now. ``device['uplink']['uplink_mac']`` is a device-level summary that can
    lag behind a re-homing event, which would otherwise produce a false third-party-bridge
    finding while a switch recovers onto its real trunk.
    """
    port_idx = _as_int(uplink_port.get('port_idx'), default=-1)
    for entry in _dict_list(device.get('lldp_table')):
        if _as_int(entry.get('local_port_idx'), default=-2) == port_idx:
            chassis_id = str(entry.get('chassis_id') or '').lower()
            if chassis_id:
                return chassis_id
    uplink = device.get('uplink')
    if isinstance(uplink, dict):
        return str(cast(dict[str, Any], uplink).get('uplink_mac') or '').lower()
    return ''


def _uplink_carried_vlans(
    port: dict[str, Any],
    network_vlan_by_id: dict[str, int],
    tagged_vlans: list[int],
) -> set[int]:
    """VLANs this uplink port carries.

    ``forward='all'`` is a full trunk and carries every VLAN on its own, whether or not
    ``tagged_vlan_mgmt`` is present in the payload — real uplink ports frequently omit it.
    Only an explicit ``block_all`` overrides that. Everything else defers to the shared
    resolution used by the VLAN coverage audit.
    """
    forward_mode = str(port.get('forward') or '').lower()
    tagged_mgmt = str(port.get('tagged_vlan_mgmt') or '').lower()
    if forward_mode == 'all' and tagged_mgmt != 'block_all':
        carried = set(tagged_vlans)
        for network_id in _excluded_network_ids(port):
            if network_id in network_vlan_by_id:
                carried.discard(network_vlan_by_id[network_id])
        return carried
    return _carried_vlans(port, network_vlan_by_id, set(tagged_vlans))


def _excluded_network_ids(port: dict[str, Any]) -> list[str]:
    value = port.get('excluded_networkconf_ids')
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [str(item) for item in items if item]


def _data_age_seconds(device: dict[str, Any], current_time: float) -> float | None:
    """Age of the device's last_seen, or None when the controller reports no timestamp."""
    raw = device.get('last_seen')
    if raw is None:
        return None
    try:
        seen = float(raw)
    except (TypeError, ValueError):
        return None
    if seen > 10_000_000_000:  # milliseconds
        seen /= 1000.0
    age = current_time - seen
    return age if age >= 0 else 0.0


def _format_age(age: float | None) -> str:
    if age is None:
        return 'an unknown time'
    if age < 3600:
        return f'{int(age // 60)} minutes'
    if age < 86400:
        return f'{age / 3600:.1f} hours'
    return f'{age / 86400:.1f} days'


def _unverifiable_finding(
    *,
    device: dict[str, Any],
    uplink_port: dict[str, Any],
    profile: dict[str, Any] | None,
    forward_mode: str,
    tagged_mgmt: str,
    age: float | None,
) -> UplinkTransparencyFinding:
    """Report a device that stopped informing too long ago to judge its topology.

    Deliberately asserts nothing about severed VLANs or the far end of the uplink: the
    snapshot describes whatever was true when the device last reported, and cabling may
    have changed since. Claiming otherwise is the exact stale-data trap this audit exists
    to catch.
    """
    device_name = str(device.get('name') or device.get('mac') or 'Unknown')
    port_idx = _as_int(uplink_port.get('port_idx'))
    port_name = str(uplink_port.get('name') or f'Port {port_idx}')
    return UplinkTransparencyFinding(
        severity='WARNING',
        device=device_name,
        device_mac=str(device.get('mac') or ''),
        uplink_port=port_idx,
        uplink_port_name=port_name,
        profile_name=str((profile or {}).get('name') or ''),
        forward_mode=forward_mode,
        tagged_vlan_mgmt=tagged_mgmt,
        severed_vlans=[],
        remote_uplink_mac='',
        remote_is_unifi=None,
        device_informing=False,
        topology_verifiable=False,
        data_age_seconds=age,
        message=(
            f'{device_name} has not been informing the controller for {_format_age(age)}, so its '
            f'port data is too old to verify topology from. VLAN transparency was NOT assessed; '
            f'the last known uplink was {port_name}, but cabling may have changed since.'
        ),
        recommendation=(
            'Bring the device back online, or remove it from the controller if it has been '
            'decommissioned, so diagnostics reflect the real network.'
        ),
    )


def _is_unresolvable_custom(
    forward_mode: str,
    tagged_mgmt: str,
    uplink_port: dict[str, Any],
    profile: dict[str, Any] | None,
) -> bool:
    """True when a non-auto/non-block_all profile exposes no enumerable tagged VLAN set.

    Verified against this controller, ``forward`` is only ever 'native' or 'all' and
    ``tagged_vlan_mgmt`` only 'native' or 'block_all'. Anything else is a newer or
    unmodelled shape, so it is only trusted when it also carries explicit VLAN numbers.
    """
    if tagged_mgmt in ('auto', 'block_all') or forward_mode in _UNTAGGED_ONLY_FORWARD:
        return False
    if forward_mode == 'all':
        return False
    merged = _merge_profile_port(uplink_port, profile)
    return not any(merged.get(key) is not None for key in _EXPLICIT_VLAN_KEYS)


def _blocking_reason(forward_mode: str, tagged_mgmt: str) -> str:
    """Explain, in words, why this uplink cannot carry tagged VLANs."""
    if tagged_mgmt == 'block_all':
        return 'blocks all tagged VLANs'
    if forward_mode in _UNTAGGED_ONLY_FORWARD:
        return 'forwards only its native (untagged) network'
    return 'does not carry every tagged VLAN'


def _is_switch(device: dict[str, Any]) -> bool:
    """True only for switches.

    Excluded: the gateway (no upstream uplink) and access points. APs also expose a
    ``port_table`` with a native-only 'Data' port, so a port_table alone is not enough
    to identify a switch.
    """
    device_type = str(device.get('type') or '').lower()
    if device_type in ('udm', 'udmpro', 'ugw', 'uxg', 'uap', 'ubb', 'uph', 'uck'):
        return False
    return device_type in ('usw', 'switch') or bool(_port_table(device))


def _elected_uplink_port(device: dict[str, Any]) -> dict[str, Any] | None:
    """Return the local port UniFi has elected as this device's uplink."""
    for port in _port_table(device):
        if port.get('is_uplink') is True:
            return port
    uplink = device.get('uplink')
    if isinstance(uplink, dict):
        port_idx = _as_int(cast(dict[str, Any], uplink).get('port_idx'), default=-1)
        if port_idx >= 0:
            for port in _port_table(device):
                if _as_int(port.get('port_idx')) == port_idx:
                    return port
    return None


def _is_informing(device: dict[str, Any]) -> bool:
    """UniFi state 1 means connected/informing; anything else is stale data."""
    state = device.get('state')
    if state is None:
        return True
    return _as_int(state, default=1) == 1


def _infer_mgmt_vlan(devices: list[dict[str, Any]], networks: list[dict[str, Any]]) -> int | None:
    """Infer the management VLAN from the subnet holding the devices' own IPs."""
    device_ips = [str(device.get('ip') or '') for device in devices if device.get('ip')]
    if not device_ips:
        return None
    best: tuple[int, int] | None = None
    for network in _dict_list(networks):
        vlan = _as_int(network.get('vlan'))
        subnet = str(network.get('ip_subnet') or '')
        if vlan <= 0 or not subnet:
            continue
        prefix = _subnet_prefix(subnet)
        if not prefix:
            continue
        matches = sum(1 for ip in device_ips if ip.startswith(prefix))
        if matches and (best is None or matches > best[1]):
            best = (vlan, matches)
    return None if best is None else best[0]


def _subnet_prefix(subnet: str) -> str:
    """Reduce '192.0.2.254/24' to the '192.0.2.' comparison prefix."""
    address = subnet.split('/', 1)[0]
    octets = address.split('.')
    if len(octets) != 4:
        return ''
    return '.'.join(octets[:3]) + '.'


def _format_vlans(vlans: list[int]) -> str:
    return ', '.join(str(vlan) for vlan in vlans)
