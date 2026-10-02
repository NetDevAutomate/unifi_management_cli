"""FastMCP server for UniFi Management tools.

Implements the Code Mode architecture pattern with:
- Dynamic tool discovery via search_tools
- Lazy loading of tool definitions
- Progressive disclosure of tool information

Launch it with the ``unifi-mcp`` console script, for example
``uvx --from <path-or-git-url> unifi-mcp`` or after ``uv tool install <path>``.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import sys
from .registry import ToolRegistry
from dataclasses import asdict, is_dataclass
from mcp.server.fastmcp import FastMCP
from typing import Any
from unifi_mapper.core.utils.errors import ToolError


DIST_NAME = 'unifi-management-cli'


def package_version() -> str:
    """Return the installed distribution version, or a sentinel for source trees.

    Returns:
        The version from distribution metadata, or ``'0+unknown'``.
    """
    try:
        return importlib.metadata.version(DIST_NAME)
    except importlib.metadata.PackageNotFoundError:
        return '0+unknown'


def _mcp_sdk_version() -> str:
    """Return the installed ``mcp`` SDK version, or ``'unknown'``."""
    try:
        return importlib.metadata.version('mcp')
    except importlib.metadata.PackageNotFoundError:
        return 'unknown'


def version_string() -> str:
    """Return the ``unifi-mcp --version`` line.

    Returns:
        ``'unifi-mcp (unifi-management-cli <version>; mcp SDK <version>)'``.
    """
    return f'unifi-mcp ({DIST_NAME} {package_version()}; mcp SDK {_mcp_sdk_version()})'


# Initialize the MCP server
mcp = FastMCP('unifi-management')
# FastMCP has no version kwarg; without this, serverInfo.version reports the SDK's version.
mcp._mcp_server.version = package_version()

# Initialize the tool registry
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get or create the tool registry singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


@mcp.tool()
async def search_tools(
    query: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    detail_level: str = 'summary',
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
        'name': metadata.name,
        'description': metadata.description,
        'category': metadata.category,
        'priority': metadata.priority,
        'tags': metadata.tags,
        'parameters': metadata.parameters,
        'module': metadata.module,
        'handler': metadata.handler,
        'mutates': metadata.mutates,
    }


def _to_jsonable(value: Any) -> Any:
    """Convert tool results (pydantic models, dataclasses, nested) to JSON-safe data."""
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    return value


@mcp.tool()
async def execute_tool(tool_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a READ-ONLY UniFi tool found via search_tools / get_tool_info.

    Tools whose manifest declares ``mutates: true`` (STP and radio apply/restore) are
    refused: changes go through the CLI's plan -> review -> apply flow, never directly
    from an AI assistant.

    Args:
        tool_name: Name of the tool (e.g. "inspect_switch_port").
        params: Keyword arguments, as listed by get_tool_info (e.g. {"switch": "Office", "port": 5}).

    Returns:
        {"ok": True, "result": ...} on success, or
        {"ok": False, "error_code": ..., "message": ..., "suggestion": ...} on failure.
    """
    registry = get_registry()
    try:
        result = await registry.execute(tool_name, params)
    except KeyError:
        return {
            'ok': False,
            'error_code': 'TOOL_NOT_FOUND',
            'message': f'No tool named {tool_name!r}',
            'suggestion': 'Use search_tools or list_categories to find the right name.',
        }
    except PermissionError:
        return {
            'ok': False,
            'error_code': 'MUTATION_REFUSED',
            'message': f'{tool_name} changes live controller configuration and is not '
            'executable over MCP.',
            'suggestion': 'Generate a plan with the read-only tools, review it, then apply it '
            'with the unifi-mapper CLI.',
        }
    except ValueError as e:
        meta = registry.get_metadata(tool_name)
        return {
            'ok': False,
            'error_code': 'INVALID_PARAMETERS',
            'message': str(e),
            'suggestion': 'Check get_tool_info for the parameter list.',
            'parameters': meta.parameters if meta else {},
        }
    except ToolError as e:
        return {'ok': False, **e.to_dict()}
    except Exception as e:  # noqa: BLE001 - surface any tool failure to the client, don't crash the server
        return {
            'ok': False,
            'error_code': 'TOOL_FAILED',
            'message': f'{type(e).__name__}: {e}',
            'suggestion': 'Run the equivalent unifi-mapper CLI command for a full traceback.',
        }
    return {'ok': True, 'result': _to_jsonable(result)}


def _arg_parser() -> argparse.ArgumentParser:
    """Build the ``unifi-mcp`` argument parser."""
    parser = argparse.ArgumentParser(
        prog='unifi-mcp',
        description=(
            'UniFi management MCP server. With no arguments it serves the Model Context '
            'Protocol over stdin/stdout for an MCP client.'
        ),
    )
    parser.add_argument('--version', action='version', version=version_string())
    return parser


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``unifi-mcp`` console script.

    ``--version`` and ``-h/--help`` print to stdout and exit 0 without starting the server.
    Unknown arguments are reported on stderr and ignored. Otherwise the stdio server runs.

    Args:
        argv: Arguments to parse; ``None`` means ``sys.argv[1:]``.
    """
    _, unknown = _arg_parser().parse_known_args(argv)
    if unknown:
        print(f'unifi-mcp: ignoring unknown arguments: {" ".join(unknown)}', file=sys.stderr)
    mcp.run()


if __name__ == '__main__':
    main()
