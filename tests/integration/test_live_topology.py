"""Integration tests for topology tools against real UniFi controller."""

import os
import pytest
import sys


# Add src to path for imports
src_path = os.path.join(os.getcwd(), 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from unifi_mcp.utils.errors import ToolError  # noqa: E402


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveTopologyTools:
    """Test topology tools against real controller."""

    async def test_get_network_topology_json(self):
        """Test network topology in JSON format."""
        try:
            from unifi_mcp.tools.topology.network_topology import get_network_topology

            topology = await get_network_topology(include_clients=False, format='json')

            assert isinstance(topology, dict)
            assert 'devices' in topology
            assert 'hierarchy' in topology
            assert 'statistics' in topology
            assert isinstance(topology['devices'], list)
            assert len(topology['devices']) > 0  # Should have at least gateway

            # Check statistics
            stats = topology['statistics']
            assert 'device_counts' in stats
            assert stats['device_counts']['total_infrastructure'] > 0

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_get_network_topology_mermaid(self):
        """Test network topology in Mermaid format."""
        try:
            from unifi_mcp.tools.topology.network_topology import get_network_topology

            mermaid_output = await get_network_topology(include_clients=False, format='mermaid')

            assert isinstance(mermaid_output, str)
            assert 'graph TD' in mermaid_output
            assert '```mermaid' in mermaid_output
            assert '```' in mermaid_output

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_get_device_tree_default(self):
        """Test device tree with default root (gateway)."""
        try:
            from unifi_mcp.tools.topology.device_tree import get_device_tree

            tree = await get_device_tree()

            assert isinstance(tree, dict)
            assert 'root' in tree
            assert 'tree' in tree
            assert 'depth_stats' in tree

            # Root should be gateway
            assert tree['root']['type'] == 'gateway'

            # Tree should have structure
            tree_structure = tree['tree']
            assert 'device' in tree_structure
            assert 'children' in tree_structure

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_get_port_map_all_switches(self):
        """Test port map for all switches."""
        try:
            from unifi_mcp.tools.topology.port_map import get_port_map

            ports = await get_port_map(include_empty=False)

            assert isinstance(ports, list)
            # May be empty if no switches or no active connections
            # Just verify it returns a list without error

            if ports:
                # Check first port structure
                port = ports[0]
                assert hasattr(port, 'port_idx')
                assert hasattr(port, 'enabled')
                assert hasattr(port, 'device_mac')

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            elif e.error_code == 'DEVICE_NOT_FOUND':
                pytest.skip('No switches found on network')
            else:
                raise

    async def test_get_port_map_with_empty_ports(self):
        """Test port map including empty ports."""
        try:
            from unifi_mcp.tools.topology.port_map import get_port_map

            all_ports = await get_port_map(include_empty=True)
            active_ports = await get_port_map(include_empty=False)

            assert isinstance(all_ports, list)
            assert isinstance(active_ports, list)

            # All ports should be >= active ports
            assert len(all_ports) >= len(active_ports)

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            elif e.error_code == 'DEVICE_NOT_FOUND':
                pytest.skip('No switches found on network')
            else:
                raise

    async def test_topology_tools_consistency(self):
        """Test that topology tools return consistent device information."""
        try:
            from unifi_mcp.tools.topology.device_tree import get_device_tree
            from unifi_mcp.tools.topology.network_topology import get_network_topology

            # Get topology and device tree
            topology = await get_network_topology(format='json')
            tree = await get_device_tree()

            # Should have same gateway device
            topology_gateway = next(
                (d for d in topology['devices'] if d['type'] == 'gateway'), None
            )
            tree_gateway = tree['root']

            if topology_gateway:
                assert topology_gateway['mac'] == tree_gateway['mac']
                assert topology_gateway['type'] == tree_gateway['type']

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise
