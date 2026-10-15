"""CLI/MCP surface parity: the mapping and the exemptions the gate enforces (issue 078).

The two surfaces must offer the same features, or say why not. Each MCP manifest entry
declares ``cli:`` (the ``unifi-mapper`` command it is the counterpart of) or ``cli_gap:``
(why there is no command); each ``unifi-mapper`` command is named by some ``cli:`` or listed
in :data:`CLI_ONLY` with a reason. Reasons start with a category from
:data:`CLI_ONLY_CATEGORIES` or :data:`CLI_GAP_CATEGORIES`, so a gap is either a standing
decision (a writer, an SSH probe, a raw read) or a feature not yet built on the other side.
``tests/test_surface_parity.py`` fails on any undeclared gap and pins the "not yet built"
counts, so the gap can only move by an edit here or in a manifest.
"""

from __future__ import annotations

import click
from .registry import ToolRegistry
from dataclasses import dataclass, field
from typer.main import get_group
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import typer

# Why a unifi-mapper command has no MCP tool.
CLI_ONLY_CATEGORIES: dict[str, str] = {
    'writer': 'changes controller state; the control boundary keeps writes on the CLI',
    'by nature': 'only makes sense at a terminal (shell completions, local files, the port-mapper)',
    'active probe': 'runs a command on the gateway over SSH; kept off MCP by issue 092',
    'long-running': 'a run outlasts an MCP call; issue 060 decision D4 waits for SDK tasks',
    'not yet built': 'a read the MCP server should offer; tracked by issue 078',
}

# Why an MCP tool has no unifi-mapper command.
CLI_GAP_CATEGORIES: dict[str, str] = {
    'raw read': 'an agent-facing read of controller objects the UniFi UI already shows',
    'not yet built': 'a feature a terminal user would want; tracked by issue 078',
}

# unifi-mapper commands with no MCP tool, each with "category: detail". A command an MCP tool
# names with cli: must not be here; a command that stops existing must be removed.
CLI_ONLY: dict[str, str] = {
    # Writers: the CLI's plan -> review -> apply flow, never over MCP (issue 019).
    'stp rollback': 'writer: applies a saved rollback plan to the controller',
    'inventory update-firmware': 'writer: triggers firmware upgrades (preview by default)',
    'ports refresh': 'writer: renames switch ports from live LLDP and client data',
    'vlan-traffic sample': 'writer: an SSH collector that appends to the local store',
    'vlan-traffic rollup': 'writer: rolls the local store up offline',
    'discover': 'writer: the port-naming workflow (preview by default, --apply writes names)',
    # Terminal-only by nature.
    'install-completions': 'by nature: installs shell completions',
    'version': 'by nature: prints the installed version (the server reports its own)',
    'verify': 'by nature: ground-truth verification of the port-naming workflow',
    'diagram': 'by nature: renders topology diagrams to local files',
    # SSH probes left off MCP. Ping, traceroute, DNS and the latency matrix are opt-in tools
    # (issue 092 tier 1, UNIFI_MCP_ALLOW_ACTIVE_PROBES); these wait for the tier-2 decision.
    'gateway http': 'active probe: curl fetches a URL the agent picks (issue 092 tier 2, pending)',
    'gateway flows': 'active probe: the whole conntrack table (issue 092 tier 2, pending)',
    'diagnose client-connectivity': 'active probe: includes an HTTP fetch (issue 092 tier 2)',
    'diagnose bandwidth': 'active probe: iperf3 saturates a link (excluded by issue 092)',
    # Longer than an MCP call.
    'diagnose ap-health': 'long-running: samples for up to 10 h (issue 060 D4, issue 008)',
}


def category_of(reason: str) -> str:
    """Return the category prefix of a reason (``'writer: ...'`` -> ``'writer'``).

    Args:
        reason: A reason string, ``"category: detail"``.

    Returns:
        The text before the first ``': '``, or the whole string when there is none.
    """
    return reason.split(': ', 1)[0]


def cli_commands(app: typer.Typer | None = None) -> dict[str, click.Command]:
    """Return every leaf command of the ``unifi-mapper`` tree, keyed by its space-joined path.

    Args:
        app: The Typer application; the default is ``unifi_mapper.typer_cli.app``.

    Returns:
        ``{'analyze poe-budget': <Command>, ...}``, hidden commands included.
    """
    if app is None:
        from unifi_mapper.typer_cli import app as default_app

        app = default_app
    commands: dict[str, click.Command] = {}

    def walk(command: click.Command, path: tuple[str, ...]) -> None:
        if isinstance(command, click.Group):
            for name, sub in command.commands.items():
                walk(sub, (*path, name))
        else:
            commands[' '.join(path)] = command

    walk(get_group(app), ())
    return commands


@dataclass
class ParityReport:
    """The parity gate's result over one registry and one command tree.

    Attributes:
        matched: MCP tool -> the ``unifi-mapper`` command it is the counterpart of.
        mcp_only: MCP tool -> its ``cli_gap`` reason.
        cli_only: command -> its reason, as given.
        problems: Every rule violation, one line each; empty when the gate passes.
    """

    matched: dict[str, str] = field(default_factory=lambda: {})
    mcp_only: dict[str, str] = field(default_factory=lambda: {})
    cli_only: dict[str, str] = field(default_factory=lambda: {})
    problems: list[str] = field(default_factory=lambda: [])


def parity_report(
    registry: ToolRegistry | None = None,
    app: typer.Typer | None = None,
    *,
    cli_only: dict[str, str] | None = None,
) -> ParityReport:
    """Check every manifest entry and every command against the parity rules.

    Args:
        registry: The manifest registry; the default is the shipped manifests.
        app: The Typer application; the default is ``unifi_mapper.typer_cli.app``.
        cli_only: The exemption table; the default is :data:`CLI_ONLY`.

    Returns:
        The report; ``problems`` is empty when both surfaces agree.
    """
    registry = registry or ToolRegistry()
    exempt = CLI_ONLY if cli_only is None else cli_only
    commands = cli_commands(app)
    report = ParityReport(cli_only=dict(exempt))
    named_by: dict[str, str] = {}

    # Every manifest entry, the active probes a registry holds back included: they are
    # features of the MCP server whether or not this process lists them (issue 092).
    entries = {
        name: meta
        for tools in registry.get_categories().values()
        for name in tools
        if (meta := registry.get_metadata(name)) is not None
    }
    entries |= registry.held_active_probes()
    for name, meta in sorted(entries.items()):
        if meta.cli and meta.cli_gap:
            report.problems.append(f'{name}: declare exactly one of cli: and cli_gap:')
            continue
        if meta.cli:
            if meta.cli not in commands:
                report.problems.append(f'{name}: cli {meta.cli!r} is not a unifi-mapper command')
            report.matched[name] = meta.cli
            named_by.setdefault(meta.cli, name)
        elif meta.cli_gap:
            if category_of(meta.cli_gap) not in CLI_GAP_CATEGORIES:
                report.problems.append(f'{name}: cli_gap {meta.cli_gap!r} has no category')
            report.mcp_only[name] = meta.cli_gap
        else:
            report.problems.append(f'{name}: declare cli: or cli_gap:')

    for command in sorted(commands):
        if command not in named_by and command not in exempt:
            report.problems.append(f'{command}: no MCP tool and not in CLI_ONLY')
    for command, reason in exempt.items():
        if command not in commands:
            report.problems.append(f'CLI_ONLY {command!r} is not a unifi-mapper command')
        elif command in named_by:
            report.problems.append(
                f'CLI_ONLY {command!r} is named by MCP tool {named_by[command]}'
            )
        if category_of(reason) not in CLI_ONLY_CATEGORIES:
            report.problems.append(f'CLI_ONLY {command!r}: reason {reason!r} has no category')
    return report
