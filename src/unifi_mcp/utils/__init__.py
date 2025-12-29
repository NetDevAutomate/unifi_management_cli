"""Shared utilities for UniFi MCP server."""

# Import only basic utilities to avoid circular dependencies in tests
from unifi_mcp.utils.errors import ErrorCodes, ToolError
from unifi_mcp.utils.logging import configure_logging, get_logger

__all__ = [
    'ErrorCodes',
    'ToolError',
    'configure_logging',
    'get_logger',
]


# Heavy imports (with dependencies) available as lazy imports
def get_credentials():
    """Lazy import for credential chain."""
    from unifi_mcp.utils.auth import get_credentials as _get_credentials

    return _get_credentials()


def get_client():
    """Lazy import for UniFi client."""
    from unifi_mcp.utils.client import UniFiClient

    return UniFiClient
