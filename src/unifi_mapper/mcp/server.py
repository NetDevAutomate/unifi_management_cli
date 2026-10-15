"""FastMCP server for UniFi Management tools.

Implements the Code Mode architecture pattern with:
- Dynamic tool discovery via search_tools
- Lazy loading of tool definitions
- Progressive disclosure of tool information

Tool categories: analysis, connectivity, diagnostics, discovery, network, observability
and protect. Every catalog tool is read-only over MCP; tools that change the controller
are refused and go through the ``unifi-mapper`` CLI's plan -> review -> apply flow.

Two tool surfaces: ``discovery`` (the default) lists the four meta-tools
``search_tools``, ``list_categories``, ``get_tool_info`` and ``execute_tool``;
``direct`` (``--surface direct`` or ``UNIFI_MCP_TOOL_SURFACE=direct``) also lists every
non-mutating, non-pipeline catalog tool. Both run catalog tools through one ToolRunner.

The gateway SSH probes (``active_probe: true`` in the manifests, issue 092) are held back
from both surfaces and refused with ``ACTIVE_PROBES_DISABLED`` unless the server starts with
``UNIFI_MCP_ALLOW_ACTIVE_PROBES=1``, read once at start like ``UNIFI_MCP_TOOL_SURFACE``.

Launch it with the ``unifi-mcp`` console script, for example
``uvx --from <path-or-git-url> unifi-mcp`` or after ``uv tool install <path>``.

The server's lifespan resolves its config once (never from a CWD ``.env``), installs
one shared, read-only-guarded controller client that every tool borrows, and points
``sys.stdout`` at stderr so a stray ``print()`` can't corrupt the JSON-RPC stream.
"""

from __future__ import annotations

import anyio
import anyio.to_thread
import argparse
import functools
import importlib.metadata
import json
import os
import re
import sys
import time
from .call_audit import CallAuditLog, env_switch
from .catalog import ToolCatalog, annotations_for
from .config import (
    ACTIVE_PROBES_ENV,
    ActiveProbesSettingError,
    ConfigFileError,
    ResolvedConfig,
    ServerSettings,
    active_probes_allowed,
    load_server_settings,
    resolve_mcp_config,
)
from .registry import ToolMetadata, ToolRegistry
from .runner import ERRORS_SET_IS_ERROR, ExecuteResult, ToolRunner, envelope_text, error_envelope
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from dataclasses import dataclass
from loguru import logger
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from mcp.types import Tool as MCPTool
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from unifi_mapper.core.utils.client import SharedControllerClient, use_shared_controller_client
from unifi_mapper.core.utils.readonly import configure_request_audit
from unifi_mapper.diagnostics import port_diagnostics_tools as _sync_tools


DIST_NAME = 'unifi-management-cli'
SERVER_NAME = 'unifi-management'
REQUEST_AUDIT_ENV = 'UNIFI_MCP_REQUEST_AUDIT'
SURFACE_ENV = 'UNIFI_MCP_TOOL_SURFACE'
SHUTDOWN_TIMEOUT_S = 3.0
# execute_tool's refusal of an active probe while UNIFI_MCP_ALLOW_ACTIVE_PROBES is not 1.
ACTIVE_PROBES_DISABLED = 'ACTIVE_PROBES_DISABLED'
# An active probe's description begins "Runs <command> on the gateway over SSH: " (issue 092).
PROBE_DESCRIPTION = re.compile(r'Runs (?P<command>\S+) on the gateway over SSH: ')

Surface = Literal['discovery', 'direct']
SURFACES: tuple[Surface, ...] = ('discovery', 'direct')
# Plan decision P2 (design D2): discovery stays the default; direct is opt-in.
DEFAULT_SURFACE: Surface = 'discovery'


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
    log_active_probes(get_registry())
    shared = SharedControllerClient()
    original_stdout = sys.stdout
    _active_config = config
    with ExitStack() as stack:
        stack.callback(_clear_active_config)
        call_audit = get_runner().call_audit
        if call_audit is not None:
            stack.callback(call_audit.flush)
        _configure_request_audit(stack, call_audit)
        stack.enter_context(use_shared_controller_client(shared))
        sys.stdout = sys.stderr
        try:
            yield AppState(config=config, shared_client=shared, settings=settings)
        finally:
            sys.stdout = original_stdout
            # Bounded and shielded: a slow logout must never hold the process after EOF.
            with anyio.move_on_after(SHUTDOWN_TIMEOUT_S, shield=True):
                await shared.aclose()
            # The sync tools' shared session (issue 021): wait for its workers, then log out.
            with anyio.move_on_after(SHUTDOWN_TIMEOUT_S, shield=True):
                await anyio.to_thread.run_sync(
                    functools.partial(
                        _sync_tools.shutdown_shared_sync_session, timeout=SHUTDOWN_TIMEOUT_S
                    ),
                    abandon_on_cancel=True,
                )


def _configure_request_audit(stack: ExitStack, call_audit: CallAuditLog | None) -> None:
    """Point the guards' request audit where ``UNIFI_MCP_REQUEST_AUDIT`` says, until exit.

    Unset, empty, ``default`` or the ``off`` family: no request lines (never a file named
    ``off`` or ``default``). The ``on`` family: request lines in the call log (one warning,
    and none, when the call log is off). Anything else: a path to a separate file, as
    before.
    """
    raw = os.environ.get(REQUEST_AUDIT_ENV)
    switch = env_switch(raw)
    if raw is None or not raw.strip() or raw.strip().casefold() == 'default' or switch == 'off':
        return
    if switch == 'on':
        if call_audit is None or not call_audit.enabled:
            logger.warning(
                '{}=on writes request lines into the MCP call log, which is off; none written',
                REQUEST_AUDIT_ENV,
            )
            return
        configure_request_audit(sink=call_audit.note_request)
    else:
        configure_request_audit(Path(raw.strip()))
    stack.callback(configure_request_audit, None)


def _clear_active_config() -> None:
    """Forget the lifespan's resolved config when the server stops."""
    global _active_config
    _active_config = None


# Initialize the tool registry
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get or create the tool registry singleton.

    It registers the active probes only when ``UNIFI_MCP_ALLOW_ACTIVE_PROBES`` is ``1``
    (issue 092): from the loaded settings when ``main()`` has set them, else from the
    environment, where an invalid value counts as off (``main()`` refuses to start on one).
    """
    global _registry
    if _registry is None:
        allowed = _settings.active_probes if _settings is not None else active_probes_allowed()
        _registry = ToolRegistry(active_probes=allowed)
    return _registry


def probe_command(meta: ToolMetadata) -> str:
    """Return the program an active probe runs on the gateway, from its description.

    Args:
        meta: An ``active_probe`` tool's metadata.

    Returns:
        E.g. ``'ping'``; ``'a command'`` for a description not in the shape issue 092 sets.
    """
    match = PROBE_DESCRIPTION.match(meta.description)
    return match['command'] if match else 'a command'


def log_active_probes(registry: ToolRegistry) -> None:
    """Log, once at start, what the active-probe gate holds back or lets through.

    Held back (the default): one INFO line with the count and the variable that lists them.
    Listed: one WARNING, since each listed probe runs a command on the gateway over SSH.

    Args:
        registry: The server's registry.
    """
    held = registry.held_active_probes()
    if held:
        logger.info(
            '{} active-probe tools held back ({}); set {}=1 to list them',
            len(held),
            ', '.join(sorted(held)),
            ACTIVE_PROBES_ENV,
        )
        return
    listed = sorted(
        name
        for names in registry.get_categories().values()
        for name in names
        if (meta := registry.get_metadata(name)) is not None and meta.active_probe
    )
    if listed:
        logger.warning(
            '{}=1: {} active-probe tools listed ({}); each runs a command on the gateway '
            'over SSH as UNIFI_SSH_USERNAME',
            ACTIVE_PROBES_ENV,
            len(listed),
            ', '.join(listed),
        )


def active_probes_disabled(meta: ToolMetadata) -> tuple[str, str]:
    """Return the ``ACTIVE_PROBES_DISABLED`` message and suggestion for a held probe.

    Args:
        meta: The held tool's metadata.

    Returns:
        ``(message, suggestion)``: the variable and the command the tool would run, then how
        to turn it on or run the probe at a terminal instead.
    """
    message = (
        f'{meta.name} runs {probe_command(meta)} on the gateway over SSH; active probes are '
        f'off ({ACTIVE_PROBES_ENV} is not 1)'
    )
    instead = f', or run `unifi-mapper {meta.cli}` at a terminal' if meta.cli else ''
    suggestion = (
        f'Start the MCP server with {ACTIVE_PROBES_ENV}=1 to allow gateway probes{instead}.'
    )
    return message, suggestion


async def refuse_held_probe(
    name: str, params: dict[str, Any] | None, surface: Literal['execute_tool', 'direct']
) -> CallToolResult | None:
    """Refuse a call to an active probe the registry holds back; None for any other tool.

    The refusal is written to the call log like any other outcome, before anything is
    validated, gated or run: nothing reads the arguments, the credentials or the gateway.

    Args:
        name: The tool the call named.
        params: The call's arguments (only their keys are logged).
        surface: ``execute_tool`` (the JSON envelope) or ``direct`` (one error text).

    Returns:
        The refusal, or None when ``name`` is not a held probe.
    """
    meta = get_registry().held_active_probes().get(name)
    if meta is None:
        return None
    started = time.monotonic()
    message, suggestion = active_probes_disabled(meta)
    if surface == 'execute_tool':
        envelope = error_envelope(ACTIVE_PROBES_DISABLED, message, suggestion)
        result = CallToolResult(
            content=[TextContent(type='text', text=envelope_text(envelope))],
            structuredContent=envelope,
            isError=ERRORS_SET_IS_ERROR,
        )
    else:
        text = f'[{ACTIVE_PROBES_DISABLED}] {message} — {suggestion}'
        result = CallToolResult(content=[TextContent(type='text', text=text)], isError=True)
    audit = get_runner().call_audit
    if audit is not None and audit.enabled:
        record = functools.partial(
            audit.record,
            tool=name,
            registered=True,  # a manifest name, not client text
            surface=surface,
            arg_keys=list(params or {}),
            known_keys=frozenset(meta.parameters),
            duration_ms=(time.monotonic() - started) * 1000,
            outcome=ACTIVE_PROBES_DISABLED,
        )
        try:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(record)
        except Exception:  # noqa: BLE001 - logging a call never changes its result
            logger.warning('MCP call log: the line for {} was not written', name)
    return result


# One runner per registry object, so monkeypatching get_registry() redirects it.
_runner: ToolRunner | None = None


def get_runner() -> ToolRunner:
    """Return the ToolRunner for the current registry (cached per registry object)."""
    global _runner
    registry = get_registry()
    if _runner is None or _runner.registry is not registry:
        settings = current_settings()
        _runner = ToolRunner(
            registry,
            settings=settings,
            config=lambda: _active_config,
            call_audit=CallAuditLog(settings.call_audit),
        )
    return _runner


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
        query: Words to find, e.g. "port vlan" or "link speed"; every word must appear in
            a tool's name, description or tags (case-insensitive). Results are ranked by
            where the words hit: name, then tags, then description.
        category: Filter by category (analysis, connectivity, diagnostics,
                  discovery, network, observability, protect; any case)
        tags: Filter by tags (e.g., ["ip", "vlan", "stp"])
        detail_level: "summary" (name + description; a tool that changes the controller
            carries mutates: true and is refused by execute_tool) or "full" (includes
            parameters)

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


async def list_categories() -> dict[str, list[str]]:
    """List all tool categories and their tools.

    Returns a dictionary mapping category names to lists of tool names.
    Use this to get an overview of available tool groups.

    Categories:
        - analysis: Network analysis tools (IP conflicts, STP, VLAN, QoS)
        - connectivity: Firewall, path analysis, traceroute
        - diagnostics: Health, performance, security and switch-port diagnostics
        - discovery: Device/IP/MAC discovery, client tracing and history
        - network: Network control plane (Firewall, ACL, DNS, DPI)
        - observability: Device events and port counter trends
        - protect: UniFi Protect integration (cameras, events, AI)

    Returns:
        Dictionary mapping category names to tool lists
    """
    registry = get_registry()
    return registry.get_categories()


async def get_tool_info(tool_name: str) -> dict[str, Any] | None:
    """Get detailed information about a specific tool.

    Args:
        tool_name: The name of the tool to look up

    Returns:
        Tool metadata including description, parameters, category, and tags, plus the
        JSON ``input_schema`` execute_tool validates against, the ``output_schema``
        (null for mutating, unloadable or untyped tools) and the MCP ``annotations``
        (null for mutating tools).
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
        'annotations': (
            None
            if metadata.mutates
            else annotations_for(metadata).model_dump(mode='json', exclude_none=True)
        ),
    }


async def execute_tool(
    tool_name: str, params: dict[str, Any] | None = None
) -> Annotated[CallToolResult, ExecuteResult]:
    """Run a READ-ONLY UniFi tool found via search_tools / get_tool_info.

    Tools whose manifest declares ``mutates: true`` (STP and radio apply/restore) are
    refused: changes go through the CLI's plan -> review -> apply flow, never directly
    from an AI assistant. The gateway SSH probes are refused with ACTIVE_PROBES_DISABLED
    unless the server was started with UNIFI_MCP_ALLOW_ACTIVE_PROBES=1. Arguments are
    validated against the tool's input_schema (see get_tool_info); results and error text
    are masked for secrets.

    Args:
        tool_name: Name of the tool (e.g. "inspect_switch_port").
        params: Keyword arguments, as listed by get_tool_info (e.g.
            {"switch": "Switch A", "port": 5}).

    Returns:
        {"ok": True, "result": ...} on success, or
        {"ok": False, "error_code": ..., "message": ..., "suggestion": ...} on failure
        (with isError set).
    """
    refused = await refuse_held_probe(tool_name, params, 'execute_tool')
    if refused is not None:
        return refused
    return await get_runner().run(tool_name, params, surface='execute_tool')


# --- server assembly (design §2.4, §2.6, §2.7, §2.10) --------------------------------

# Fixed annotations for the meta-tools. execute_tool can reach writes_local tools
# (snapshot_radio_config), so it can't claim readOnlyHint.
META_TOOLS: dict[str, tuple[Any, ToolAnnotations]] = {
    'search_tools': (
        search_tools,
        ToolAnnotations(
            title='Search Tools',
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    ),
    'list_categories': (
        list_categories,
        ToolAnnotations(
            title='List Categories',
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    ),
    'get_tool_info': (
        get_tool_info,
        ToolAnnotations(
            title='Get Tool Info',
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    ),
    'execute_tool': (
        execute_tool,
        ToolAnnotations(
            title='Execute Tool',
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    ),
}

CATEGORY_SUMMARY = (
    'analysis (IP conflicts, STP, VLAN, QoS, MTU, PoE, Wi-Fi radio), connectivity '
    '(firewall, path analysis, traceroute, inter-VLAN routing), diagnostics (health, '
    'performance, security, switch-port inspection), discovery (device, IP, MAC, client '
    'tracing and history), network (firewall zones and policies, ACL, DNS, clients, '
    'networks via the Network Integration API), observability (device events, port '
    'counter trends) and protect (UniFi Protect cameras, NVR, sensors)'
)


def build_instructions(registry: ToolRegistry) -> str:
    """Return the server ``instructions``: one paragraph naming only registered tools.

    Args:
        registry: The tool registry.

    Returns:
        The instructions text.
    """
    link_tools = [n for n in ('inspect_switch_port', 'audit_link_speeds') if n in registry]
    parts = [
        'Read-only UniFi Network and Protect troubleshooting for switching, Wi-Fi, STP, '
        f'VLAN and firewall. Tool categories: {CATEGORY_SUMMARY}.',
        'Tools that would change the controller are refused; changes go through the '
        "unifi-mapper CLI's plan -> review -> apply flow.",
        'Discover tools with search_tools (or list_categories), read get_tool_info for '
        'the input_schema, then run them with execute_tool.',
    ]
    if link_tools:
        parts.append(f'For link or negotiation problems start with {" and ".join(link_tools)}.')
    if 'diagnose_switch_port' in registry:
        parts.append(
            'diagnose_switch_port produces a single-port evidence bundle for a vendor ticket.'
        )
    return ' '.join(parts)


class UnifiFastMCP(FastMCP[Any]):
    """FastMCP whose direct catalog tools run through ToolRunner, not Tool.run."""

    runner: ToolRunner | None = None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Route direct catalog tools to ToolRunner; everything else to FastMCP.

        Args:
            name: The tool name from the ``tools/call`` request.
            arguments: The raw request arguments.

        Returns:
            A ``CallToolResult`` for direct catalog tools (passed through unchanged by the
            low-level server), otherwise whatever ``FastMCP.call_tool`` returns.
        """
        if self.runner is not None:
            refused = await refuse_held_probe(name, arguments, 'direct')
            if refused is not None:
                return refused
            if self.runner.is_direct(name):
                return await self.runner.run(name, arguments, surface='direct')
        return await super().call_tool(name, arguments)

    async def list_tools(self) -> list[MCPTool]:
        """List tools sorted by name (spec SHOULD, so hosts can cache the listing)."""
        return sorted(await super().list_tools(), key=lambda tool: tool.name)


def _build_fastmcp(surface: Surface, registry: ToolRegistry) -> UnifiFastMCP:
    """Construct the FastMCP object; the only place that writes ``_mcp_server.version``.

    The discovery surface builds no catalog tools (and no runner) here: execute_tool
    gets its runner at call time.
    """
    runner = get_runner() if surface == 'direct' else None
    server = UnifiFastMCP(
        SERVER_NAME,
        instructions=build_instructions(registry),
        lifespan=lifespan,
        tools=runner.catalog.direct_tools() if runner is not None else None,
    )
    # FastMCP has no version kwarg; without this, serverInfo.version reports the SDK's version.
    server._mcp_server.version = package_version()
    server.runner = runner
    return server


def catalog_resource() -> str:
    """``unifi://catalog``: every tool (name + description) and the categories, as JSON."""
    registry = get_registry()
    return json.dumps(
        {
            'categories': registry.get_categories(),
            'tools': registry.search(detail_level='summary'),
        },
        indent=2,
    )


def config_status_resource() -> str:
    """``unifi://config/status``: where config came from and family readiness (key names)."""
    config = _active_config or resolve_mcp_config(_config_path)
    return json.dumps(config.to_json_dict(), indent=2)


def _call(tool: str, args: str) -> str:
    """Render one tool call as the prompt shows it."""
    return f'execute_tool("{tool}", {{{args}}})'


def troubleshoot_port_link(switch: str, port: int) -> str:
    """Investigate a switch port that links at the wrong speed, flaps or stays down.

    Args:
        switch: Switch name, MAC or IP.
        port: Port number on that switch.

    Returns:
        Step-by-step instructions naming only tools registered right now.
    """
    registry = get_registry()
    at = f'"switch": {json.dumps(switch)}, "port": {port}'
    on_switch = f'"switch": {json.dumps(switch)}'
    steps = [
        (
            'inspect_switch_port',
            _call('inspect_switch_port', at) + ': negotiated speed and duplex, the '
            'effective port profile and any override, LLDP neighbour and errors.',
        ),
        (
            'audit_link_speeds',
            _call('audit_link_speeds', on_switch) + ': every port below its capability '
            'or forced to a speed that is down.',
        ),
        (
            'audit_port_profile_usage',
            _call('audit_port_profile_usage', '"profile": "<the port profile>"')
            + ': the other ports on the same profile and how they link.',
        ),
        (
            'analyze_link_quality',
            _call('analyze_link_quality', '"device_id": "<the switch id or MAC>"')
            + ': error and drop counters per port.',
        ),
        (
            'get_switch_ports',
            _call('get_switch_ports', on_switch) + ': compare peer ports with the same '
            'speed capabilities.',
        ),
        (
            'diff_port_profiles',
            _call('diff_port_profiles', '"profile_a": "<A>", "profile_b": "<B>"')
            + ': what differs between the two profiles involved (for example forced vs '
            'auto).',
        ),
        (
            'diagnose_switch_port',
            _call('diagnose_switch_port', at) + ': the single-port evidence bundle for a '
            'vendor ticket.',
        ),
    ]
    lines = [
        f'Troubleshoot the link on port {port} of switch {switch!r}. Every tool here is '
        'read-only; do not change port profiles or overrides from this conversation '
        '(changes go through the unifi-mapper CLI).',
        '',
    ]
    present = [text for name, text in steps if name in registry]
    lines += [f'{i}. {text}' for i, text in enumerate(present, start=1)]
    lines += [
        f'{len(present) + 1}. Ask the user for far-end NIC evidence: `ethtool <iface>` '
        '(supported and advertised link modes, negotiated speed), `ethtool -i <iface>` '
        '(driver and firmware versions) and the NIC or NAS firmware release.',
        '',
        'Summarise what the switch side shows, what the far end shows, and which '
        'combination fails.',
    ]
    return '\n'.join(lines)


def plan_stp_change() -> str:
    """Plan a spanning-tree change safely, through the CLI rather than MCP.

    Returns:
        Instructions that steer the change to the unifi-mapper CLI.
    """
    return '\n'.join(
        [
            'STP changes are applied with the unifi-mapper CLI, never over MCP. Ask the '
            'user to run, in order:',
            '',
            '1. `unifi-mapper stp analyze`: the current topology, root bridge and priorities.',
            '2. `unifi-mapper stp report`: the optimisation report to review together.',
            '3. `unifi-mapper stp optimize --plan stp-plan.json`: a dry run that writes a '
            'reversible change plan.',
            '4. Review the plan, then `unifi-mapper stp apply --plan stp-plan.json` '
            '(a dry run by default; `--no-dry-run` applies it).',
            '',
            'Read-only MCP tools can help explain the topology (discover_stp_topology) and '
            "check every switch's current against its recommended priority "
            '(audit_stp_priorities), before and after.',
        ]
    )


def create_server(surface: Surface = DEFAULT_SURFACE) -> UnifiFastMCP:
    """Build the MCP server for a tool surface.

    ``discovery`` lists the four meta-tools; ``direct`` also lists every non-mutating,
    non-pipeline catalog tool (built here) with its own annotations. Mutating tools are
    never listed or executed on either surface.

    Args:
        surface: ``'discovery'`` or ``'direct'``.

    Returns:
        The server.
    """
    registry = get_registry()
    server = _build_fastmcp(surface, registry)
    for name, (fn, annotations) in META_TOOLS.items():
        server.add_tool(fn, name=name, annotations=annotations)
    server.resource(
        'unifi://catalog',
        name='catalog',
        description='Every tool (name and description) and the categories.',
        mime_type='application/json',
    )(catalog_resource)
    server.resource(
        'unifi://config/status',
        name='config-status',
        description='Where MCP config came from and which credential families are ready '
        '(key names only, never values).',
        mime_type='application/json',
    )(config_status_resource)
    server.prompt(name='troubleshoot_port_link')(troubleshoot_port_link)
    server.prompt(name='plan_stp_change')(plan_stp_change)
    return server


def resolve_surface(flag: str | None, env: dict[str, str] | None = None) -> Surface:
    """Choose the tool surface: ``--surface`` first, then ``UNIFI_MCP_TOOL_SURFACE``.

    Args:
        flag: The validated ``--surface`` value, if given.
        env: The environment; ``None`` means ``os.environ``.

    Returns:
        The surface. An invalid environment value warns and falls back to the default.
    """
    if flag is not None:
        return cast(Surface, flag)
    raw = (os.environ if env is None else env).get(SURFACE_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_SURFACE
    value = raw.strip().lower()
    if value in SURFACES:
        return cast(Surface, value)
    print(
        f'unifi-mcp: {SURFACE_ENV}={raw!r} is not one of {", ".join(SURFACES)}; '
        f'using {DEFAULT_SURFACE}',
        file=sys.stderr,
    )
    return DEFAULT_SURFACE


# The default (discovery) server; `from unifi_mapper.mcp import mcp` keeps working.
mcp = create_server('discovery')


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
        '--surface',
        type=str.lower,
        choices=SURFACES,
        help=(
            'tools to list: discovery (the four meta-tools, the default) or direct (also '
            f'every read-only catalog tool). Default: ${SURFACE_ENV} or {DEFAULT_SURFACE}'
        ),
    )
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
    """Send loguru output to stderr only, at ``level`` (stdout carries JSON-RPC).

    ``diagnose=False``: a logged traceback never shows the failing frames' variable values,
    which can hold a credential (the MCP client keeps this stderr in its own logs).
    """
    logger.remove()
    logger.add(sys.stderr, level=level, diagnose=False)


def check_report(
    config: ResolvedConfig,
    surface: Surface = DEFAULT_SURFACE,
    settings: ServerSettings | None = None,
) -> dict[str, Any]:
    """Return the ``--check`` JSON: config source and per-family readiness, no values.

    Args:
        config: The resolved configuration.
        surface: The selected tool surface.
        settings: The server settings (``None``: :func:`current_settings`).

    Returns:
        A JSON-safe dict naming keys only, plus the tool counts each surface lists,
        ``active_probes`` (whether the gateway SSH probes are listed, and which are held
        back) and ``call_audit``, the MCP call log's path or ``'off'``.
    """
    report = config.to_json_dict()
    controller = report['families'].get('controller')
    if controller is not None and not controller['ready']:
        # --check never runs the Keychain/1Password chain.
        controller['fallback_chain'] = 'not probed'
    settings = settings or current_settings()
    registry = ToolRegistry(active_probes=settings.active_probes)
    report['tool_count'] = len(registry)
    report['active_probes'] = {
        'enabled': registry.active_probes,
        'held': sorted(registry.held_active_probes()),
    }
    report['surface'] = surface
    report['listed_tools'] = {
        'discovery': len(META_TOOLS),
        'direct': len(META_TOOLS) + len(ToolCatalog(registry).direct_tools()),
    }
    try:
        report['call_audit'] = settings.call_audit.describe()
    except RuntimeError:  # the default path with no home directory: no line can be written
        report['call_audit'] = 'off'
    return report


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``unifi-mcp`` console script.

    ``--version`` and ``-h/--help`` print to stdout and exit 0 without starting the server.
    ``--surface discovery|direct`` (or ``UNIFI_MCP_TOOL_SURFACE``) picks the tools listed;
    an invalid flag value exits 2, an invalid environment value warns and uses discovery.
    ``--check`` prints the resolved config (key names only) and exits 0 if the controller
    is configured, else 1. ``--config PATH`` must name a readable file (else exit 2), and
    ``UNIFI_MCP_ALLOW_ACTIVE_PROBES`` must be unset, empty or ``1`` (else exit 2).
    Unknown arguments are reported on stderr and ignored. Otherwise the stdio server runs.
    Every mode but ``--version`` and ``--help`` logs to stderr at ``UNIFI_MCP_LOG_LEVEL``
    (default ``WARNING``), set before anything that can log runs.

    Args:
        argv: Arguments to parse; ``None`` means ``sys.argv[1:]``.
    """
    global _config_path, _settings
    args, unknown = _arg_parser().parse_known_args(argv)
    if unknown:
        print(f'unifi-mcp: ignoring unknown arguments: {" ".join(unknown)}', file=sys.stderr)
    try:
        settings = load_server_settings()
    except ActiveProbesSettingError as e:
        print(f'unifi-mcp: {e}', file=sys.stderr)
        sys.exit(2)
    # Before --check or the direct surface builds the catalog: building it logs DEBUG notes.
    _configure_logging(settings.log_level)
    surface = resolve_surface(args.surface)

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
        print(json.dumps(check_report(config, surface, settings), indent=2))
        sys.exit(0 if config.families['controller'].ready else 1)

    _config_path, _settings = explicit, settings
    server = mcp if surface == 'discovery' else create_server(surface)
    server.run()


if __name__ == '__main__':
    main()
