"""Find device tool for locating devices on the network."""

import time
from pydantic import Field
from typing import Annotated, Any
from unifi_mapper.core.models import Device
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


async def find_device(
    identifier: Annotated[
        str,
        Field(description='Device identifier: MAC address, IP address, hostname, or partial name'),
    ],
) -> Device:
    """Find a device on the network by various identifiers.

    When to use this tool:
    - Before traceroute to verify endpoint exists
    - To look up device details by MAC, IP, or name
    - When troubleshooting connectivity and need device information

    Common workflow:
    1. Use find_device() to locate and verify the device exists
    2. Use get_port_map() to see its physical connection details
    3. Use traceroute() if you need to trace the path to/from this device

    What to do next:
    - If device found: Use traceroute() or client_trace() for path analysis
    - If device not found: Check if device is powered on, verify identifier spelling
    - For clients: Use client_trace() to see connection path through APs

    Args:
        identifier: Device identifier - can be:
                   - MAC address (aa:bb:cc:dd:ee:ff or AA-BB-CC-DD-EE-FF)
                   - IP address (192.168.1.100)
                   - Hostname or device name (exact or partial match)
                   - Model name (partial match, e.g., "Pro-48")

    Returns:
        Device model with complete device information including connection details

    Raises:
        ToolError: DEVICE_NOT_FOUND if device cannot be located on the network
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
        ToolError: API_ERROR for other API-related issues
    """
    async with UniFiClient() as client:
        # Get all devices from controller
        devices_data = await client.get(client.build_path('stat/device'))
        clients_data = await client.get(client.build_path('stat/sta'))

        # Search through devices first (infrastructure)
        device = _search_devices(identifier.lower(), devices_data)
        if device:
            return device

        # Search through clients (connected devices)
        device = _search_clients(identifier.lower(), clients_data)
        if device:
            return device

        # Device not found anywhere
        raise ToolError(
            message=f'Device with identifier "{identifier}" not found on network',
            error_code=ErrorCodes.DEVICE_NOT_FOUND,
            suggestion=(
                'Verify the identifier is correct. Device may be offline or disconnected. '
                'Try a different identifier (MAC, IP, or name).'
            ),
            related_tools=['get_network_topology', 'find_mac', 'find_ip'],
        )


def _search_devices(identifier: str, devices_data: list[dict[str, Any]]) -> Device | None:
    """Search through UniFi devices (switches, APs, gateways)."""
    for device_info in devices_data:
        # Check MAC address
        if device_info.get('mac', '').lower() == identifier:
            return _convert_device_data(device_info, 'infrastructure')

        # Check IP address
        if device_info.get('ip', '').lower() == identifier:
            return _convert_device_data(device_info, 'infrastructure')

        # Check device name/hostname (exact and partial)
        device_name = device_info.get('name', '').lower()
        hostname = device_info.get('hostname', '').lower()

        if (
            device_name == identifier
            or hostname == identifier
            or identifier in device_name
            or identifier in hostname
        ):
            return _convert_device_data(device_info, 'infrastructure')

        # Check model name (partial match)
        model = device_info.get('model', '').lower()
        if identifier in model:
            return _convert_device_data(device_info, 'infrastructure')

    return None


def _search_clients(identifier: str, clients_data: list[dict[str, Any]]) -> Device | None:
    """Search through UniFi clients (connected devices)."""
    for client_info in clients_data:
        # Check MAC address
        if client_info.get('mac', '').lower() == identifier:
            return _convert_client_data(client_info)

        # Check IP address
        if client_info.get('ip', '').lower() == identifier:
            return _convert_client_data(client_info)

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
            return _convert_client_data(client_info)

    return None


def _convert_device_data(device_info: dict[str, Any], source: str) -> Device:
    """Convert UniFi device API data to Device model."""
    # Map UniFi device types to our types
    type_mapping = {
        'usw': 'switch',  # UniFi Switch
        'uap': 'ap',  # UniFi Access Point
        'ugw': 'gateway',  # UniFi Gateway
        'udm': 'gateway',  # UniFi Dream Machine
        'uxg': 'gateway',  # UniFi Next-Gen Gateway
    }

    unifi_type = device_info.get('type', '').lower()
    device_type = type_mapping.get(unifi_type, 'switch')  # Default to switch

    return Device(
        mac=device_info.get('mac', ''),
        name=device_info.get('name', '') or device_info.get('hostname', ''),
        model=device_info.get('model', ''),
        ip=device_info.get('ip'),
        type=device_type,
        uptime=device_info.get('uptime', 0),
        connected_to=device_info.get('uplink', {}).get('uplink_mac'),
        port_idx=device_info.get('uplink', {}).get('uplink_remote_port'),
        site_id=device_info.get('site_id', 'default'),
        # System metrics if available
        cpu_percent=device_info.get('system-stats', {}).get('cpu'),
        memory_percent=device_info.get('system-stats', {}).get('mem'),
        load_average=device_info.get('system-stats', {}).get('loadavg_1'),
    )


def _convert_client_data(client_info: dict[str, Any]) -> Device:
    """Convert UniFi client API data to Device model."""
    return Device(
        mac=client_info.get('mac', ''),
        name=(
            client_info.get('display_name')
            or client_info.get('hostname')
            or client_info.get('name', '')
        ),
        model=client_info.get('oui', 'Unknown Client'),  # Use OUI as model for clients
        ip=client_info.get('ip'),
        type='client',
        uptime=int(time.time()) - client_info.get('first_seen', int(time.time())),
        connected_to=client_info.get('ap_mac') or client_info.get('sw_mac'),
        port_idx=client_info.get('sw_port'),
        site_id=client_info.get('site_id', 'default'),
    )
