"""Tests for running tools through the registry and the MCP execute_tool meta-tool.

Covers the safety policy (tools declaring ``mutates: true`` are refused), manifest
parameter validation, and the shape of execute_tool's success/error envelopes.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unifi_mapper.mcp.registry import ToolRegistry
from unittest.mock import AsyncMock, patch


MANIFEST = """
category: test
tools:
  read_port:
    module: fake.mod
    handler: read_port
    description: Read-only port lookup
    parameters:
      switch: {type: string, required: true}
      port: {type: integer, required: true}
      verbose: {type: boolean}
  apply_things:
    module: fake.mod
    handler: apply_things
    description: Writes live config
    mutates: true
  no_params_tool:
    module: fake.mod
    handler: no_params
    description: Declares no parameters
"""


@pytest.fixture
def registry(tmp_path: Path) -> ToolRegistry:
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'test.yaml').write_text(MANIFEST)
    return ToolRegistry(manifests)


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


def test_mutates_flag_parsed_and_defaults_false(registry: ToolRegistry) -> None:
    assert registry.get_metadata('apply_things').mutates is True
    assert registry.get_metadata('read_port').mutates is False


def test_full_search_exposes_mutates(registry: ToolRegistry) -> None:
    [hit] = registry.search(query='apply_things', detail_level='full')
    assert hit['mutates'] is True


def test_shipped_manifests_flag_exactly_the_controller_writers() -> None:
    """Guard against a new apply_/restore_ tool shipping without the flag (or the flag drifting)."""
    shipped = ToolRegistry()  # real manifests
    mutating = {n for n in shipped.get_categories()['analysis'] if shipped.get_metadata(n).mutates}
    assert mutating == {'apply_stp_changes', 'apply_radio_optimization', 'restore_radio_config'}
    assert _unflagged_writers(shipped) == []


# A tool whose name says it changes the controller must declare ``mutates: true`` (issue 019's
# rule: CLI only, dry run first, never over MCP). ``trigger_*`` is left out: an on-demand
# probe is decision D1 in issue 060 (an active_probe flag), not a write.
WRITER_PREFIXES = ('apply_', 'restore_', 'set_', 'power_cycle_', 'delete_')


def _names_a_write(name: str) -> bool:
    return name.startswith(WRITER_PREFIXES) or (name.startswith('run_') and 'speedtest' in name)


def _unflagged_writers(registry: ToolRegistry) -> list[str]:
    names = [n for tools in registry.get_categories().values() for n in tools]
    return sorted(n for n in names if _names_a_write(n) and not registry.get_metadata(n).mutates)


def test_the_writer_naming_rule_catches_set_power_cycle_and_speedtest_names(
    tmp_path: Path,
) -> None:
    lines = ['category: test', 'tools:']
    for name in (
        'set_wlan_option',
        'power_cycle_poe_port',
        'delete_firewall_rule',
        'run_wan_speedtest',
        'trigger_vlan_traffic_sample',
        'get_wan_health',
    ):
        lines += [
            f'  {name}:',
            '    module: fake.mod',
            f'    handler: {name}',
            '    description: fake',
        ]
    (tmp_path / 'test.yaml').write_text('\n'.join(lines) + '\n')
    found = _unflagged_writers(ToolRegistry(tmp_path))
    assert found == [
        'delete_firewall_rule',
        'power_cycle_poe_port',
        'run_wan_speedtest',
        'set_wlan_option',
    ]


# The prototype's MCP tools that the port did not put on MCP (issue 059 says why; issue 060
# holds the open choices). None may be registered without that decision.
PROTOTYPE_TOOLS_NOT_ON_MCP = (
    'decode_object_timestamps',
    'run_latency_matrix',
    'run_port_mapping',
    'run_spectrum_scan',
    'power_cycle_poe_port',
    'set_wlan_option',
    'set_wlan_ap_group',
    'list_jobs',
    'get_job_status',
    'get_job_result',
    'cancel_job',
    'run_ap_health_test',
    'diagnose_client_connectivity',
    'gateway_ping',
    'gateway_traceroute',
    'gateway_dns_check',
    'gateway_http_check',
    'get_active_flows',
    'get_backup_status',
    'run_wan_speedtest',
    'trigger_vlan_traffic_sample',
    'mcp_health_check',
)


def test_no_prototype_tool_left_off_mcp_is_registered() -> None:
    assert len(set(PROTOTYPE_TOOLS_NOT_ON_MCP)) == 22
    shipped = ToolRegistry()
    names = {n for tools in shipped.get_categories().values() for n in tools}
    registered = sorted(names & set(PROTOTYPE_TOOLS_NOT_ON_MCP))
    assert not registered, (
        f'{registered} were left off MCP by the 0.2.0 port: read '
        'docs/issues/059-prototype-work-not-ported.md and docs/issues/060-decisions-from-the-'
        '0.2.0-port.md (decisions D1-D4, W6-W10) before registering them'
    )


# ---------------------------------------------------------------------------
# ToolRegistry.execute policy
# ---------------------------------------------------------------------------


async def test_unknown_tool_raises_keyerror(registry: ToolRegistry) -> None:
    with pytest.raises(KeyError):
        await registry.execute('nope')


async def test_mutating_tool_refused_by_default(registry: ToolRegistry) -> None:
    with patch('unifi_mapper.mcp.registry.ToolProxy.execute', new=AsyncMock()) as run:
        with pytest.raises(PermissionError):
            await registry.execute('apply_things')
        run.assert_not_called()  # refused BEFORE the implementation is even imported


async def test_mutating_tool_allowed_only_with_explicit_opt_in(registry: ToolRegistry) -> None:
    with patch('unifi_mapper.mcp.registry.ToolProxy.execute', new=AsyncMock(return_value='done')):
        assert await registry.execute('apply_things', allow_mutation=True) == 'done'


async def test_missing_required_parameter(registry: ToolRegistry) -> None:
    with pytest.raises(ValueError, match='missing required parameter\\(s\\): port'):
        await registry.execute('read_port', {'switch': 'Office'})


async def test_unknown_parameter(registry: ToolRegistry) -> None:
    with pytest.raises(ValueError, match='unknown parameter\\(s\\): colour'):
        await registry.execute('read_port', {'switch': 'Office', 'port': 5, 'colour': 'red'})


async def test_valid_call_passes_params_through(registry: ToolRegistry) -> None:
    with patch(
        'unifi_mapper.mcp.registry.ToolProxy.execute', new=AsyncMock(return_value={'speed': 5000})
    ) as run:
        result = await registry.execute('read_port', {'switch': 'Office', 'port': 5})
    assert result == {'speed': 5000}
    run.assert_awaited_once_with(switch='Office', port=5)


async def test_tool_without_declared_params_skips_unknown_check(registry: ToolRegistry) -> None:
    with patch('unifi_mapper.mcp.registry.ToolProxy.execute', new=AsyncMock(return_value=1)):
        assert await registry.execute('no_params_tool', {'anything': True}) == 1


# ---------------------------------------------------------------------------
# MCP execute_tool envelope
# ---------------------------------------------------------------------------


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The real server module, its registry pointing at tests/mcp/fakes.py handlers."""
    from tests.mcp import fakes
    from unifi_mapper.mcp import server as srv

    fake = fakes.fake_registry(tmp_path)
    monkeypatch.setattr(srv, 'get_registry', lambda: fake)
    return srv


async def test_execute_tool_success_envelope(server) -> None:
    out = await server.execute_tool('read_port', {'switch': 'S', 'port': 1})
    assert out.structuredContent == {'ok': True, 'result': {'a': 1}}


@pytest.mark.parametrize(
    ('tool', 'params', 'code'),
    [
        ('nope', None, 'TOOL_NOT_FOUND'),
        ('apply_things', None, 'MUTATION_REFUSED'),
        ('read_port', {'switch': 'S'}, 'INVALID_PARAMETERS'),
    ],
)
async def test_execute_tool_error_envelopes(server, tool, params, code) -> None:
    out = (await server.execute_tool(tool, params)).structuredContent
    assert out['ok'] is False
    assert out['error_code'] == code


async def test_execute_tool_wraps_tool_error(server) -> None:
    params = {'code': 'DEVICE_NOT_FOUND', 'message': 'switch not found', 'suggestion': 'x'}
    out = (await server.execute_tool('raise_domain', params)).structuredContent
    assert out['ok'] is False and out['error_code'] == 'DEVICE_NOT_FOUND'


async def test_execute_tool_never_raises_on_unexpected_error(server) -> None:
    params = {'kind': 'RuntimeError', 'text': 'boom'}
    out = await server.execute_tool('raise_exc', params)
    assert out.structuredContent == {
        'ok': False,
        'error_code': 'TOOL_FAILED',
        'message': 'RuntimeError: boom',
        'suggestion': 'Run the equivalent unifi-mapper CLI command for a full traceback.',
    }
