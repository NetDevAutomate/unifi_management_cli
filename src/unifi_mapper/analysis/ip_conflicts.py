"""IP conflict detection tool for UniFi networks."""

from collections import defaultdict
from datetime import datetime
from typing import Any
from unifi_mcp.models import (
    ConflictingClient,
    IPConflict,
    IPConflictReport,
)
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


async def detect_ip_conflicts(
    include_offline: bool = False,
) -> IPConflictReport:
    """Detect IP address conflicts in the network.

    When to use this tool:
    - When clients report connectivity issues or intermittent network problems
    - During routine network health checks
    - After DHCP changes or IP address reassignments
    - When troubleshooting duplicate IP errors in logs
    - Before deploying new devices with static IPs

    How IP conflict detection works:
    - Scans all connected clients from the UniFi controller
    - Groups clients by IP address to identify duplicates
    - Analyzes VLAN assignments to detect cross-VLAN conflicts
    - Provides connection details to help locate conflicting devices

    Common workflow:
    1. detect_ip_conflicts() - identify all IP conflicts
    2. For each conflict, note the MAC addresses and connection points
    3. Physically locate or remotely access conflicting devices
    4. Resolve by changing IP or fixing DHCP configuration

    What to do next:
    - If conflicts found on same VLAN: Check for static IP misconfigurations
    - If conflicts across VLANs: May indicate routing/NAT issue
    - If offline devices conflict: May be stale DHCP leases
    - Review DHCP scope to prevent future conflicts

    Args:
        include_offline: Include clients that are currently offline (may show stale data)

    Returns:
        IPConflictReport with all detected conflicts and recommendations

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            # Get all clients from controller
            clients = await client.get_clients()
            devices = await client.get_devices()

            # Build device lookup for connection info
            device_lookup: dict[str, dict[str, Any]] = {}
            for device in devices:
                mac = device.get('mac', '').lower().replace(':', '')
                device_lookup[mac] = device

            # Group clients by IP address
            ip_to_clients: dict[str, list[dict[str, Any]]] = defaultdict(list)

            for client_data in clients:
                ip = client_data.get('ip')
                if not ip:
                    continue

                # Skip offline clients unless requested
                last_seen = client_data.get('last_seen', 0)
                if not include_offline and last_seen == 0:
                    continue

                ip_to_clients[ip].append(client_data)

            # Find conflicts (IPs with multiple clients)
            conflicts: list[IPConflict] = []
            recommendations: list[str] = []

            for ip, clients_list in ip_to_clients.items():
                if len(clients_list) < 2:
                    continue

                # Build conflict details
                conflicting_clients: list[ConflictingClient] = []
                vlans_seen: set[int] = set()

                for client_data in clients_list:
                    # Get connection info
                    connected_device = None
                    connected_port = None

                    sw_mac = client_data.get('sw_mac', '').lower().replace(':', '')
                    ap_mac = client_data.get('ap_mac', '').lower().replace(':', '')

                    if sw_mac and sw_mac in device_lookup:
                        device = device_lookup[sw_mac]
                        connected_device = device.get('name', device.get('mac', 'Unknown'))
                        connected_port = f'Port {client_data.get("sw_port", "?")}'
                    elif ap_mac and ap_mac in device_lookup:
                        device = device_lookup[ap_mac]
                        connected_device = device.get('name', device.get('mac', 'Unknown'))
                        connected_port = 'Wireless'

                    # Track VLAN
                    vlan = client_data.get('vlan', client_data.get('network_id'))
                    if vlan:
                        vlans_seen.add(int(vlan) if isinstance(vlan, (int, str)) else 0)

                    # Parse last_seen timestamp
                    last_seen_ts = client_data.get('last_seen')
                    last_seen_dt = None
                    if last_seen_ts:
                        try:
                            last_seen_dt = datetime.fromtimestamp(last_seen_ts)
                        except (ValueError, TypeError, OSError):
                            pass

                    conflicting_clients.append(
                        ConflictingClient(
                            mac_address=_format_mac(client_data.get('mac', '')),
                            hostname=client_data.get('hostname'),
                            name=client_data.get('name'),
                            is_wired=client_data.get('is_wired', False),
                            is_guest=client_data.get('is_guest', False),
                            connected_device=connected_device,
                            connected_port=connected_port,
                            last_seen=last_seen_dt,
                            vlan=vlan if isinstance(vlan, int) else None,
                        )
                    )

                # Determine severity
                severity = _determine_severity(conflicting_clients)

                # Check for VLAN mismatch
                vlan_mismatch = len(vlans_seen) > 1

                conflicts.append(
                    IPConflict(
                        ip_address=ip,
                        clients=conflicting_clients,
                        conflict_count=len(conflicting_clients),
                        severity=severity,
                        vlan_mismatch=vlan_mismatch,
                    )
                )

            # Generate recommendations
            if conflicts:
                recommendations.append('Review DHCP server configuration for overlapping scopes')
                recommendations.append(
                    'Check for devices with static IPs that conflict with DHCP range'
                )

                wired_conflicts = sum(1 for c in conflicts if any(cl.is_wired for cl in c.clients))
                if wired_conflicts > 0:
                    recommendations.append(
                        f'{wired_conflicts} conflicts involve wired devices - check switch port configurations'
                    )

                vlan_issues = sum(1 for c in conflicts if c.vlan_mismatch)
                if vlan_issues > 0:
                    recommendations.append(
                        f'{vlan_issues} conflicts span multiple VLANs - review inter-VLAN routing'
                    )

            return IPConflictReport(
                timestamp=datetime.now().isoformat(),
                total_clients_scanned=len(clients),
                conflicts_found=len(conflicts),
                conflicts=conflicts,
                healthy=len(conflicts) == 0,
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
                message=f'Error detecting IP conflicts: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _format_mac(mac: str) -> str:
    """Format MAC address with colons."""
    mac = mac.lower().replace(':', '').replace('-', '')
    if len(mac) == 12:
        return ':'.join(mac[i : i + 2] for i in range(0, 12, 2))
    return mac


def _determine_severity(clients: list[ConflictingClient]) -> str:
    """Determine conflict severity based on client characteristics."""
    # Critical: Multiple wired devices online
    wired_online = sum(1 for c in clients if c.is_wired and c.last_seen)
    if wired_online >= 2:
        return 'critical'

    # High: Mix of wired and wireless online
    wireless_online = sum(1 for c in clients if not c.is_wired and c.last_seen)
    if wired_online >= 1 and wireless_online >= 1:
        return 'high'

    # Medium: Multiple wireless devices
    if wireless_online >= 2:
        return 'medium'

    # Low: Involves offline devices (likely stale)
    return 'low'
