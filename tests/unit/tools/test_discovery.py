"""Unit tests for discovery tools (simplified for environment)."""

import os
import sys


# Add src to path for imports
src_path = os.path.join(os.getcwd(), 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)


def test_find_device_imports():
    """Test that find_device module can be imported."""
    try:
        # Test import without actually calling the async function
        from unifi_mcp.tools.discovery.find_device import find_device

        assert callable(find_device)
        assert hasattr(find_device, '__name__')
        assert 'find_device' in find_device.__name__
    except ImportError as e:
        assert False, f'Cannot import find_device: {e}'


def test_find_mac_imports():
    """Test that find_mac module can be imported."""
    try:
        from unifi_mcp.tools.discovery.find_mac import find_mac

        assert callable(find_mac)
    except ImportError as e:
        assert False, f'Cannot import find_mac: {e}'


def test_find_ip_imports():
    """Test that find_ip module can be imported."""
    try:
        from unifi_mcp.tools.discovery.find_ip import find_ip

        assert callable(find_ip)
    except ImportError as e:
        assert False, f'Cannot import find_ip: {e}'


def test_client_trace_imports():
    """Test that client_trace module can be imported."""
    try:
        from unifi_mcp.tools.discovery.client_trace import client_trace

        assert callable(client_trace)
    except ImportError as e:
        assert False, f'Cannot import client_trace: {e}'


def test_discovery_init_imports():
    """Test that discovery __init__ imports all tools."""
    try:
        from unifi_mcp.tools.discovery import __all__

        expected_tools = ['client_trace', 'find_device', 'find_ip', 'find_mac']
        assert set(__all__) == set(expected_tools)
    except ImportError as e:
        assert False, f'Cannot import discovery module: {e}'


def test_mac_address_normalization():
    """Test MAC address normalization utility."""
    try:
        from unifi_mcp.tools.discovery.find_mac import _normalize_mac_address

        # Test valid formats
        assert _normalize_mac_address('aa:bb:cc:dd:ee:ff') == 'aa:bb:cc:dd:ee:ff'
        assert _normalize_mac_address('AA:BB:CC:DD:EE:FF') == 'aa:bb:cc:dd:ee:ff'
        assert _normalize_mac_address('aa-bb-cc-dd-ee-ff') == 'aa:bb:cc:dd:ee:ff'
        assert _normalize_mac_address('aabbccddeeff') == 'aa:bb:cc:dd:ee:ff'

        # Test invalid formats
        assert _normalize_mac_address('invalid') is None
        assert _normalize_mac_address('aa:bb:cc:dd') is None  # Too short
        assert _normalize_mac_address('zz:bb:cc:dd:ee:ff') is None  # Invalid chars

    except ImportError as e:
        assert False, f'Cannot import MAC normalization function: {e}'


def test_ipv4_validation():
    """Test IPv4 validation utility."""
    try:
        from unifi_mcp.tools.discovery.find_ip import _is_valid_ipv4

        # Test valid IPs
        assert _is_valid_ipv4('192.168.1.1') is True
        assert _is_valid_ipv4('10.0.0.1') is True
        assert _is_valid_ipv4('172.16.0.1') is True
        assert _is_valid_ipv4('8.8.8.8') is True

        # Test invalid IPs
        assert _is_valid_ipv4('256.1.1.1') is False  # Out of range
        assert _is_valid_ipv4('192.168.1') is False  # Too few octets
        assert _is_valid_ipv4('192.168.1.1.1') is False  # Too many octets
        assert _is_valid_ipv4('not.an.ip.address') is False  # Non-numeric
        assert _is_valid_ipv4('') is False  # Empty string

    except ImportError as e:
        assert False, f'Cannot import IPv4 validation function: {e}'


def test_rfc1918_detection():
    """Test RFC1918 private IP detection."""
    try:
        from unifi_mcp.tools.discovery.find_ip import _is_rfc1918_ip

        # Test private ranges
        assert _is_rfc1918_ip('192.168.1.1') is True
        assert _is_rfc1918_ip('10.0.0.1') is True
        assert _is_rfc1918_ip('172.16.0.1') is True
        assert _is_rfc1918_ip('172.31.255.254') is True

        # Test public IPs
        assert _is_rfc1918_ip('8.8.8.8') is False
        assert _is_rfc1918_ip('1.1.1.1') is False
        assert _is_rfc1918_ip('172.15.0.1') is False  # Just outside private range
        assert _is_rfc1918_ip('172.32.0.1') is False  # Just outside private range

    except ImportError as e:
        assert False, f'Cannot import RFC1918 detection function: {e}'
