"""UniFi Management MCP Server.

This package provides an MCP (Model Context Protocol) server for UniFi network
management tools, implementing the Code Mode architecture pattern.

Features:
    - Dynamic tool discovery via search_tools
    - Lazy loading of tool definitions
    - Progressive disclosure of tool information
    - Network management tools grouped by category, declared in YAML manifests

Usage:
    # Run the MCP server (stdio) without installing it
    uvx --from <path-or-git-url> unifi-mcp

    # Or install it as a tool, then run unifi-mcp
    uv tool install <path>

    # Or programmatically
    from unifi_mapper.mcp import mcp, get_registry, ToolRegistry

Categories:
    - analysis: Network analysis (IP conflicts, STP, VLAN, QoS)
    - connectivity: Firewall, path analysis, traceroute
    - diagnostics: Health, performance, security and switch-port diagnostics
    - discovery: Device/IP/MAC discovery, client tracing and history
    - network: Network control plane (Firewall, ACL, DNS, DPI)
    - observability: Device events and port counter trends
    - protect: UniFi Protect integration (cameras, events, AI)

Surfaces:
    - discovery (default): search_tools, list_categories, get_tool_info, execute_tool
    - direct (``--surface direct`` / ``UNIFI_MCP_TOOL_SURFACE=direct``): those plus every
      read-only, non-pipeline catalog tool

Active probes (issue 092): the tools that run a command on the gateway over SSH (ping,
traceroute, nslookup, the latency matrix) are held back from both surfaces unless the
server starts with ``UNIFI_MCP_ALLOW_ACTIVE_PROBES=1``; ``execute_tool`` refuses them with
``ACTIVE_PROBES_DISABLED`` until then.

The ``server`` names (``mcp``, ``get_registry``, ``search_tools``, ``list_categories``) are
resolved lazily (PEP 562) so that ``python -m unifi_mapper.mcp.server`` does not import
``server`` through this package first, which made runpy warn that the module was already in
``sys.modules`` (issue 020). ``from unifi_mapper.mcp import mcp`` works as before.
"""

from typing import TYPE_CHECKING, Any
from .registry import ToolMetadata, ToolProxy, ToolRegistry


if TYPE_CHECKING:  # the type checker sees the real objects; at runtime __getattr__ loads them
    from .server import get_registry, list_categories, mcp, search_tools

__all__ = [
    'mcp',
    'get_registry',
    'search_tools',
    'list_categories',
    'ToolRegistry',
    'ToolMetadata',
    'ToolProxy',
]

_SERVER_NAMES = frozenset({'mcp', 'get_registry', 'search_tools', 'list_categories'})


def __getattr__(name: str) -> Any:
    """Resolve a ``server`` name on first use (PEP 562)."""
    if name in _SERVER_NAMES:
        from . import server

        return getattr(server, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def __dir__() -> list[str]:
    """List the public names, the lazy ones included."""
    return sorted(set(globals()) | _SERVER_NAMES)
