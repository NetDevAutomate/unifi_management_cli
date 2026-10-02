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
"""

from .registry import ToolMetadata, ToolProxy, ToolRegistry
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
