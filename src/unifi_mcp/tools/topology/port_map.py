"""Port map tool for detailed switch port information."""

from pydantic import Field
from typing import Annotated, Any
from unifi_mcp.models import Port
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


async def get_port_map(
    device: Annotated[
        str | None,
        Field(description='Specific device to get port map for (defaults to all switches)'),
    ] = None,
    include_empty: Annotated[
        bool, Field(description='Include ports with no active connection')
    ] = False,
) -> list[Port]:
    """Get port status and connections for switches with naming audit.

    When to use this tool:
    - Viewing all switch port statuses and connections
    - Finding available ports for new device connections
    - Auditing port naming and VLAN assignments
    - Identifying Half Duplex connections (should be none)
    - Checking for unnamed or incorrectly named ports

    Common workflow:
    1. Use get_port_map() to see all ports with their current status
    2. Use port_config() to get detailed settings for specific problematic ports
    3. Use vlan_info() to verify VLAN configurations match port assignments
    4. Use find_device() to get details on connected devices

    What to do next:
    - For Half Duplex ports: Check port configuration, may need auto-negotiate
    - For unnamed ports: Use connected device name to create appropriate port name
    - For errors/drops: Use link_quality() for detailed interface statistics
    - For VLAN issues: Use vlan_info() to verify VLAN configuration

    Args:
        device: Specific switch identifier (MAC, IP, or name).
               If None, returns ports from all switches.
        include_empty: Whether to include ports with no device connected.
                      Useful for finding available ports.

    Returns:
        List of Port models with:
        - Port configuration (speed, duplex, VLAN, PoE)
        - Connection status and connected device info
        - Naming audit (unnamed ports flagged)
        - Trunk vs access port identification
        - Error counts and statistics

    Raises:
        ToolError: DEVICE_NOT_FOUND if specified device is not a switch
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to controller
    """
    async with UniFiClient() as client:
        # Get all devices to find switches
        devices_data = await client.get(client.build_path('stat/device'))
        clients_data = await client.get(client.build_path('stat/sta'))

        # Filter to switches only
        if device:
            # Find specific device
            target_device = _find_switch_by_identifier(device.lower(), devices_data)
            if not target_device:
                raise ToolError(
                    message=f'Switch device "{device}" not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Verify device exists and is a switch. Use find_device() first.',
                    related_tools=['find_device', 'get_network_topology'],
                )
            switches_data = [target_device]
        else:
            # Get all switches
            switches_data = [d for d in devices_data if d.get('type', '').lower() in ('usw',)]

        if not switches_data:
            raise ToolError(
                message='No switches found on network',
                error_code=ErrorCodes.DEVICE_NOT_FOUND,
                suggestion='Check network configuration or specify device type correctly',
                related_tools=['get_network_topology', 'find_device'],
            )

        # Get port information for each switch
        all_ports = []
        for switch_data in switches_data:
            ports = await _get_switch_ports(client, switch_data, clients_data, include_empty)
            all_ports.extend(ports)

        return all_ports


def _find_switch_by_identifier(
    identifier: str, devices_data: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Find switch device by identifier."""
    for device in devices_data:
        if device.get('type', '').lower() != 'usw':
            continue  # Skip non-switches

        # Check MAC
        if device.get('mac', '').lower() == identifier:
            return device

        # Check IP
        if device.get('ip', '').lower() == identifier:
            return device

        # Check name
        device_name = device.get('name', '').lower()
        hostname = device.get('hostname', '').lower()
        if (
            device_name == identifier
            or hostname == identifier
            or identifier in device_name
            or identifier in hostname
        ):
            return device

    return None


async def _get_switch_ports(
    client: UniFiClient,
    switch_data: dict[str, Any],
    clients_data: list[dict[str, Any]],
    include_empty: bool,
) -> list[Port]:
    """Get ports for a specific switch."""
    switch_mac = switch_data.get('mac', '')
    switch_name = switch_data.get('name', '') or switch_data.get('hostname', '')

    # Get port overrides/configuration
    try:
        port_overrides_data = await client.get(
            client.build_path(f'rest/device/{switch_data.get("_id", "")}')
        )
    except Exception:
        port_overrides_data = {}

    # Get port statistics
    port_stats = switch_data.get('port_table', [])

    ports = []
    for port_stat in port_stats:
        port_idx = port_stat.get('port_idx', 0)
        if port_idx == 0:
            continue  # Skip SFP/uplink ports in some cases

        # Find any port override config
        port_override = _find_port_override(port_idx, port_overrides_data)

        # Find connected client
        connected_client = _find_client_on_port(switch_mac, port_idx, clients_data)

        # Create Port model
        port = Port(
            port_idx=port_idx,
            name=port_override.get('name') if port_override else None,
            enabled=port_stat.get('enable', True),
            up=port_stat.get('up', False),
            speed=port_stat.get('speed', 0),
            duplex=port_stat.get('full_duplex', True) and 'full' or 'half',
            poe_mode=port_stat.get('poe_mode', 'off'),
            poe_power=port_stat.get('poe_power', 0.0),
            vlan=port_override.get('native_networkconf_id', 1) if port_override else 1,
            tagged_vlans=port_override.get('networkconf_ids', []) if port_override else [],
            is_trunk=len(port_override.get('networkconf_ids', [])) > 1 if port_override else False,
            connected_mac=connected_client.get('mac') if connected_client else None,
            connected_device_name=connected_client.get('display_name')
            if connected_client
            else None,
            device_mac=switch_mac,
            device_name=switch_name,
            rx_bytes=port_stat.get('rx_bytes', 0),
            tx_bytes=port_stat.get('tx_bytes', 0),
            rx_errors=port_stat.get('rx_errors', 0),
            tx_errors=port_stat.get('tx_errors', 0),
            rx_dropped=port_stat.get('rx_dropped', 0),
            tx_dropped=port_stat.get('tx_dropped', 0),
        )

        # Only include port if it has connection or if include_empty is True
        if include_empty or port.up or port.connected_mac:
            ports.append(port)

    return ports


def _find_port_override(
    port_idx: int, port_overrides_data: dict[str, Any]
) -> dict[str, Any] | None:
    """Find port override configuration for specific port."""
    port_overrides = port_overrides_data.get('port_overrides', [])

    for override in port_overrides:
        if override.get('port_idx') == port_idx:
            return override

    return None


def _find_client_on_port(
    switch_mac: str, port_idx: int, clients_data: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Find client connected to specific switch port."""
    for client in clients_data:
        if (
            client.get('sw_mac', '').lower() == switch_mac.lower()
            and client.get('sw_port') == port_idx
            and client.get('is_wired', False)
        ):
            return client

    return None
