"""UniFi Management MCP Server.

This package provides an MCP (Model Context Protocol) server for UniFi network
management tools, implementing the Code Mode architecture pattern.

Features:
    - Dynamic tool discovery via search_tools
    - Lazy loading of tool definitions
    - Progressive disclosure of tool information
    - 30+ network management tools across 6 categories

Usage:
    # Run the MCP server
    uvx run unifi-mcp

    # Or programmatically
    from unifi_mapper.mcp import mcp, get_registry, ToolRegistry

Categories:
    - analysis: Network analysis (IP conflicts, STP, VLAN, QoS)
    - diagnostics: Health, performance, security diagnostics
    - discovery: Device/IP/MAC discovery, client tracing
    - connectivity: Firewall, path analysis, traceroute
    - network: Network control plane (Firewall, ACL, DNS, DPI)
    - protect: UniFi Protect integration (cameras, events, AI)
"""

from .registry import ToolMetadata, ToolProxy, ToolRegistry
from .server import get_registry, list_categories, mcp, search_tools

__all__ = [
    "mcp",
    "get_registry",
    "search_tools",
    "list_categories",
    "ToolRegistry",
    "ToolMetadata",
    "ToolProxy",
]
