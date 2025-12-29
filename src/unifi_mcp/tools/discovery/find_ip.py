"""Find IP address tool for locating devices by IP."""

import time
from pydantic import Field
from typing import Annotated, Any
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


async def find_ip(
    ip: Annotated[str, Field(description='IP address to locate on the network')],
) -> dict[str, Any]:
    """Find a device by its IP address and show connection details.

    When to use this tool:
    - Looking up device information from an IP address
    - Identifying what device is using a specific IP
    - Troubleshooting IP conflicts or connectivity issues
    - Verifying DHCP assignments

    Common workflow:
    1. Use find_ip() to identify the device at this IP
    2. Use find_device() or find_mac() for more detailed device info
    3. Use traceroute() to test connectivity to this IP
    4. Use vlan_info() to check VLAN configuration for this IP range

    What to do next:
    - If device found: Use traceroute() to test connectivity
    - If IP not found: Check if it's in the correct subnet, verify device is online
    - If IP conflict: Use get_network_topology() to see all devices with IPs
    - For DHCP issues: Use vlan_info() to check DHCP configuration

    Args:
        ip: IP address to search for (IPv4 format like 192.168.1.100)

    Returns:
        Dictionary containing:
        - device_mac: MAC address of device using this IP
        - device_name: Name/hostname of the device
        - device_type: Type (switch, ap, gateway, client)
        - device_model: Hardware model
        - vlan_id: VLAN this IP belongs to
        - vlan_name: Name of the VLAN
        - subnet: Network subnet (e.g., 192.168.1.0/24)
        - dhcp_assigned: Whether IP was assigned by DHCP
        - lease_time: DHCP lease time if applicable
        - connection_info: How device connects to network
        - first_seen: When IP was first seen
        - last_seen: When IP was last seen

    Raises:
        ToolError: IP_NOT_FOUND if IP address not found on any device
        ToolError: INVALID_IP if IP address format is invalid
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to controller
    """
    # Validate IP address format (basic check)
    if not _is_valid_ipv4(ip):
        raise ToolError(
            message=f'Invalid IP address format: {ip}',
            error_code=ErrorCodes.INVALID_IP,
            suggestion='Use IPv4 format like 192.168.1.100',
            related_tools=['find_device', 'find_mac'],
        )

    async with UniFiClient() as client:
        # Search infrastructure devices
        devices_data = await client.get(client.build_path('stat/device'))
        device_info = _find_ip_in_devices(ip, devices_data)

        if device_info:
            return device_info

        # Search clients
        clients_data = await client.get(client.build_path('stat/sta'))
        client_info = _find_ip_in_clients(ip, clients_data)

        if client_info:
            return client_info

        # Get VLAN info to provide context about IP range
        vlans_data = await client.get(client.build_path('rest/networkconf'))
        vlan_context = _get_vlan_context_for_ip(ip, vlans_data)

        if vlan_context:
            # IP is in a known VLAN range but no device found
            raise ToolError(
                message=f'IP address {ip} not found on any device',
                error_code=ErrorCodes.DEVICE_NOT_FOUND,
                suggestion=(
                    f'IP is in VLAN "{vlan_context["vlan_name"]}" range but no device found. '
                    'Device may be offline or IP may be unassigned.'
                ),
                related_tools=['get_network_topology', 'vlan_info'],
            )

        # IP not found and not in any known VLAN range
        is_rfc1918 = _is_rfc1918_ip(ip)
        if not is_rfc1918:
            suggestion = (
                'This appears to be a public IP address. Are you trying to trace to '
                'an Internet destination? Use traceroute with destination="internet".'
            )
        else:
            suggestion = (
                'IP not found in any configured VLAN. Check if IP is in correct subnet '
                'or if device is powered on.'
            )

        raise ToolError(
            message=f'IP address {ip} not found on network',
            error_code=ErrorCodes.DEVICE_NOT_FOUND,
            suggestion=suggestion,
            related_tools=['get_network_topology', 'vlan_info', 'traceroute'],
        )


def _is_valid_ipv4(ip: str) -> bool:
    """Basic IPv4 validation."""
    try:
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        for part in parts:
            num = int(part)
            if not 0 <= num <= 255:
                return False
        return True
    except (ValueError, AttributeError):
        return False


def _is_rfc1918_ip(ip: str) -> bool:
    """Check if IP is in RFC1918 private ranges."""
    try:
        parts = [int(p) for p in ip.split('.')]
        if len(parts) != 4:
            return False

        first, second = parts[0], parts[1]

        # 10.0.0.0/8
        if first == 10:
            return True

        # 172.16.0.0/12
        if first == 172 and 16 <= second <= 31:
            return True

        # 192.168.0.0/16
        if first == 192 and second == 168:
            return True

        return False
    except (ValueError, IndexError):
        return False


def _find_ip_in_devices(ip: str, devices_data: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Search for IP in infrastructure devices."""
    for device in devices_data:
        if device.get('ip', '').lower() == ip.lower():
            return {
                'device_mac': device.get('mac', ''),
                'device_name': device.get('name', '') or device.get('hostname', ''),
                'device_type': 'infrastructure',
                'device_model': device.get('model', ''),
                'vlan_id': device.get('config', {}).get('vlan', 1),
                'vlan_name': f'VLAN {device.get("config", {}).get("vlan", 1)}',  # Will enhance with actual name later
                'subnet': 'Unknown',  # Will be resolved from VLAN config
                'dhcp_assigned': device.get('config', {}).get('type') == 'dhcp',
                'connection_info': {
                    'type': 'infrastructure',
                    'uplink_mac': device.get('uplink', {}).get('uplink_mac'),
                    'uplink_port': device.get('uplink', {}).get('uplink_remote_port'),
                },
                'first_seen': device.get('first_seen', int(time.time())),
                'last_seen': device.get('last_seen', int(time.time())),
                'is_online': device.get('state', 0) == 1,
            }
    return None


def _find_ip_in_clients(ip: str, clients_data: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Search for IP in client devices."""
    for client in clients_data:
        if client.get('ip', '').lower() == ip.lower():
            connection_type = 'wireless' if not client.get('is_wired', False) else 'wired'

            return {
                'device_mac': client.get('mac', ''),
                'device_name': (
                    client.get('display_name')
                    or client.get('hostname')
                    or client.get('name', 'Unknown Client')
                ),
                'device_type': 'client',
                'device_model': client.get('oui', 'Unknown'),
                'vlan_id': client.get('vlan', 1),
                'vlan_name': client.get('network', 'Default'),
                'subnet': client.get('network_id', 'Unknown'),  # Network ID maps to subnet
                'dhcp_assigned': True,  # Clients typically get DHCP
                'lease_time': client.get('dhcp_end_time', 0) - int(time.time())
                if client.get('dhcp_end_time')
                else None,
                'connection_info': {
                    'type': connection_type,
                    'connected_to_mac': client.get('ap_mac') or client.get('sw_mac'),
                    'port_number': client.get('sw_port') if connection_type == 'wired' else None,
                    'signal_strength': client.get('signal')
                    if connection_type == 'wireless'
                    else None,
                    'channel': client.get('channel') if connection_type == 'wireless' else None,
                },
                'first_seen': client.get('first_seen', int(time.time())),
                'last_seen': client.get('last_seen', int(time.time())),
                'is_online': True,  # Clients in active list are online
            }
    return None


def _get_vlan_context_for_ip(ip: str, vlans_data: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Get VLAN context for an IP address."""
    import ipaddress

    try:
        ip_addr = ipaddress.IPv4Address(ip)

        for vlan in vlans_data:
            if 'ip_subnet' in vlan:
                try:
                    network = ipaddress.IPv4Network(vlan['ip_subnet'], strict=False)
                    if ip_addr in network:
                        return {
                            'vlan_id': vlan.get('vlan', 1),
                            'vlan_name': vlan.get('name', f'VLAN {vlan.get("vlan", 1)}'),
                            'subnet': str(network),
                            'gateway': vlan.get('ip', 'Unknown'),
                        }
                except (ipaddress.AddressValueError, ValueError):
                    continue

    except ipaddress.AddressValueError:
        pass

    return None
