"""Unit tests for topology tools (simplified for environment)."""

import os
import sys


# Add src to path for imports
src_path = os.path.join(os.getcwd(), 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)


def test_topology_tools_import():
    """Test that topology tools can be imported."""
    try:
        from unifi_mcp.tools.topology import __all__

        expected_tools = [
            'discover_lldp_topology',
            'get_device_tree',
            'get_network_topology',
            'get_port_map',
            'trace_network_path',
        ]
        assert set(__all__) == set(expected_tools)
    except ImportError as e:
        assert False, f'Cannot import topology module: {e}'


def test_network_topology_imports():
    """Test network topology tool import."""
    try:
        from unifi_mcp.tools.topology.network_topology import get_network_topology

        assert callable(get_network_topology)
    except ImportError as e:
        assert False, f'Cannot import get_network_topology: {e}'


def test_device_tree_imports():
    """Test device tree tool import."""
    try:
        from unifi_mcp.tools.topology.device_tree import get_device_tree

        assert callable(get_device_tree)
    except ImportError as e:
        assert False, f'Cannot import get_device_tree: {e}'


def test_port_map_imports():
    """Test port map tool import."""
    try:
        from unifi_mcp.tools.topology.port_map import get_port_map

        assert callable(get_port_map)
    except ImportError as e:
        assert False, f'Cannot import get_port_map: {e}'


def test_device_type_mapping():
    """Test UniFi device type mapping utility."""
    try:
        from unifi_mcp.tools.topology.network_topology import _map_device_type

        # Test known mappings
        assert _map_device_type('usw') == 'switch'
        assert _map_device_type('uap') == 'ap'
        assert _map_device_type('ugw') == 'gateway'
        assert _map_device_type('udm') == 'gateway'
        assert _map_device_type('uxg') == 'gateway'

        # Test unknown type (should default to switch)
        assert _map_device_type('unknown') == 'switch'
        assert _map_device_type('') == 'switch'

    except ImportError as e:
        assert False, f'Cannot import device type mapping: {e}'
