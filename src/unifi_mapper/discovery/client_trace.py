"""Client trace tool for following client connection paths."""

from pydantic import Field
from typing import Annotated, Any
from unifi_mcp.models import NetworkPath, PathHop
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


async def client_trace(
    client: Annotated[
        str, Field(description='Client identifier (MAC, IP, hostname, or device name)')
    ],
) -> NetworkPath:
    """Trace a client's connection path from device through network to gateway.

    When to use this tool:
    - Understanding how a client device connects to the network
    - Troubleshooting client connectivity issues (slow speeds, drops)
    - Verifying client VLAN assignment and path
    - Diagnosing wireless client issues (roaming, signal strength)

    Common workflow:
    1. Use client_trace() to see the complete path from client to gateway
    2. Use link_quality() if you see performance issues on any hop
    3. Use firewall_check() to verify the client can reach desired destinations
    4. Use system_load() if any device in the path shows high latency

    What to do next:
    - If path incomplete: Check if client is online and authenticated
    - If wireless issues: Check AP placement and channel conflicts
    - If VLAN issues: Use vlan_info() to verify VLAN configuration
    - If firewall blocks client: Use firewall_check() for rule analysis

    Args:
        client: Client device identifier - can be:
                - MAC address (aa:bb:cc:dd:ee:ff)
                - IP address (192.168.1.100)
                - Hostname (johns-laptop)
                - Device name or display name

    Returns:
        NetworkPath showing complete path from client → AP/Switch → Gateway

    Raises:
        ToolError: DEVICE_NOT_FOUND if client not found on network
        ToolError: PATH_INCOMPLETE if cannot trace complete path to gateway
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to controller
    """
    async with UniFiClient() as client_api:
        # Find the client device first
        clients_data = await client_api.get(client_api.build_path('stat/sta'))
        client_info = _find_client_by_identifier(client.lower(), clients_data)

        if not client_info:
            raise ToolError(
                message=f'Client "{client}" not found on network',
                error_code=ErrorCodes.DEVICE_NOT_FOUND,
                suggestion=(
                    'Client may be offline, disconnected, or identifier is incorrect. '
                    'Verify client is connected and try find_device() for more search options.'
                ),
                related_tools=['find_device', 'find_mac', 'get_network_topology'],
            )

        # Get network infrastructure to build path
        devices_data = await client_api.get(client_api.build_path('stat/device'))

        # Build path from client to gateway
        path = await _build_client_path(client_info, devices_data)

        return path


def _find_client_by_identifier(
    identifier: str, clients_data: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Find client by various identifiers."""
    for client_info in clients_data:
        # Check MAC address
        if client_info.get('mac', '').lower() == identifier:
            return client_info

        # Check IP address
        if client_info.get('ip', '').lower() == identifier:
            return client_info

        # Check hostname/name (exact and partial)
        hostname = client_info.get('hostname', '').lower()
        name = client_info.get('name', '').lower()
        display_name = client_info.get('display_name', '').lower()

        if (
            hostname == identifier
            or name == identifier
            or display_name == identifier
            or identifier in hostname
            or identifier in name
            or identifier in display_name
        ):
            return client_info

    return None


async def _build_client_path(
    client_info: dict[str, Any], devices_data: list[dict[str, Any]]
) -> NetworkPath:
    """Build complete path from client to gateway."""
    hops = []
    current_device = client_info

    # Client as first hop
    client_hop = PathHop(
        hop_number=1,
        device_mac=current_device['mac'],
        device_name=(
            current_device.get('display_name')
            or current_device.get('hostname')
            or current_device.get('name', 'Unknown Client')
        ),
        device_type='client',
        interface='client',
        vlan=current_device.get('vlan', 1),
        latency_ms=0.0,  # Client is start point
    )
    hops.append(client_hop)

    hop_number = 2

    # Find immediate parent (AP for wireless, switch for wired)
    connection_type = 'wireless' if not current_device.get('is_wired', False) else 'wired'
    parent_mac = (
        current_device.get('ap_mac')
        if connection_type == 'wireless'
        else current_device.get('sw_mac')
    )

    if not parent_mac:
        raise ToolError(
            message='Cannot determine client connection point',
            error_code=ErrorCodes.PATH_INCOMPLETE,
            suggestion='Client connection data incomplete. Client may have just connected.',
        )

    # Find parent device in infrastructure
    parent_device = _find_device_by_mac(parent_mac, devices_data)
    if not parent_device:
        raise ToolError(
            message=f'Parent device {parent_mac} not found',
            error_code=ErrorCodes.PATH_INCOMPLETE,
            suggestion='Infrastructure device data incomplete.',
        )

    # Parent device hop
    parent_port = (
        current_device.get('sw_port', 'wireless')
        if connection_type == 'wired'
        else f'radio{current_device.get("radio", 0)}'
    )

    parent_hop = PathHop(
        hop_number=hop_number,
        device_mac=parent_device['mac'],
        device_name=parent_device.get('name', '') or parent_device.get('hostname', ''),
        device_type=_map_device_type(parent_device.get('type', '')),
        interface=parent_port,
        vlan=current_device.get('vlan', 1),
        latency_ms=None,  # Will be populated by actual ping if available
    )
    hops.append(parent_hop)

    # Follow uplink chain to gateway
    current_device = parent_device
    hop_number += 1

    while current_device and current_device.get('uplink', {}).get('uplink_mac'):
        uplink_mac = current_device['uplink']['uplink_mac']
        uplink_device = _find_device_by_mac(uplink_mac, devices_data)

        if not uplink_device:
            break

        uplink_hop = PathHop(
            hop_number=hop_number,
            device_mac=uplink_device['mac'],
            device_name=uplink_device.get('name', '') or uplink_device.get('hostname', ''),
            device_type=_map_device_type(uplink_device.get('type', '')),
            interface=f'port{current_device["uplink"].get("uplink_remote_port", "unknown")}',
            vlan=current_device.get('config', {}).get('vlan', 1),
        )
        hops.append(uplink_hop)

        current_device = uplink_device
        hop_number += 1

        # Prevent infinite loops
        if hop_number > 10:
            break

    # Create NetworkPath
    return NetworkPath(
        source=client_info.get('display_name')
        or client_info.get('hostname')
        or client_info['mac'],
        source_resolved=client_info['mac'],
        source_name=client_info.get('display_name') or client_info.get('hostname', ''),
        destination='gateway',
        destination_resolved=hops[-1].device_mac if hops else '',
        destination_name=hops[-1].device_name if hops else '',
        hops=hops,
        crosses_vlans=False,  # Client path typically stays in same VLAN
        vlans_traversed=[client_info.get('vlan', 1)],
        is_l2_only=True,  # Client to infrastructure is L2
        is_l3_routed=False,
        firewall_verdict='unknown',  # Will be determined by firewall_check if needed
    )


def _find_device_by_mac(mac: str, devices_data: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find device in devices list by MAC address."""
    for device in devices_data:
        if device.get('mac', '').lower() == mac.lower():
            return device
    return None


def _map_device_type(unifi_type: str) -> str:
    """Map UniFi device type to our device type."""
    type_mapping = {
        'usw': 'switch',
        'uap': 'ap',
        'ugw': 'gateway',
        'udm': 'gateway',
        'uxg': 'gateway',
    }
    return type_mapping.get(unifi_type.lower(), 'switch')
