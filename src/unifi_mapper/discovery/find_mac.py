"""Find MAC address tool for locating MAC addresses on the network."""

import time
from pydantic import Field
from typing import Annotated, Any
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


async def find_mac(
    mac: Annotated[str, Field(description='MAC address to locate (any format)')],
) -> dict[str, Any]:
    """Find the physical location and details of a MAC address on the network.

    When to use this tool:
    - Locating where a device is physically connected
    - Identifying unknown devices on the network
    - Verifying device placement and connection
    - Troubleshooting MAC address conflicts

    Common workflow:
    1. Use find_mac() to locate the device's switch and port
    2. Use port_config() to check port settings if needed
    3. Use vlan_info() to verify VLAN assignment
    4. Use get_device_tree() to see device's position in network hierarchy

    What to do next:
    - If found on switch port: Use port_config() to check port settings
    - If found on AP: Device is wireless, use client_trace() for wireless path
    - If not found: Device may be offline, check if it was recently connected

    Args:
        mac: MAC address in any format:
             - Colon format: aa:bb:cc:dd:ee:ff
             - Hyphen format: aa-bb-cc-dd-ee-ff
             - No separators: aabbccddeeff
             - Mixed case: AA:BB:CC:DD:EE:FF

    Returns:
        Dictionary containing:
        - device_type: 'infrastructure' or 'client'
        - device_name: Name of the device
        - connection_type: 'wired' or 'wireless'
        - connected_to: Name/MAC of parent device (switch/AP)
        - port_number: Port number if wired connection
        - vlan: VLAN ID
        - ip_address: Current IP if assigned
        - first_seen: Timestamp when first detected
        - last_seen: Timestamp when last seen
        - is_online: Current online status

    Raises:
        ToolError: MAC_NOT_FOUND if MAC address not found on network
        ToolError: INVALID_MAC if MAC address format is invalid
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to controller
    """
    # Normalize MAC address format
    normalized_mac = _normalize_mac_address(mac)
    if not normalized_mac:
        raise ToolError(
            message=f'Invalid MAC address format: {mac}',
            error_code=ErrorCodes.INVALID_MAC,
            suggestion='Use format: aa:bb:cc:dd:ee:ff, aa-bb-cc-dd-ee-ff, or aabbccddeeff',
            related_tools=['find_device', 'find_ip'],
        )

    async with UniFiClient() as client:
        # Search infrastructure devices first
        devices_data = await client.get(client.build_path('stat/device'))
        device_info = _find_mac_in_devices(normalized_mac, devices_data)

        if device_info:
            return device_info

        # Search clients
        clients_data = await client.get(client.build_path('stat/sta'))
        client_info = _find_mac_in_clients(normalized_mac, clients_data)

        if client_info:
            return client_info

        # Check ARP table / known clients (historical data)
        known_clients = await client.get(client.build_path('stat/alluser'))
        historical_info = _find_mac_in_historical(normalized_mac, known_clients)

        if historical_info:
            return historical_info

        # MAC not found anywhere
        raise ToolError(
            message=f'MAC address {normalized_mac} not found on network',
            error_code=ErrorCodes.DEVICE_NOT_FOUND,
            suggestion=(
                'Device may be offline or never connected to this network. '
                'Check if device is powered on and connected.'
            ),
            related_tools=['get_network_topology', 'find_device'],
        )


def _normalize_mac_address(mac: str) -> str | None:
    """Normalize MAC address to standard format (aa:bb:cc:dd:ee:ff)."""
    # Remove all non-hex characters
    mac_clean = ''.join(c for c in mac.lower() if c in '0123456789abcdef')

    # Must be exactly 12 hex characters
    if len(mac_clean) != 12:
        return None

    # Format as aa:bb:cc:dd:ee:ff
    return ':'.join(mac_clean[i : i + 2] for i in range(0, 12, 2))


def _find_mac_in_devices(mac: str, devices_data: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Search for MAC in infrastructure devices."""
    for device in devices_data:
        if device.get('mac', '').lower() == mac.lower():
            return {
                'device_type': 'infrastructure',
                'device_name': device.get('name', '') or device.get('hostname', ''),
                'device_model': device.get('model', ''),
                'connection_type': 'wired',
                'connected_to': device.get('uplink', {}).get('uplink_mac', 'Unknown'),
                'port_number': device.get('uplink', {}).get('uplink_remote_port'),
                'vlan': device.get('config', {}).get('vlan', 1),
                'ip_address': device.get('ip'),
                'first_seen': device.get('first_seen', int(time.time())),
                'last_seen': device.get('last_seen', int(time.time())),
                'is_online': device.get('state', 0) == 1,
                'uptime_seconds': device.get('uptime', 0),
            }
    return None


def _find_mac_in_clients(mac: str, clients_data: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Search for MAC in client devices."""
    for client in clients_data:
        if client.get('mac', '').lower() == mac.lower():
            # Determine connection type
            connection_type = 'wireless' if client.get('is_wired', False) is False else 'wired'
            connected_to = (
                client.get('ap_mac') if connection_type == 'wireless' else client.get('sw_mac')
            )

            return {
                'device_type': 'client',
                'device_name': (
                    client.get('display_name')
                    or client.get('hostname')
                    or client.get('name', 'Unknown Client')
                ),
                'device_model': client.get('oui', 'Unknown'),
                'connection_type': connection_type,
                'connected_to': connected_to,
                'port_number': client.get('sw_port') if connection_type == 'wired' else None,
                'vlan': client.get('vlan', 1),
                'ip_address': client.get('ip'),
                'first_seen': client.get('first_seen', int(time.time())),
                'last_seen': client.get('last_seen', int(time.time())),
                'is_online': True,  # Clients in stat/sta are currently online
                'signal_strength': client.get('signal') if connection_type == 'wireless' else None,
                'channel': client.get('channel') if connection_type == 'wireless' else None,
            }
    return None


def _find_mac_in_historical(
    mac: str, known_clients: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Search for MAC in historical client data."""
    for client in known_clients:
        if client.get('mac', '').lower() == mac.lower():
            last_seen = client.get('last_seen', 0)
            is_recent = (int(time.time()) - last_seen) < 86400  # Within 24 hours

            return {
                'device_type': 'client',
                'device_name': (
                    client.get('display_name')
                    or client.get('hostname')
                    or client.get('name', 'Unknown Client')
                ),
                'device_model': client.get('oui', 'Historical'),
                'connection_type': 'unknown',
                'connected_to': 'Last known location',
                'port_number': None,
                'vlan': client.get('vlan', 1),
                'ip_address': client.get('ip', 'Unknown'),
                'first_seen': client.get('first_seen', 0),
                'last_seen': last_seen,
                'is_online': False,
                'note': f'Historical data - last seen {"recently" if is_recent else "more than 24h ago"}',
            }
    return None
