"""LLDP-based network topology discovery tool."""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Annotated, Any
from unifi_mcp.models import NetworkPath, PathHop
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


class LLDPNeighbor(BaseModel):
    """LLDP neighbor information."""

    local_device_id: str = Field(description='Local device ID')
    local_device_name: str = Field(description='Local device name')
    local_port: int = Field(description='Local port index')
    local_port_name: str = Field(description='Local port name')
    remote_device_id: str | None = Field(description='Remote UniFi device ID if known')
    remote_device_name: str | None = Field(description='Remote device name')
    remote_port_name: str = Field(description='Remote port identifier')
    chassis_id: str = Field(description='LLDP chassis ID (usually MAC address)')
    is_unifi_device: bool = Field(description='Whether remote device is a UniFi device')


class LLDPTopologyReport(BaseModel):
    """Comprehensive LLDP topology discovery report."""

    timestamp: str = Field(description='When the discovery was performed')
    total_switches: int = Field(description='Total switches discovered')
    total_connections: int = Field(description='Total inter-switch connections')
    lldp_neighbors: list[LLDPNeighbor] = Field(description='All LLDP neighbor relationships')
    unifi_connections: int = Field(description='Connections between UniFi devices')
    external_connections: int = Field(description='Connections to non-UniFi devices')
    potential_loops: list[str] = Field(description='Detected potential loop paths')
    isolated_switches: list[str] = Field(description='Switches with no detected uplinks')


async def discover_lldp_topology() -> LLDPTopologyReport:
    """Discover network topology using LLDP (Link Layer Discovery Protocol) data.

    When to use this tool:
    - To understand physical layer connectivity between switches
    - To verify cable connections and port mappings
    - To detect non-UniFi devices connected to UniFi switches
    - To identify potential network loops or isolated switches
    - Before configuring port mirroring to understand traffic paths

    How LLDP discovery works:
    - LLDP is a vendor-neutral protocol for network device discovery
    - Switches exchange LLDP packets to learn about directly connected neighbors
    - This provides authoritative physical layer topology (not just logical)
    - UniFi switches store LLDP neighbor data accessible via API

    Common workflow:
    1. discover_lldp_topology() - get physical connectivity map
    2. trace_network_path() - trace path between specific devices
    3. get_mirror_capabilities() - plan traffic capture points
    4. create_mirror_session() - capture traffic at strategic points

    What to do next:
    - If isolated_switches found: Check cable connections and switch status
    - If potential_loops found: Review STP configuration
    - If external_connections found: Document non-UniFi infrastructure
    - Use results to plan port mirroring for troubleshooting

    Returns:
        LLDPTopologyReport with comprehensive LLDP neighbor data

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            # Use the client's built-in LLDP topology discovery
            topology = await client.get_network_topology()

            # Process the raw topology data
            connections = topology.get('connections', [])
            _devices = topology.get('devices', [])  # Reserved for future use  # noqa: F841
            switches = topology.get('switches', [])

            # Build LLDP neighbors list
            lldp_neighbors: list[LLDPNeighbor] = []
            for conn in connections:
                neighbor = LLDPNeighbor(
                    local_device_id=conn.get('local_device_id', ''),
                    local_device_name=conn.get('local_device_name', 'Unknown'),
                    local_port=conn.get('local_port', 0),
                    local_port_name=conn.get('local_port_name', ''),
                    remote_device_id=conn.get('remote_device_id'),
                    remote_device_name=conn.get('remote_device_name'),
                    remote_port_name=conn.get('remote_port_name', ''),
                    chassis_id=conn.get('chassis_id', ''),
                    is_unifi_device=conn.get('is_unifi_device', False),
                )
                lldp_neighbors.append(neighbor)

            # Calculate statistics
            unifi_connections = len([n for n in lldp_neighbors if n.is_unifi_device])
            external_connections = len(lldp_neighbors) - unifi_connections

            # Detect potential loops (switches connected in cycles)
            potential_loops = _detect_potential_loops(lldp_neighbors)

            # Find isolated switches (no LLDP neighbors)
            connected_switch_ids = set()
            for neighbor in lldp_neighbors:
                connected_switch_ids.add(neighbor.local_device_id)
                if neighbor.remote_device_id:
                    connected_switch_ids.add(neighbor.remote_device_id)

            isolated_switches = [
                s.get('name', s.get('mac', 'Unknown'))
                for s in switches
                if s.get('id') not in connected_switch_ids
            ]

            return LLDPTopologyReport(
                timestamp=datetime.now().isoformat(),
                total_switches=len(switches),
                total_connections=len(lldp_neighbors),
                lldp_neighbors=lldp_neighbors,
                unifi_connections=unifi_connections,
                external_connections=external_connections,
                potential_loops=potential_loops,
                isolated_switches=isolated_switches,
            )

        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
                )
            raise ToolError(
                message=f'Error discovering LLDP topology: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _detect_potential_loops(neighbors: list[LLDPNeighbor]) -> list[str]:
    """Detect potential network loops based on LLDP neighbor relationships."""
    loops: list[str] = []

    # Build adjacency map
    adjacency: dict[str, set[str]] = {}
    for neighbor in neighbors:
        if not neighbor.remote_device_id:
            continue
        if neighbor.local_device_id not in adjacency:
            adjacency[neighbor.local_device_id] = set()
        adjacency[neighbor.local_device_id].add(neighbor.remote_device_id)

    # Simple loop detection: check for bidirectional connections with multiple paths
    # A true loop would show multiple distinct paths between same pair of switches
    visited_pairs: set[tuple[str, str]] = set()

    for device_id, connected_to in adjacency.items():
        for connected_device in connected_to:
            pair = tuple(sorted([device_id, connected_device]))
            if pair in visited_pairs:
                continue
            visited_pairs.add(pair)

            # Check if there are multiple connection paths
            if device_id in adjacency.get(connected_device, set()):
                # Bidirectional connection is normal, but check for multi-path
                local_connections = sum(
                    1
                    for n in neighbors
                    if n.local_device_id == device_id and n.remote_device_id == connected_device
                )
                if local_connections > 1:
                    loops.append(
                        f'Multiple connections between {device_id[:8]} and {connected_device[:8]}'
                    )

    return loops


async def trace_network_path(
    source_device_id: Annotated[str, Field(description='Source device ID or MAC')],
    destination_device_id: Annotated[str, Field(description='Destination device ID or MAC')],
) -> NetworkPath:
    """Trace the network path between two devices using LLDP topology data.

    When to use this tool:
    - To understand the exact path traffic takes between two devices
    - When troubleshooting connectivity or latency issues
    - To identify all switches in a traffic path for monitoring
    - Before setting up distributed port mirroring across multiple switches

    Forbidden actions:
    - Do not assume path without tracing - topology may be complex
    - Do not bypass this for multi-switch environments

    Common workflow:
    1. find_device() to get source and destination IDs
    2. trace_network_path() to understand the path
    3. get_mirror_capabilities() for each switch in path
    4. create_mirror_session() at strategic points

    What to do next:
    - If path found: Review each hop for potential monitoring points
    - If no path found: Devices may be on different isolated networks
    - For monitoring: Set up mirror sessions on critical path switches

    Args:
        source_device_id: Source device ID or MAC address
        destination_device_id: Destination device ID or MAC address

    Returns:
        NetworkPath with list of hops between source and destination

    Raises:
        ToolError: DEVICE_NOT_FOUND if source or destination not found
        ToolError: NO_PATH_FOUND if no path exists between devices
    """
    async with UniFiClient() as client:
        try:
            topology = await client.get_network_topology()
            devices = topology.get('devices', [])
            connections = topology.get('connections', [])

            # Normalize IDs (remove colons, lowercase)
            def normalize_id(id_str: str) -> str:
                return id_str.lower().replace(':', '')

            source_normalized = normalize_id(source_device_id)
            dest_normalized = normalize_id(destination_device_id)

            # Find source and destination devices
            source_device = None
            dest_device = None

            for device in devices:
                device_id_norm = normalize_id(device.get('id', ''))
                device_mac_norm = normalize_id(device.get('mac', ''))

                if source_normalized in (device_id_norm, device_mac_norm):
                    source_device = device
                if dest_normalized in (device_id_norm, device_mac_norm):
                    dest_device = device

            if not source_device:
                raise ToolError(
                    message=f'Source device {source_device_id} not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Use find_device to search for the correct device ID',
                    related_tools=['find_device', 'discover_lldp_topology'],
                )

            if not dest_device:
                raise ToolError(
                    message=f'Destination device {destination_device_id} not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Use find_device to search for the correct device ID',
                    related_tools=['find_device', 'discover_lldp_topology'],
                )

            # Build adjacency graph for path finding
            adjacency = _build_adjacency_graph(connections)

            # Find path using BFS
            path = _find_path_bfs(
                normalize_id(source_device.get('id', '')),
                normalize_id(dest_device.get('id', '')),
                adjacency,
            )

            if not path:
                # Try reverse direction
                path = _find_path_bfs(
                    normalize_id(dest_device.get('id', '')),
                    normalize_id(source_device.get('id', '')),
                    adjacency,
                )
                if path:
                    path.reverse()

            if not path:
                raise ToolError(
                    message=f'No path found between {source_device.get("name")} and {dest_device.get("name")}',
                    error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                    suggestion='Devices may be on isolated network segments',
                    related_tools=['discover_lldp_topology', 'get_network_topology'],
                )

            # Build NetworkPath with hops
            hops: list[PathHop] = []
            device_lookup = {normalize_id(d.get('id', '')): d for d in devices}

            for i, device_id in enumerate(path):
                device = device_lookup.get(device_id, {})

                # Find port information from connections
                ingress_port = None
                egress_port = None

                if i > 0:
                    # Find connection from previous device
                    prev_id = path[i - 1]
                    for conn in connections:
                        if normalize_id(conn.get('local_device_id', '')) == prev_id:
                            if normalize_id(conn.get('remote_device_id', '') or '') == device_id:
                                ingress_port = conn.get('remote_port_name', '')
                                break

                if i < len(path) - 1:
                    # Find connection to next device
                    next_id = path[i + 1]
                    for conn in connections:
                        if normalize_id(conn.get('local_device_id', '')) == device_id:
                            if normalize_id(conn.get('remote_device_id', '') or '') == next_id:
                                egress_port = str(conn.get('local_port', ''))
                                break

                hop = PathHop(
                    device_id=device.get('id', device_id),
                    device_name=device.get('name', 'Unknown'),
                    device_type=device.get('type', 'unknown'),
                    ingress_port=ingress_port,
                    egress_port=egress_port,
                    hop_number=i + 1,
                )
                hops.append(hop)

            return NetworkPath(
                source_device=source_device.get('name', source_device_id),
                destination_device=dest_device.get('name', destination_device_id),
                hops=hops,
                total_hops=len(hops),
                path_found=True,
            )

        except ToolError:
            raise
        except Exception as e:
            raise ToolError(
                message=f'Error tracing network path: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check device IDs and try again',
            )


def _build_adjacency_graph(connections: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Build adjacency graph from connections."""
    adjacency: dict[str, set[str]] = {}

    def normalize_id(id_str: str) -> str:
        return id_str.lower().replace(':', '') if id_str else ''

    for conn in connections:
        local_id = normalize_id(conn.get('local_device_id', ''))
        remote_id = normalize_id(conn.get('remote_device_id', '') or '')

        if not local_id or not remote_id:
            continue

        if local_id not in adjacency:
            adjacency[local_id] = set()
        if remote_id not in adjacency:
            adjacency[remote_id] = set()

        adjacency[local_id].add(remote_id)
        adjacency[remote_id].add(local_id)  # Bidirectional

    return adjacency


def _find_path_bfs(
    source: str, destination: str, adjacency: dict[str, set[str]]
) -> list[str] | None:
    """Find path between source and destination using BFS."""
    if source == destination:
        return [source]

    if source not in adjacency:
        return None

    visited = {source}
    queue = [[source]]

    while queue:
        path = queue.pop(0)
        current = path[-1]

        for neighbor in adjacency.get(current, set()):
            if neighbor in visited:
                continue

            new_path = path + [neighbor]

            if neighbor == destination:
                return new_path

            visited.add(neighbor)
            queue.append(new_path)

    return None
