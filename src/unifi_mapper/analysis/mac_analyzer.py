"""MAC address table analysis tool for UniFi networks."""

from collections import defaultdict
from datetime import datetime
from typing import Any, cast
from unifi_mapper.analysis.link_settings import effective_profile_id, port_override
from unifi_mapper.analysis.vlan_diagnostics import is_trunk_profile
from unifi_mapper.core.models import (
    MACAlert,
    MACAlertSeverity,
    MACAlertType,
    MACAnalysisReport,
    MACFlappingEvent,
    MACTableEntry,
    PortMACCount,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


# Thresholds for MAC analysis
MAX_MACS_PER_ACCESS_PORT = 5  # Access ports shouldn't have many MACs
FLAP_WINDOW_SECONDS = 60  # Time window for flap detection
FLAP_THRESHOLD = 3  # Number of port changes to trigger flap alert


async def analyze_mac_table(
    device_id: str | None = None,
    max_macs_per_port: int = MAX_MACS_PER_ACCESS_PORT,
) -> MACAnalysisReport:
    """Analyze MAC address tables across the network.

    When to use this tool:
    - When troubleshooting connectivity issues on specific ports
    - When investigating potential unauthorized devices
    - When diagnosing MAC address flapping (loop detection)
    - During security audits to identify unknown devices
    - When planning port security configurations

    How MAC analysis works:
    - Collects MAC address tables from all switches: the device's ``mac_table`` where the
      controller sends one, otherwise the wired clients' ``sw_mac`` / ``sw_port`` from
      ``stat/sta`` (current controllers send no ``mac_table``; issue 088), and says so
    - Identifies ports with excessive MAC counts (potential hubs/rogue APs)
    - Detects MAC flapping (same MAC moving between ports)
    - Tracks static vs dynamic MAC entries
    - Validates MAC counts against port type (trunk vs access)

    Types of issues detected:
    - MAC address flapping indicating loops or misconfigurations
    - Access ports with too many MACs (unauthorized switches/hubs)
    - Potential rogue devices or unauthorized access points
    - Aging issues with stale MAC entries

    Common workflow:
    1. analyze_mac_table() - get MAC table overview
    2. Review alerts for flapping or excessive MACs
    3. Investigate flagged ports with get_port_details
    4. Check connected device with find_device
    5. Take action (port shutdown, 802.1X, etc.)

    What to do next:
    - If flapping detected: Check for loops, verify STP, trace cable
    - If excessive MACs on access port: Investigate for unauthorized hub/AP
    - If unknown MACs: Cross-reference with client list, consider 802.1X
    - If aging issues: Check MAC aging timers, verify connectivity

    Args:
        device_id: Optional device ID to check. If None, checks all switches.
        max_macs_per_port: Threshold for excessive MACs on access ports.

    Returns:
        MACAnalysisReport with MAC entries, alerts, and recommendations

    Raises:
        ToolError: DEVICE_NOT_FOUND if device_id specified but not found
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()
            clients = await client.get_clients()
            profiles = cast(
                list[dict[str, Any]], await client.get(client.build_path('rest/portconf'))
            )
            profiles_by_id = {
                str(profile.get('_id')): profile
                for profile in profiles
                if isinstance(profile, dict) and profile.get('_id') is not None
            }

            devices_analyzed = 0
            all_mac_entries: list[MACTableEntry] = []
            all_alerts: list[MACAlert] = []
            flapping_events: list[MACFlappingEvent] = []
            port_mac_counts: list[PortMACCount] = []
            recommendations: list[str] = []

            # Build client MAC lookup for reference (reserved for future use)
            _client_macs = {c.get('mac', '').lower() for c in clients if c.get('mac')}  # noqa: F841
            # Where each wired client is learned, for switches that send no mac_table
            client_rows = _client_mac_rows(clients)
            switches_from_clients = 0

            # Track MAC locations for flapping detection
            mac_locations: dict[str, list[tuple[str, str, int, str]]] = defaultdict(list)

            for device in devices:
                device_type = device.get('type', '')
                if device_type not in ('usw', 'switch', 'udm', 'udmpro'):
                    continue

                # Filter to specific device if requested
                if device_id:
                    if device.get('_id') != device_id and device.get('mac') != device_id:
                        continue

                devices_analyzed += 1
                dev_id = device.get('_id', '')
                dev_name = device.get('name', device.get('mac', 'Unknown'))

                # Get port information for context
                port_table = device.get('port_table', [])
                port_info = {p.get('port_idx'): p for p in port_table}

                # Process MAC table entries: the switch's own table where the controller
                # sends one, otherwise the wired clients learned on it (issue 088)
                if 'mac_table' in device:
                    mac_table = device.get('mac_table') or []
                else:
                    mac_table = client_rows.get(str(device.get('mac') or '').lower(), [])
                    switches_from_clients += 1
                port_macs: dict[int, list[str]] = defaultdict(list)

                for entry in mac_table:
                    mac = entry.get('mac', '').lower()
                    port_idx = entry.get('port_idx', 0)
                    vlan = entry.get('vlan', 1)
                    is_static = entry.get('static', False)
                    age = entry.get('age')

                    if not mac or port_idx == 0:
                        continue

                    port_data = port_info.get(port_idx, {})
                    port_name = port_data.get('name', '') or f'Port {port_idx}'

                    mac_entry = MACTableEntry(
                        mac_address=mac,
                        device_id=dev_id,
                        device_name=dev_name,
                        port_idx=port_idx,
                        port_name=port_name,
                        vlan_id=vlan,
                        is_static=is_static,
                        age_seconds=age,
                        last_seen=datetime.now().isoformat(),
                    )
                    all_mac_entries.append(mac_entry)

                    # Track for flapping detection
                    mac_locations[mac].append(
                        (
                            dev_id,
                            dev_name,
                            port_idx,
                            datetime.now().isoformat(),
                        )
                    )

                    # Track per-port MAC counts
                    port_macs[port_idx].append(mac)

                # Analyze port MAC counts
                for port_idx, macs in port_macs.items():
                    port_data = port_info.get(port_idx, {})
                    port_name = port_data.get('name', '') or f'Port {port_idx}'
                    is_trunk = _is_trunk_port(device, port_data, port_idx, profiles_by_id)
                    is_uplink = port_data.get('is_uplink', False)

                    # Only flag access ports with excessive MACs
                    exceeds = not is_trunk and not is_uplink and len(macs) > max_macs_per_port

                    port_count = PortMACCount(
                        device_id=dev_id,
                        device_name=dev_name,
                        port_idx=port_idx,
                        port_name=port_name,
                        mac_count=len(macs),
                        is_trunk=is_trunk,
                        is_uplink=is_uplink,
                        exceeds_threshold=exceeds,
                    )
                    port_mac_counts.append(port_count)

                    if exceeds:
                        all_alerts.append(
                            MACAlert(
                                alert_type=MACAlertType.EXCESSIVE_MACS,
                                severity=MACAlertSeverity.WARNING,
                                message=f'Access port {port_name} has {len(macs)} MACs (threshold: {max_macs_per_port})',
                                device_id=dev_id,
                                device_name=dev_name,
                                port_idx=port_idx,
                                details={'mac_count': len(macs), 'macs': macs[:10]},
                                recommendation='Investigate for unauthorized hub, switch, or access point',
                            )
                        )

                # Check if specific device was found
                if device_id and devices_analyzed > 0:
                    break

            # Handle device not found
            if device_id and devices_analyzed == 0:
                raise ToolError(
                    message=f'Device with ID {device_id} not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Use find_device to search for the correct device ID',
                    related_tools=['find_device', 'find_mac'],
                )

            # Detect MAC flapping
            flapping_events = _detect_flapping(mac_locations)
            for event in flapping_events:
                all_alerts.append(
                    MACAlert(
                        alert_type=MACAlertType.FLAPPING,
                        severity=event.severity,
                        message=f'MAC {event.mac_address} flapping between ports',
                        device_id=event.device_id,
                        device_name=event.device_name,
                        mac_address=event.mac_address,
                        details={
                            'ports_involved': event.ports_involved,
                            'flap_count': event.flap_count,
                        },
                        recommendation=event.recommendation,
                    )
                )

            # Count statistics
            unique_macs = len({e.mac_address for e in all_mac_entries})
            static_count = sum(1 for e in all_mac_entries if e.is_static)
            ports_exceeding = sum(1 for p in port_mac_counts if p.exceeds_threshold)

            critical_count = sum(1 for a in all_alerts if a.severity == MACAlertSeverity.CRITICAL)
            warning_count = sum(
                1
                for a in all_alerts
                if a.severity in (MACAlertSeverity.WARNING, MACAlertSeverity.HIGH)
            )

            # Generate recommendations
            recommendations = _generate_recommendations(
                all_alerts, flapping_events, ports_exceeding
            )
            if switches_from_clients:
                recommendations.insert(0, _client_source_note(switches_from_clients))

            return MACAnalysisReport(
                timestamp=datetime.now().isoformat(),
                devices_analyzed=devices_analyzed,
                total_mac_entries=len(all_mac_entries),
                unique_mac_addresses=unique_macs,
                static_mac_count=static_count,
                flapping_events=flapping_events,
                alerts=all_alerts,
                port_mac_counts=port_mac_counts,
                ports_exceeding_threshold=ports_exceeding,
                critical_alerts=critical_count,
                warning_alerts=warning_count,
                network_healthy=critical_count == 0 and len(flapping_events) == 0,
                recommendations=recommendations,
            )

        except ToolError:
            raise
        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
                )
            raise ToolError(
                message=f'Error analyzing MAC table: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _client_mac_rows(clients: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Wired clients as ``mac_table`` rows, keyed by the lower-case MAC of their switch.

    A current controller sends no ``mac_table`` on a switch's ``stat/device`` record (each
    port has only ``mac_table_count``), but each wired ``stat/sta`` client names the switch
    and port it is learned on in ``sw_mac`` and ``sw_port`` (issue 088). A wireless client,
    or one without both fields, is learned on no switch port here.
    """
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for client in clients:
        sw_mac = str(client.get('sw_mac') or '').lower()
        port = client.get('sw_port')
        if client.get('is_wired') is False or not sw_mac:
            continue
        if not isinstance(port, int) or isinstance(port, bool):
            continue
        vlan = client.get('vlan')
        rows[sw_mac].append(
            {
                'mac': str(client.get('mac') or ''),
                'port_idx': port,
                'vlan': vlan if isinstance(vlan, int) and not isinstance(vlan, bool) else 1,
            }
        )
    return rows


def _client_source_note(switches: int) -> str:
    """The report line that says the entries came from the client list (issue 088)."""
    return (
        f'MAC entries for {switches} switch(es) come from the client list (stat/sta sw_mac '
        'and sw_port): the controller sends no mac_table for them, so a MAC that is not a '
        'listed wired client is not counted, and a MAC moving between ports (flapping) '
        'cannot be seen'
    )


def _is_trunk_port(
    device: dict[str, Any],
    port_data: dict[str, Any],
    port_idx: int,
    profiles_by_id: dict[str, dict[str, Any]],
) -> bool:
    """Determine if a port is configured as a trunk.

    The port's profile is the one ``link_settings.effective_profile_id`` picks, looked up in
    ``rest/portconf``, with the override's own settings on top; trunk-ness is then
    ``vlan_diagnostics.is_trunk_profile`` (``forward``, ``tagged_vlan_mgmt``, name). A port
    table entry that lists ``tagged_vlans`` is a trunk as before (issue 030).
    """
    profile_id, _source = effective_profile_id(device, port_data, port_idx)
    settings = dict(profiles_by_id.get(profile_id or '') or {})
    settings.update(port_override(device, port_idx) or {})
    if is_trunk_profile(settings):
        return True

    # Check VLAN configuration
    tagged_vlans = port_data.get('tagged_vlans', [])
    if tagged_vlans:
        return True

    return False


def _detect_flapping(
    mac_locations: dict[str, list[tuple[str, str, int, str]]],
) -> list[MACFlappingEvent]:
    """Detect MAC addresses that are flapping between ports."""
    flapping_events: list[MACFlappingEvent] = []

    for mac, locations in mac_locations.items():
        if len(locations) < 2:
            continue

        # Get unique ports
        unique_ports = {loc[2] for loc in locations}
        if len(unique_ports) < 2:
            continue

        # If MAC seen on multiple ports, it's flapping
        device_id, device_name, _, first_seen = locations[0]
        _, _, _, last_seen = locations[-1]
        ports_list = list(unique_ports)

        severity = MACAlertSeverity.WARNING
        if len(unique_ports) >= FLAP_THRESHOLD:
            severity = MACAlertSeverity.CRITICAL

        flapping_events.append(
            MACFlappingEvent(
                mac_address=mac,
                device_id=device_id,
                device_name=device_name,
                ports_involved=ports_list,
                flap_count=len(locations),
                window_seconds=FLAP_WINDOW_SECONDS,
                first_seen=first_seen,
                last_seen=last_seen,
                severity=severity,
                recommendation='Check for network loops, verify STP configuration, inspect cabling',
            )
        )

    return flapping_events


def _generate_recommendations(
    alerts: list[MACAlert],
    flapping_events: list[MACFlappingEvent],
    ports_exceeding: int,
) -> list[str]:
    """Generate recommendations based on analysis."""
    recommendations: list[str] = []

    if flapping_events:
        critical_flaps = [f for f in flapping_events if f.severity == MACAlertSeverity.CRITICAL]
        if critical_flaps:
            recommendations.append(
                f'URGENT: {len(critical_flaps)} MAC address(es) showing severe flapping - '
                'likely network loop or STP issue'
            )
        else:
            recommendations.append(
                f'{len(flapping_events)} MAC address(es) flapping - check cable connections and STP'
            )

    if ports_exceeding > 0:
        recommendations.append(
            f'{ports_exceeding} access port(s) have excessive MACs - '
            'investigate for unauthorized hubs, switches, or APs'
        )

    excessive_alerts = [a for a in alerts if a.alert_type == MACAlertType.EXCESSIVE_MACS]
    if excessive_alerts:
        recommendations.append(
            'Consider enabling port security or 802.1X on affected access ports'
        )

    if not alerts and not flapping_events:
        recommendations.append('MAC table analysis shows no issues - network looks healthy')

    return recommendations
