"""Device tree tool for hierarchical device view."""

from pydantic import Field
from typing import Annotated, Any
from unifi_mcp.models import Device
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


async def get_device_tree(
    root_device: Annotated[
        str | None,
        Field(description='Root device identifier (defaults to gateway)'),
    ] = None,
) -> dict[str, Any]:
    """Get hierarchical device tree from gateway to endpoints.

    When to use this tool:
    - Visualizing device hierarchy and upstream/downstream relationships
    - Understanding how devices connect through the network
    - Finding all devices connected to a specific switch or AP
    - Troubleshooting uplink issues or network loops

    Common workflow:
    1. Use get_device_tree() to see overall device hierarchy
    2. Use get_port_map() to see port-level details for specific switches
    3. Use find_device() to get detailed info on any device in the tree
    4. Use traceroute() to verify connectivity within the tree

    What to do next:
    - For switch details: Use get_port_map() on switch devices
    - For connectivity issues: Use traceroute() between devices
    - For device problems: Use system_load() on specific devices
    - For client issues: Use client_trace() to follow client paths

    Args:
        root_device: Starting device for tree (MAC, IP, or name).
                    If None, uses gateway as root. Can also be a specific
                    switch to see only devices downstream from it.

    Returns:
        Dictionary containing:
        - root: Root device information
        - tree: Hierarchical structure with all downstream devices
        - depth_stats: Statistics about tree depth and branching
        - connection_summary: Summary of connection types and counts
        - potential_issues: Any detected topology issues

    Raises:
        ToolError: DEVICE_NOT_FOUND if specified root device not found
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to controller
    """
    async with UniFiClient() as client:
        # Get all devices
        devices_data = await client.get(client.build_path('stat/device'))

        # Convert to Device models
        devices = [_convert_device_data(device_info) for device_info in devices_data]

        # Find root device
        if root_device:
            root = _find_device_by_identifier(root_device.lower(), devices)
            if not root:
                raise ToolError(
                    message=f'Root device "{root_device}" not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Use find_device() to verify device exists and get exact identifier',
                    related_tools=['find_device', 'get_network_topology'],
                )
        else:
            # Find gateway as default root
            gateways = [d for d in devices if d.type == 'gateway']
            if not gateways:
                raise ToolError(
                    message='No gateway device found on network',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Specify a root device explicitly or check network configuration',
                    related_tools=['get_network_topology', 'find_device'],
                )
            root = gateways[0]

        # Build tree from root
        tree = _build_tree_recursive(root, devices, visited=set())

        # Calculate statistics
        depth_stats = _calculate_tree_depth(tree)
        connection_summary = _build_connection_summary(devices)
        potential_issues = _detect_topology_issues(devices)

        return {
            'root': root.dict(),
            'tree': tree,
            'depth_stats': depth_stats,
            'connection_summary': connection_summary,
            'potential_issues': potential_issues,
        }


def _convert_device_data(device_info: dict[str, Any]) -> Device:
    """Convert UniFi device API data to Device model."""
    type_mapping = {
        'usw': 'switch',
        'uap': 'ap',
        'ugw': 'gateway',
        'udm': 'gateway',
        'uxg': 'gateway',
    }

    device_type = type_mapping.get(device_info.get('type', '').lower(), 'switch')

    return Device(
        mac=device_info.get('mac', ''),
        name=device_info.get('name', '') or device_info.get('hostname', ''),
        model=device_info.get('model', ''),
        ip=device_info.get('ip'),
        type=device_type,  # type: ignore
        uptime=device_info.get('uptime', 0),
        connected_to=device_info.get('uplink', {}).get('uplink_mac'),
        port_idx=device_info.get('uplink', {}).get('uplink_remote_port'),
    )


def _find_device_by_identifier(identifier: str, devices: list[Device]) -> Device | None:
    """Find device by various identifiers."""
    for device in devices:
        # Check MAC
        if device.mac.lower() == identifier:
            return device

        # Check IP
        if device.ip and device.ip.lower() == identifier:
            return device

        # Check name (exact and partial)
        if device.name.lower() == identifier or identifier in device.name.lower():
            return device

    return None


def _build_tree_recursive(
    parent: Device, all_devices: list[Device], visited: set[str], depth: int = 0
) -> dict[str, Any]:
    """Build device tree recursively."""
    if parent.mac in visited or depth > 10:  # Prevent loops and limit depth
        return {'device': parent.dict(), 'children': {}, 'loop_detected': True}

    visited.add(parent.mac)

    # Find children
    children = [d for d in all_devices if d.connected_to == parent.mac]

    subtree = {
        'device': parent.dict(),
        'children': {},
        'child_count': len(children),
        'depth': depth,
    }

    for child in children:
        subtree['children'][child.mac] = _build_tree_recursive(
            child, all_devices, visited.copy(), depth + 1
        )

    return subtree


def _calculate_tree_depth(tree: dict[str, Any]) -> dict[str, Any]:
    """Calculate tree depth statistics."""

    def _max_depth(node: dict[str, Any], current_depth: int = 0) -> int:
        if not node.get('children'):
            return current_depth

        max_child_depth = max(
            _max_depth(child, current_depth + 1) for child in node['children'].values()
        )
        return max_child_depth

    max_depth = _max_depth(tree)
    total_nodes = _count_nodes(tree)

    return {
        'max_depth': max_depth,
        'total_nodes': total_nodes,
        'average_branching': total_nodes / max(1, max_depth),
    }


def _count_nodes(tree: dict[str, Any]) -> int:
    """Count total nodes in tree."""
    count = 1  # Count this node
    if tree.get('children'):
        count += sum(_count_nodes(child) for child in tree['children'].values())
    return count


def _build_connection_summary(devices: list[Device]) -> dict[str, Any]:
    """Build connection type summary."""
    wired_devices = len([d for d in devices if d.type in ('switch', 'gateway')])
    wireless_devices = len([d for d in devices if d.type == 'ap'])
    clients = len([d for d in devices if d.type == 'client'])

    return {
        'wired_infrastructure': wired_devices,
        'wireless_infrastructure': wireless_devices,
        'connected_clients': clients,
        'connection_types': {
            'switch_to_switch': len([d for d in devices if d.type == 'switch' and d.connected_to]),
            'ap_to_switch': len([d for d in devices if d.type == 'ap' and d.connected_to]),
        },
    }


def _detect_topology_issues(devices: list[Device]) -> list[dict[str, str]]:
    """Detect potential topology issues."""
    issues = []

    # Check for devices without names
    unnamed_devices = [d for d in devices if not d.name and d.type != 'client']
    if unnamed_devices:
        issues.append(
            {
                'type': 'unnamed_devices',
                'severity': 'medium',
                'description': f'{len(unnamed_devices)} devices without names',
                'recommendation': 'Use get_port_map() to identify and name devices',
            }
        )

    # Check for single points of failure
    critical_devices = [d for d in devices if d.type == 'gateway']
    if len(critical_devices) == 1:
        issues.append(
            {
                'type': 'single_gateway',
                'severity': 'high',
                'description': 'Single gateway - no redundancy',
                'recommendation': 'Consider gateway redundancy for critical networks',
            }
        )

    # Check for orphaned devices (no uplink but not gateway)
    orphaned = [d for d in devices if not d.connected_to and d.type != 'gateway']
    if orphaned:
        issues.append(
            {
                'type': 'orphaned_devices',
                'severity': 'high',
                'description': f'{len(orphaned)} devices with no uplink connection',
                'recommendation': 'Check physical connections and uplink configuration',
            }
        )

    return issues
