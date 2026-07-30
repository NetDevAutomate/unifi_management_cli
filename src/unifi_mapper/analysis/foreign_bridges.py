"""Detect wired third-party (foreign) bridges inside the UniFi L2 domain.

A "foreign bridge" is any device that the controller is attributing clients to, but which
is **not an adopted UniFi device**. Consumer mesh systems (eero, Deco, Orbi and similar)
behave exactly this way when wired in: they forward frames like a switch, so clients appear
behind them, yet they do not participate in RSTP and relay no BPDUs.

That combination is dangerous. If such a bridge touches two UniFi switches, it closes an L2
loop that spanning tree **cannot** break, because the BPDUs that would reveal the loop never
traverse it. UniFi then falls back to error-disabling ports, or the segment simply storms.

Motivating incident (2026-07-29): an eero mesh was wired in at six points. One eero bridged
`Flex8 p8` to `Flex 2.5G 5 p3` while a direct link also existed. Four eero-facing ports
carried **trunk** profiles, exporting every VLAN across the mesh fabric. Diagnosis took most
of a day; this check reduces it to one call.

Signals, in descending severity:

1. **Loop risk** -- one foreign bridge attached to two or more switch ports. This is a
   second path between L2 domains that RSTP is blind to.
2. **Trunk exposure** -- a foreign bridge on a trunk profile, so it receives every VLAN.
3. **Presence** -- a foreign bridge exists at all, with a count of clients behind it.
4. **Nesting** -- a foreign bridge learned behind another foreign bridge, which proves the
   fabric is performing transit bridging rather than acting as leaf APs.
"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, cast
from unifi_mapper.core.utils.client import UniFiClient


class ForeignBridge(BaseModel):
    """A non-adopted device that clients are appearing behind."""

    mac: str
    oui: str = ''
    ip: str = ''
    hostname: str = ''
    downstream_clients: int = 0
    attached_to: list[tuple[str, int]] = Field(
        default_factory=lambda: [],
        description='(switch name, port index) pairs where this bridge was located',
    )
    trunk_ports: list[str] = Field(
        default_factory=lambda: [],
        description='Port profile names granting this bridge a full trunk',
    )
    behind_another_bridge: bool = False


class ForeignBridgeFinding(BaseModel):
    """A finding about one foreign bridge."""

    severity: str = Field(description='WARNING or CRITICAL')
    bridge_mac: str
    loop_risk: bool = False
    message: str
    recommendation: str


class ForeignBridgeReport(BaseModel):
    """Foreign bridge detection report."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    clients_analyzed: int = 0
    adopted_devices: int = 0
    bridges_found: int = 0
    bridges: list[ForeignBridge] = Field(default_factory=lambda: [])
    findings_count: int = 0
    validation_passed: bool = True
    findings: list[ForeignBridgeFinding] = Field(default_factory=lambda: [])


async def detect_foreign_bridges() -> ForeignBridgeReport:
    """Fetch devices/clients/profiles and detect wired third-party bridges."""
    async with UniFiClient() as client:
        devices = await client.get_devices()
        clients = await client.get_clients()
        profiles = cast(list[dict[str, Any]], await client.get(client.build_path('rest/portconf')))
    return detect_foreign_bridges_from_data(devices, clients, profiles)


def detect_foreign_bridges_from_data(
    devices: list[dict[str, Any]],
    clients: list[dict[str, Any]],
    port_profiles: list[dict[str, Any]] | None = None,
) -> ForeignBridgeReport:
    """Detect foreign bridges from already-fetched UniFi data."""
    adopted = {
        str(d.get('mac') or '').lower()
        for d in devices
        if d.get('mac')
    }
    profiles_by_id = {
        str(p.get('_id')): p for p in port_profiles or [] if p.get('_id') is not None
    }

    # Any sw_mac that is not an adopted device is a bridge the controller sees as a switch.
    bridge_macs: dict[str, int] = {}
    for cl in clients:
        sw = str(cl.get('sw_mac') or '').lower()
        if sw and sw not in adopted:
            bridge_macs[sw] = bridge_macs.get(sw, 0) + 1

    client_by_mac = {str(c.get('mac') or '').lower(): c for c in clients}
    bridges: list[ForeignBridge] = []

    for mac, downstream in sorted(bridge_macs.items()):
        record = client_by_mac.get(mac, {})
        attached, trunks = _locate_bridge(mac, devices, profiles_by_id)
        parent = str(record.get('sw_mac') or '').lower()
        bridges.append(
            ForeignBridge(
                mac=mac,
                oui=str(record.get('oui') or ''),
                ip=str(record.get('ip') or ''),
                hostname=str(record.get('hostname') or record.get('name') or ''),
                downstream_clients=downstream,
                attached_to=attached,
                trunk_ports=trunks,
                behind_another_bridge=bool(parent) and parent in bridge_macs,
            )
        )

    findings = [f for b in bridges for f in _findings_for(b)]

    return ForeignBridgeReport(
        clients_analyzed=len(clients),
        adopted_devices=len(adopted),
        bridges_found=len(bridges),
        bridges=bridges,
        findings_count=len(findings),
        validation_passed=not any(f.severity == 'CRITICAL' for f in findings),
        findings=findings,
    )


def _locate_bridge(
    mac: str,
    devices: list[dict[str, Any]],
    profiles_by_id: dict[str, dict[str, Any]],
) -> tuple[list[tuple[str, int]], list[str]]:
    """Find which adopted switch ports this bridge MAC is physically attached to."""
    attached: list[tuple[str, int]] = []
    trunks: list[str] = []
    for device in devices:
        name = str(device.get('name') or device.get('mac') or 'Unknown')
        for port in _port_table(device):
            last = str((port.get('last_connection') or {}).get('mac') or '').lower()
            if last != mac:
                continue
            idx = _as_int(port.get('port_idx'))
            attached.append((name, idx))
            profile = profiles_by_id.get(str(port.get('portconf_id') or ''))
            if profile and _is_trunk(profile):
                trunks.append(str(profile.get('name') or ''))
    return attached, trunks


def _is_trunk(profile: dict[str, Any]) -> bool:
    return (
        str(profile.get('forward') or '').lower() == 'all'
        and str(profile.get('tagged_vlan_mgmt') or '').lower() != 'block_all'
    )


def _findings_for(bridge: ForeignBridge) -> list[ForeignBridgeFinding]:
    label = f'{bridge.mac}' + (f' ({bridge.oui})' if bridge.oui else '')
    where = ', '.join(f'{n} p{p}' for n, p in bridge.attached_to) or 'location unknown'
    out: list[ForeignBridgeFinding] = []

    if len(bridge.attached_to) >= 2:
        out.append(ForeignBridgeFinding(
            severity='CRITICAL',
            bridge_mac=bridge.mac,
            loop_risk=True,
            message=(
                f'Foreign bridge {label} is attached to {len(bridge.attached_to)} switch ports '
                f'({where}). That is a second L2 path between those switches which RSTP cannot '
                f'break, because a third-party bridge does not relay BPDUs. Expect broadcast '
                f'storms or ports being error-disabled by loop protection.'
            ),
            recommendation=(
                'Remove all but one wired connection to this bridge immediately. A device like '
                'this must be a leaf with a single uplink, never a transit path between '
                'switches.'
            ),
        ))

    if bridge.trunk_ports:
        out.append(ForeignBridgeFinding(
            severity='CRITICAL',
            bridge_mac=bridge.mac,
            message=(
                f'Foreign bridge {label} at {where} is on a trunk profile '
                f'({", ".join(sorted(set(bridge.trunk_ports)))}). It therefore receives every '
                f'tagged VLAN and can bridge them across its own fabric, including the '
                f'management VLAN.'
            ),
            recommendation=(
                'Move this port to an access profile (forward=native, tagged_vlan_mgmt=block_all). '
                'Reserve trunk profiles for switch-to-switch and UniFi AP links only.'
            ),
        ))

    if not out:
        out.append(ForeignBridgeFinding(
            severity='WARNING',
            bridge_mac=bridge.mac,
            message=(
                f'Foreign bridge {label} at {where} has {bridge.downstream_clients} client(s) '
                f'behind it. It is not an adopted UniFi device, so it is invisible to RSTP and '
                f'to UniFi client tracking.'
                + (' It is itself learned behind another foreign bridge, which means the fabric '
                   'is performing transit bridging.' if bridge.behind_another_bridge else '')
            ),
            recommendation=(
                'Confirm this device is intended, that it has exactly one wired uplink, and that '
                'its port uses an access profile with BPDU Guard enabled.'
            ),
        ))

    return out


def _port_table(device: dict[str, Any]) -> list[dict[str, Any]]:
    value = device.get('port_table')
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
