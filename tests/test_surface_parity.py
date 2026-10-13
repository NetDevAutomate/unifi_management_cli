"""The CLI and the MCP server offer the same features, or say why not (issue 078).

Every manifest entry declares ``cli:`` (the ``unifi-mapper`` command it is the counterpart of)
or ``cli_gap:`` (why no command exists); every ``unifi-mapper`` command is named by a ``cli:``
or listed in ``CLI_ONLY`` with a reason. The rules live in ``unifi_mapper.mcp.parity``; this
file fails on any undeclared gap, stale exemption or unclassified reason, and pins the number
of gaps that are declared "not yet built" so closing one (or adding one) is a deliberate edit.
"""

import pytest
from unifi_mapper.mcp.parity import (
    CLI_GAP_CATEGORIES,
    CLI_ONLY,
    CLI_ONLY_CATEGORIES,
    ParityReport,
    category_of,
    cli_commands,
    parity_report,
)
from unifi_mapper.mcp.registry import MANIFEST_KEYS, ToolRegistry, default_manifests_dir


REGISTRY = ToolRegistry(default_manifests_dir(), strict=True)
REPORT: ParityReport = parity_report(REGISTRY)
ENTRIES = sorted(
    (name, REGISTRY.get_metadata(name))
    for tools in REGISTRY.get_categories().values()
    for name in tools
)

# Gaps declared "not yet built" on each side. Closing one lowers the number here; adding one
# raises it, which is the visible cost of shipping a feature on one surface only.
NOT_YET_BUILT_CLI_COMMANDS = 0
NOT_YET_BUILT_MCP_TOOLS = 18


def test_the_gate_has_no_problems() -> None:
    assert REPORT.problems == []


def test_manifest_keys_carry_the_parity_fields() -> None:
    assert MANIFEST_KEYS['cli'] is str
    assert MANIFEST_KEYS['cli_gap'] is str


@pytest.mark.parametrize(('name', 'meta'), ENTRIES)
def test_every_entry_declares_a_counterpart_or_a_gap(name: str, meta: object) -> None:
    assert meta is not None
    cli, gap = getattr(meta, 'cli'), getattr(meta, 'cli_gap')
    assert bool(cli) != bool(gap), f'{name}: declare exactly one of cli: and cli_gap:'
    if gap:
        assert category_of(gap) in CLI_GAP_CATEGORIES, f'{name}: cli_gap {gap!r} is unclassified'


def test_every_cli_reference_names_a_real_command() -> None:
    commands = cli_commands()
    for tool, command in REPORT.matched.items():
        assert command in commands, f'{tool}: cli {command!r} is not a unifi-mapper command'


def test_every_cli_command_is_covered_or_exempt() -> None:
    commands = set(cli_commands())
    covered = set(REPORT.matched.values())
    assert covered | set(CLI_ONLY) == commands
    assert not (covered & set(CLI_ONLY)), 'a command an MCP tool names must not be in CLI_ONLY'


def test_cli_only_reasons_are_classified() -> None:
    for command, reason in CLI_ONLY.items():
        assert category_of(reason) in CLI_ONLY_CATEGORIES, f'{command}: {reason!r}'
        assert len(reason.split(': ', 1)) == 2 and reason.split(': ', 1)[1], command


def test_the_declared_gaps_are_the_recorded_ones() -> None:
    cli_gaps = sorted(c for c, r in CLI_ONLY.items() if category_of(r) == 'not yet built')
    mcp_gaps = sorted(t for t, r in REPORT.mcp_only.items() if category_of(r) == 'not yet built')
    assert len(cli_gaps) == NOT_YET_BUILT_CLI_COMMANDS, cli_gaps
    assert len(mcp_gaps) == NOT_YET_BUILT_MCP_TOOLS, mcp_gaps


def test_the_raw_reads_are_the_network_and_protect_tools() -> None:
    raw = {t for t, r in REPORT.mcp_only.items() if category_of(r) == 'raw read'}
    categories = REGISTRY.get_categories()
    assert raw == set(categories['network']) | set(categories['protect'])


def test_the_writers_are_declared_on_both_sides() -> None:
    # The three declared mutating tools name their CLI command; the CLI-only writers say so.
    for tool in ('apply_stp_changes', 'apply_radio_optimization', 'restore_radio_config'):
        assert tool in REPORT.matched
    for command in ('stp rollback', 'inventory update-firmware', 'ports refresh'):
        assert category_of(CLI_ONLY[command]) == 'writer'


def test_the_ssh_probes_are_exempt_by_decision_d1() -> None:
    for command in (
        'gateway ping',
        'gateway traceroute',
        'gateway dns',
        'gateway http',
        'gateway flows',
        'diagnose latency-matrix',
        'diagnose bandwidth',
        'diagnose client-connectivity',
    ):
        assert category_of(CLI_ONLY[command]) == 'active probe', command
        assert '060' in CLI_ONLY[command], command


def test_the_report_counts_add_up() -> None:
    assert len(REPORT.matched) + len(REPORT.mcp_only) == len(REGISTRY)
    assert len(set(REPORT.matched.values())) + len(CLI_ONLY) == len(cli_commands())


def test_a_registry_with_an_undeclared_tool_is_a_problem(tmp_path) -> None:
    manifest = tmp_path / 'x.yaml'
    manifest.write_text(
        'category: analysis\n'
        'tools:\n'
        '  undeclared_tool:\n'
        '    module: unifi_mapper.analysis.poe_budget\n'
        '    handler: check_poe_budget\n'
        '    title: Undeclared\n'
        '  both_declared:\n'
        '    module: unifi_mapper.analysis.poe_budget\n'
        '    handler: check_poe_budget\n'
        '    title: Both\n'
        '    cli: analyze poe-budget\n'
        '    cli_gap: "raw read: x"\n'
        '  unknown_command:\n'
        '    module: unifi_mapper.analysis.poe_budget\n'
        '    handler: check_poe_budget\n'
        '    title: Unknown\n'
        '    cli: analyze no-such-command\n'
        '  bad_reason:\n'
        '    module: unifi_mapper.analysis.poe_budget\n'
        '    handler: check_poe_budget\n'
        '    title: Bad\n'
        '    cli_gap: "because"\n'
        '  well_formed:\n'
        '    module: unifi_mapper.analysis.poe_budget\n'
        '    handler: check_poe_budget\n'
        '    title: Well Formed\n'
        '    cli: analyze poe-budget\n'
    )
    report = parity_report(ToolRegistry(tmp_path, strict=True), cli_only={})
    joined = '\n'.join(report.problems)
    assert 'undeclared_tool: declare cli: or cli_gap:' in joined
    assert 'both_declared: declare exactly one' in joined
    assert "unknown_command: cli 'analyze no-such-command' is not a unifi-mapper command" in joined
    assert "bad_reason: cli_gap 'because' has no category" in joined
    assert report.matched['well_formed'] == 'analyze poe-budget'
    # With an empty exemption table every uncovered command is a problem, and a stale
    # exemption (one that is not a command, or one an MCP tool now names) is too.
    assert 'analyze client-density: no MCP tool and not in CLI_ONLY' in joined
    assert 'analyze poe-budget: no MCP tool' not in joined
    stale = parity_report(
        ToolRegistry(tmp_path, strict=True),
        cli_only={'no such': 'by nature: x', 'analyze poe-budget': 'writer: x'},
    )
    joined = '\n'.join(stale.problems)
    assert "CLI_ONLY 'no such' is not a unifi-mapper command" in joined
    assert "CLI_ONLY 'analyze poe-budget' is named by MCP tool well_formed" in joined
