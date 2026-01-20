"""FastMCP server for UniFi Management tools.

Implements the Code Mode architecture pattern with:
- Dynamic tool discovery via search_tools
- Lazy loading of tool definitions
- Progressive disclosure of tool information
"""

from __future__ import annotations

from .registry import ToolRegistry
from mcp.server.fastmcp import FastMCP
from pathlib import Path
from typing import Any


# Initialize the MCP server
mcp = FastMCP("unifi-management")

# Initialize the tool registry
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get or create the tool registry singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry(Path(__file__).parent / "manifests")
    return _registry


@mcp.tool()
async def search_tools(
    query: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    detail_level: str = "summary",
) -> list[dict[str, Any]]:
    """Search available UniFi management tools.

    Use this to discover tools before executing them. This is the primary
    entry point for the Code Mode pattern - agents should search for relevant
    tools first, then execute specific tools as needed.

    Args:
        query: Text search in tool names and descriptions
        category: Filter by category (analysis, diagnostics, discovery,
                  connectivity, network, protect)
        tags: Filter by tags (e.g., ["ip", "vlan", "stp"])
        detail_level: "summary" (name + description) or "full" (includes parameters)

    Returns:
        List of matching tools with requested detail level

    Example:
        # Find all IP-related tools
        search_tools(query="ip")

        # Find analysis tools with full details
        search_tools(category="analysis", detail_level="full")

        # Find tools by tags
        search_tools(tags=["vlan", "layer2"])
    """
    registry = get_registry()
    return registry.search(query, category, tags, detail_level)


@mcp.tool()
async def list_categories() -> dict[str, list[str]]:
    """List all tool categories and their tools.

    Returns a dictionary mapping category names to lists of tool names.
    Use this to get an overview of available tool groups.

    Categories:
        - analysis: Network analysis tools (IP conflicts, STP, VLAN, QoS)
        - diagnostics: Health, performance, security diagnostics
        - discovery: Device/IP/MAC discovery and client tracing
        - connectivity: Firewall, path analysis, traceroute
        - network: Network control plane (Firewall, ACL, DNS, DPI)
        - protect: UniFi Protect integration (cameras, events, AI)

    Returns:
        Dictionary mapping category names to tool lists
    """
    registry = get_registry()
    return registry.get_categories()


@mcp.tool()
async def get_tool_info(tool_name: str) -> dict[str, Any] | None:
    """Get detailed information about a specific tool.

    Args:
        tool_name: The name of the tool to look up

    Returns:
        Tool metadata including description, parameters, category, and tags.
        Returns None if the tool is not found.
    """
    registry = get_registry()
    metadata = registry.get_metadata(tool_name)
    if metadata is None:
        return None

    return {
        "name": metadata.name,
        "description": metadata.description,
        "category": metadata.category,
        "priority": metadata.priority,
        "tags": metadata.tags,
        "parameters": metadata.parameters,
        "module": metadata.module,
        "handler": metadata.handler,
    }


def main() -> None:
    """Entry point for uvx run unifi-mcp."""
    mcp.run()


if __name__ == "__main__":
    main()
