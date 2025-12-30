"""Basic server tests without complex dependencies."""

import os
import sys

import pytest


# Check if fastmcp is available
try:
    import fastmcp  # noqa: F401
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False


@pytest.mark.skipif(not HAS_FASTMCP, reason='fastmcp not installed')
def test_server_module_exists():
    """Test that server module can be found."""
    # Add src to path
    src_path = os.path.join(os.getcwd(), 'src')
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    # Test import without instantiation
    try:
        import unifi_mcp.server

        assert hasattr(unifi_mcp.server, 'main')
        assert hasattr(unifi_mcp.server, 'create_server')
    except ImportError as e:
        assert False, f'Cannot import server module: {e}'


@pytest.mark.skipif(not HAS_FASTMCP, reason='fastmcp not installed')
def test_resources_exist():
    """Test that resources are available."""
    src_path = os.path.join(os.getcwd(), 'src')
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    try:
        from unifi_mcp.resources import NETWORKING_SPECIALIST_PERSONA

        assert isinstance(NETWORKING_SPECIALIST_PERSONA, str)
        assert len(NETWORKING_SPECIALIST_PERSONA) > 100
        assert 'UniFi Network MCP Server' in NETWORKING_SPECIALIST_PERSONA
    except ImportError as e:
        assert False, f'Cannot import resources: {e}'
