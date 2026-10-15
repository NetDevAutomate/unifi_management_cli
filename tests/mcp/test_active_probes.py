"""Gateway SSH probes over MCP behind ``UNIFI_MCP_ALLOW_ACTIVE_PROBES`` (issue 092, tier 1).

Four tools run a command on the gateway over SSH. With the variable unset (the default) the
registry holds them back: no surface lists them, ``search_tools``, ``get_tool_info`` and
``list_categories`` do not see them, and ``execute_tool`` refuses them with
``ACTIVE_PROBES_DISABLED``. Every test here loads the real manifests.
"""

from __future__ import annotations

import json
import pytest
from loguru import logger
from pathlib import Path
from typing import Any
from unifi_mapper.mcp import server
from unifi_mapper.mcp.call_audit import CallAuditSetting
from unifi_mapper.mcp.config import (
    ACTIVE_PROBES_ENV,
    ActiveProbesSettingError,
    ServerSettings,
    load_server_settings,
    parse_active_probes,
)
from unifi_mapper.mcp.registry import ToolRegistry


# Tier 1 (issue 092): tool -> (the program it runs on the gateway, its unifi-mapper command).
PROBES: dict[str, tuple[str, str]] = {
    'gateway_ping': ('ping', 'gateway ping'),
    'gateway_traceroute': ('traceroute', 'gateway traceroute'),
    'gateway_dns_check': ('nslookup', 'gateway dns'),
    'run_latency_matrix': ('ping', 'diagnose latency-matrix'),
}
# One valid call per probe; the refusal must come before anything reads them.
CALLS: dict[str, dict[str, Any]] = {
    'gateway_ping': {'target': '192.0.2.10', 'count': 3},
    'gateway_traceroute': {'target': '192.0.2.10', 'max_hops': 5},
    'gateway_dns_check': {'hostname': 'example.com'},
    'run_latency_matrix': {'ping_count': 1},
}


def _use(monkeypatch: pytest.MonkeyPatch, settings: ServerSettings) -> None:
    """Make the server build its registry and runner from ``settings``, as main() does."""
    monkeypatch.setattr(server, '_settings', settings)
    monkeypatch.setattr(server, '_registry', None)
    monkeypatch.setattr(server, '_runner', None)


@pytest.fixture
def gate_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The default server: active probes off; the call log at a known path."""
    log = tmp_path / 'calls.jsonl'
    _use(monkeypatch, ServerSettings(call_audit=CallAuditSetting('path', log)))
    return log


def _names(tools: list[Any]) -> set[str]:
    return {tool.name for tool in tools}


# ---------------------------------------------------------------------------
# The setting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('raw', 'expected'), [(None, False), ('', False), (' ', False), ('1', True)]
)
def test_only_1_turns_the_probes_on(raw: str | None, expected: bool) -> None:
    assert parse_active_probes(raw) is expected
    env = {} if raw is None else {ACTIVE_PROBES_ENV: raw}
    assert load_server_settings(env, warn=pytest.fail).active_probes is expected


@pytest.mark.parametrize('raw', ['0', 'true', 'yes', 'on', '2', 'TRUE'])
def test_any_other_value_is_a_named_config_error(raw: str) -> None:
    with pytest.raises(ActiveProbesSettingError, match=ACTIVE_PROBES_ENV):
        parse_active_probes(raw)
    with pytest.raises(ActiveProbesSettingError, match=ACTIVE_PROBES_ENV):
        load_server_settings({ACTIVE_PROBES_ENV: raw}, warn=pytest.fail)


@pytest.mark.parametrize('argv', [[], ['--check']])
def test_main_refuses_to_start_on_a_bad_value(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[object] = []
    monkeypatch.setattr(server.UnifiFastMCP, 'run', lambda self, *a, **k: ran.append(a))
    monkeypatch.setattr(server, '_settings', None)
    monkeypatch.setitem(server.os.environ, ACTIVE_PROBES_ENV, 'yes')
    with pytest.raises(SystemExit) as exc:
        server.main(argv)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert ACTIVE_PROBES_ENV in err and "'yes'" in err
    assert ran == []


# ---------------------------------------------------------------------------
# Gate off: held back from every listing, refused by execute_tool
# ---------------------------------------------------------------------------


def test_the_shipped_manifests_hold_exactly_the_tier1_probes() -> None:
    registry = ToolRegistry(strict=True)
    held = registry.held_active_probes()
    assert set(held) == set(PROBES)
    for name, meta in held.items():
        assert meta.active_probe and not meta.mutates
        assert meta.cli == PROBES[name][1]
        assert name not in registry
        assert registry.get_metadata(name) is None
    listed = {n for names in registry.get_categories().values() for n in names}
    assert not listed & set(PROBES)
    assert len(registry) == len(listed)


async def test_neither_surface_lists_a_probe(gate_off: Path) -> None:
    for surface in server.SURFACES:
        assert not _names(await server.create_server(surface).list_tools()) & set(PROBES)


@pytest.mark.parametrize(
    'kwargs',
    [{}, {'query': 'ping'}, {'query': 'gateway ssh'}, {'detail_level': 'full'}, {'tags': ['ssh']}],
)
async def test_search_tools_does_not_find_a_probe(gate_off: Path, kwargs: dict[str, Any]) -> None:
    assert not {hit['name'] for hit in await server.search_tools(**kwargs)} & set(PROBES)


@pytest.mark.parametrize('name', sorted(PROBES))
async def test_get_tool_info_does_not_know_a_probe(gate_off: Path, name: str) -> None:
    assert await server.get_tool_info(name) is None


async def test_list_categories_does_not_count_a_probe(gate_off: Path) -> None:
    categories = await server.list_categories()
    assert not {n for names in categories.values() for n in names} & set(PROBES)
    assert json.loads(server.catalog_resource())['categories'] == categories


@pytest.mark.parametrize('name', sorted(PROBES))
async def test_execute_tool_refuses_a_probe_naming_the_variable_and_command(
    gate_off: Path, name: str
) -> None:
    out = await server.execute_tool(name, CALLS[name])
    assert out.isError is True
    envelope = out.structuredContent
    assert envelope is not None
    assert envelope['ok'] is False
    assert envelope['error_code'] == 'ACTIVE_PROBES_DISABLED'
    program, command = PROBES[name]
    assert ACTIVE_PROBES_ENV in envelope['message']
    assert f'runs {program} on the gateway over SSH' in envelope['message']
    assert f'{ACTIVE_PROBES_ENV}=1' in envelope['suggestion']
    assert f'unifi-mapper {command}' in envelope['suggestion']
    assert json.loads(out.content[0].text) == envelope  # type: ignore[union-attr]


async def test_a_refusal_is_in_the_call_log(gate_off: Path) -> None:
    await server.execute_tool('gateway_ping', CALLS['gateway_ping'])
    [line] = [json.loads(raw) for raw in gate_off.read_text(encoding='utf-8').splitlines()]
    assert (line['tool'], line['outcome']) == ('gateway_ping', 'ACTIVE_PROBES_DISABLED')


async def test_the_direct_surface_refuses_a_probe_by_name(gate_off: Path) -> None:
    out = await server.create_server('direct').call_tool('gateway_ping', CALLS['gateway_ping'])
    assert out.isError is True
    assert out.content[0].text.startswith('[ACTIVE_PROBES_DISABLED] ')  # type: ignore[union-attr]


def test_the_startup_log_says_how_many_are_held(gate_off: Path) -> None:
    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(str(m)), level='INFO', format='{level} {message}')
    try:
        server.log_active_probes(server.get_registry())
    finally:
        logger.remove(sink)
    assert len(seen) == 1
    assert seen[0].startswith('INFO 4 active-probe tools held back')
    assert f'{ACTIVE_PROBES_ENV}=1' in seen[0]


async def test_the_lifespan_writes_the_startup_log(gate_off: Path) -> None:
    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(str(m)), level='INFO', format='{message}')
    try:
        async with server.lifespan(server.mcp):
            pass
    finally:
        logger.remove(sink)
    assert any('active-probe tools held back' in line for line in seen)


def test_check_reports_the_gate(gate_off: Path) -> None:
    config = server.resolve_mcp_config(None)
    report = server.check_report(config, 'direct', ServerSettings())
    assert report['active_probes'] == {'enabled': False, 'held': sorted(PROBES)}
    assert report['tool_count'] == len(ToolRegistry())
