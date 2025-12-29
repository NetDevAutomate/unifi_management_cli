"""Unit tests for connectivity tools (simplified for environment)."""

import os
import sys


# Add src to path for imports
src_path = os.path.join(os.getcwd(), 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)


def test_connectivity_tools_import():
    """Test that connectivity tools can be imported."""
    try:
        from unifi_mcp.tools.connectivity import __all__

        expected_tools = ['firewall_check', 'path_analysis', 'traceroute']
        assert set(__all__) == set(expected_tools)
    except ImportError as e:
        assert False, f'Cannot import connectivity module: {e}'


def test_traceroute_imports():
    """Test traceroute tool import."""
    try:
        from unifi_mcp.tools.connectivity.traceroute import traceroute

        assert callable(traceroute)
    except ImportError as e:
        assert False, f'Cannot import traceroute: {e}'


def test_firewall_check_imports():
    """Test firewall check tool import."""
    try:
        from unifi_mcp.tools.connectivity.firewall_check import firewall_check

        assert callable(firewall_check)
    except ImportError as e:
        assert False, f'Cannot import firewall_check: {e}'


def test_path_analysis_imports():
    """Test path analysis tool import."""
    try:
        from unifi_mcp.tools.connectivity.path_analysis import path_analysis

        assert callable(path_analysis)
    except ImportError as e:
        assert False, f'Cannot import path_analysis: {e}'


def test_endpoint_resolution_helpers():
    """Test endpoint resolution helper functions."""
    try:
        # These functions help resolve different endpoint formats
        from unifi_mcp.tools.connectivity.traceroute import (
            _search_endpoint_in_devices,
        )

        # Mock device data for testing
        mock_device = {
            'mac': 'aa:bb:cc:dd:ee:ff',
            'name': 'Test Switch',
            'ip': '192.168.1.10',
            'hostname': 'switch1',
        }

        # Test device search
        result = _search_endpoint_in_devices('192.168.1.10', [mock_device])
        assert result == mock_device

        result = _search_endpoint_in_devices('aa:bb:cc:dd:ee:ff', [mock_device])
        assert result == mock_device

        result = _search_endpoint_in_devices('test switch', [mock_device])
        assert result == mock_device

        # Test not found
        result = _search_endpoint_in_devices('not-found', [mock_device])
        assert result is None

    except ImportError as e:
        assert False, f'Cannot import endpoint resolution helpers: {e}'


def test_firewall_rule_matching_helpers():
    """Test firewall rule matching utilities."""
    try:
        # Test with mock firewall rules
        from unifi_mcp.models.firewall import FirewallRule
        from unifi_mcp.tools.connectivity.firewall_check import _determine_verdict

        # Test allow verdict
        allow_rule = FirewallRule(
            id='test1',
            name='Allow All',
            action='allow',
            order=100,
        )
        verdict = _determine_verdict([allow_rule])
        assert verdict == 'allow'

        # Test deny verdict
        deny_rule = FirewallRule(
            id='test2',
            name='Block Traffic',
            action='deny',
            order=50,
        )
        verdict = _determine_verdict([deny_rule])
        assert verdict == 'deny'

        # Test empty rules (default allow)
        verdict = _determine_verdict([])
        assert verdict == 'allow'

    except ImportError as e:
        assert False, f'Cannot import firewall utilities: {e}'
