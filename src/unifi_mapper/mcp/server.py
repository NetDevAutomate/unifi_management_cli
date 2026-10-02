"""FastMCP server for UniFi Management tools.

Implements the Code Mode architecture pattern with:
- Dynamic tool discovery via search_tools
- Lazy loading of tool definitions
- Progressive disclosure of tool information

Launch it with the ``unifi-mcp`` console script, for example
``uvx --from <path-or-git-url> unifi-mcp`` or after ``uv tool install <path>``.

The server's lifespan resolves its config once (never from a CWD ``.env``), installs
one shared, read-only-guarded controller client that every tool borrows, and points
``sys.stdout`` at stderr so a stray ``print()`` can't corrupt the JSON-RPC stream.
"""

from __future__ import annotations

import anyio
import argparse
import importlib.metadata
import json
import os
import sys
from .config import (
    ConfigFileError,
    ResolvedConfig,
    ServerSettings,
    load_server_settings,
    resolve_mcp_config,
)
from .registry import ToolRegistry
from .runner import ExecuteResult, ToolRunner
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from dataclasses import dataclass
from loguru import logger
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult
from pathlib import Path
from typing import Annotated, Any
from unifi_mapper.core.utils.client import SharedControllerClient, use_shared_controller_client
from unifi_mapper.core.utils.readonly import configure_request_audit


DIST_NAME = 'unifi-management-cli'
REQUEST_AUDIT_ENV = 'UNIFI_MCP_REQUEST_AUDIT'
SHUTDOWN_TIMEOUT_S = 3.0


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


@dataclass(frozen=True)
class AppState:
    """What the lifespan hands to request handlers (``ctx.request_context.lifespan_context``)."""

    config: ResolvedConfig
    shared_client: SharedControllerClient
    settings: ServerSettings


# Set by main() before mcp.run(); the lifespan reads them. None = not given / not loaded.
_config_path: Path | None = None
_settings: ServerSettings | None = None
# The config the running lifespan resolved (the runner names its paths in CONFIG_MISSING).
_active_config: ResolvedConfig | None = None


def current_settings() -> ServerSettings:
    """Return the validated server settings, loading them from the environment once."""
    global _settings
    if _settings is None:
        _settings = load_server_settings()
    return _settings


@asynccontextmanager
async def lifespan(server: FastMCP[Any]) -> AsyncIterator[AppState]:
    """Per-process server state: config, shared guarded client, stdout guard.

    Runs after ``stdio_server()`` has wrapped the real stdout, so redirecting
    ``sys.stdout`` to stderr here leaves the protocol stream untouched while any handler
    ``print()`` goes to stderr. Everything is undone on exit.

    Args:
        server: The FastMCP server (unused).

    Yields:
        The :class:`AppState` for this run.
    """
    global _active_config
    config = resolve_mcp_config(_config_path)
    settings = current_settings()
    shared = SharedControllerClient()
    original_stdout = sys.stdout
    _active_config = config
    with ExitStack() as stack:
        stack.callback(_clear_active_config)
        audit_path = os.environ.get(REQUEST_AUDIT_ENV)
        if audit_path:
            configure_request_audit(Path(audit_path))
            stack.callback(configure_request_audit, None)
        stack.enter_context(use_shared_controller_client(shared))
        sys.stdout = sys.stderr
        try:
            yield AppState(config=config, shared_client=shared, settings=settings)
        finally:
            sys.stdout = original_stdout
            # Bounded and shielded: a slow logout must never hold the process after EOF.
            with anyio.move_on_after(SHUTDOWN_TIMEOUT_S, shield=True):
                await shared.aclose()


def _clear_active_config() -> None:
    """Forget the lifespan's resolved config when the server stops."""
    global _active_config
    _active_config = None


# Initialize the MCP server
mcp = FastMCP('unifi-management', lifespan=lifespan)
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


# One runner per registry object, so monkeypatching get_registry() redirects it.
_runner: ToolRunner | None = None


def get_runner() -> ToolRunner:
    """Return the ToolRunner for the current registry (cached per registry object)."""
    global _runner
    registry = get_registry()
    if _runner is None or _runner.registry is not registry:
        _runner = ToolRunner(registry, settings=current_settings(), config=lambda: _active_config)
    return _runner


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
    results = registry.search(query, category, tags, detail_level)
    if detail_level != 'summary':
        catalog = get_runner().catalog
        for result in results:
            tool = catalog.find(result['name'])
            result['input_schema'] = tool.parameters if tool is not None else None
    return results


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
        Tool metadata including description, parameters, category, and tags, plus the
        JSON ``input_schema`` execute_tool validates against and the ``output_schema``
        (null for mutating, unloadable or untyped tools).
        Returns None if the tool is not found.
    """
    registry = get_registry()
    metadata = registry.get_metadata(tool_name)
    if metadata is None:
        return None
    tool = get_runner().catalog.find(tool_name)

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
        'input_schema': tool.parameters if tool is not None else None,
        'output_schema': tool.output_schema if tool is not None else None,
    }


@mcp.tool()
async def execute_tool(
    tool_name: str, params: dict[str, Any] | None = None
) -> Annotated[CallToolResult, ExecuteResult]:
    """Run a READ-ONLY UniFi tool found via search_tools / get_tool_info.

    Tools whose manifest declares ``mutates: true`` (STP and radio apply/restore) are
    refused: changes go through the CLI's plan -> review -> apply flow, never directly
    from an AI assistant. Arguments are validated against the tool's input_schema
    (see get_tool_info); results and error text are masked for secrets.

    Args:
        tool_name: Name of the tool (e.g. "inspect_switch_port").
        params: Keyword arguments, as listed by get_tool_info (e.g. {"switch": "Office", "port": 5}).

    Returns:
        {"ok": True, "result": ...} on success, or
        {"ok": False, "error_code": ..., "message": ..., "suggestion": ...} on failure
        (with isError set).
    """
    return await get_runner().run(tool_name, params, surface='execute_tool')


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
    parser.add_argument(
        '--config',
        metavar='PATH',
        type=Path,
        help=(
            'env file with controller settings (default: UNIFI_CONFIG, then '
            '$XDG_CONFIG_HOME or ~/.config/unifi_management_cli/{prod,default}.env; '
            'a .env in the working directory is never read)'
        ),
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help=(
            'print where config comes from and which credential families are ready '
            '(key names only), then exit 0 if the controller is configured, else 1. '
            'Never contacts the controller, Keychain or 1Password'
        ),
    )
    return parser


def _configure_logging(level: str) -> None:
    """Send loguru output to stderr only, at ``level`` (stdout carries JSON-RPC)."""
    logger.remove()
    logger.add(sys.stderr, level=level)


def check_report(config: ResolvedConfig) -> dict[str, Any]:
    """Return the ``--check`` JSON: config source and per-family readiness, no values.

    Args:
        config: The resolved configuration.

    Returns:
        A JSON-safe dict naming keys only.
    """
    report = config.to_json_dict()
    controller = report['families'].get('controller')
    if controller is not None and not controller['ready']:
        # --check never runs the Keychain/1Password chain.
        controller['fallback_chain'] = 'not probed'
    report['tool_count'] = len(ToolRegistry())
    return report


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``unifi-mcp`` console script.

    ``--version`` and ``-h/--help`` print to stdout and exit 0 without starting the server.
    ``--check`` prints the resolved config (key names only) and exits 0 if the controller
    is configured, else 1. ``--config PATH`` must name a readable file (else exit 2).
    Unknown arguments are reported on stderr and ignored. Otherwise the stdio server runs.

    Args:
        argv: Arguments to parse; ``None`` means ``sys.argv[1:]``.
    """
    global _config_path, _settings
    args, unknown = _arg_parser().parse_known_args(argv)
    if unknown:
        print(f'unifi-mcp: ignoring unknown arguments: {" ".join(unknown)}', file=sys.stderr)
    settings = load_server_settings()

    explicit: Path | None = args.config
    if explicit is not None:
        explicit = explicit.expanduser()
        if not (explicit.is_file() and os.access(explicit, os.R_OK)):
            print(f'unifi-mcp: --config {explicit} is missing or unreadable', file=sys.stderr)
            sys.exit(2)

    if args.check:
        try:
            config = resolve_mcp_config(explicit)
        except ConfigFileError as e:
            print(f'unifi-mcp: {e}', file=sys.stderr)
            sys.exit(2)
        print(json.dumps(check_report(config), indent=2))
        sys.exit(0 if config.families['controller'].ready else 1)

    _config_path, _settings = explicit, settings
    _configure_logging(settings.log_level)
    mcp.run()


if __name__ == '__main__':
    main()
