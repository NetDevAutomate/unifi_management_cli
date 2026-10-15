"""Gateway SSH probes over MCP behind ``UNIFI_MCP_ALLOW_ACTIVE_PROBES`` (issue 092, tier 1).

Four tools run a command on the gateway over SSH. With the variable unset (the default) the
registry holds them back: no surface lists them, ``search_tools``, ``get_tool_info`` and
``list_categories`` do not see them, and ``execute_tool`` refuses them with
``ACTIVE_PROBES_DISABLED``. Every test here loads the real manifests.
"""

from __future__ import annotations

import asyncssh
import inspect
import json
import os
import pytest
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from loguru import logger
from pathlib import Path
from tests.fake_controller import API, FakeController, legacy, serving
from tests.fake_gateway import PASSWORD, REAL_CONNECT, USER, Reply, serve, write_known_hosts
from tests.fixtures_unifi import FAKE_TOKEN
from tests.mcp.test_execute import _names_a_write
from typing import Any
from unifi_mapper.analysis.latency_matrix import run_latency_matrix
from unifi_mapper.connectivity.gateway_probe import (
    gateway_dns_check,
    gateway_ping,
    gateway_traceroute,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.mcp import server
from unifi_mapper.mcp.call_audit import CallAuditSetting
from unifi_mapper.mcp.catalog import annotations_for
from unifi_mapper.mcp.config import (
    ACTIVE_PROBES_ENV,
    ActiveProbesSettingError,
    ServerSettings,
    active_probes_allowed,
    load_server_settings,
    parse_active_probes,
)
from unifi_mapper.mcp.registry import ToolMetadata, ToolRegistry
from unifi_mapper.mcp.runner import _to_jsonable


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


# The gate's value table (issue 092, council pass A): unset or empty is off, exactly '1' is
# on, and every other present value is a named start-up error, never a silent off and never a
# truthy parse. One case per row.
@pytest.mark.parametrize(('raw', 'expected'), [(None, False), ('', False), ('1', True)])
def test_unset_and_empty_are_off_and_exactly_1_is_on(raw: str | None, expected: bool) -> None:
    assert parse_active_probes(raw) is expected
    env = {} if raw is None else {ACTIVE_PROBES_ENV: raw}
    assert load_server_settings(env, warn=pytest.fail).active_probes is expected
    assert active_probes_allowed(env) is expected


@pytest.mark.parametrize('raw', ['0', 'true', 'yes', 'TRUE', ' 1 ', ' ', 'on', '2', '1\n'])
def test_any_other_present_value_is_a_named_startup_error(raw: str) -> None:
    pattern = re.escape(f'{ACTIVE_PROBES_ENV}={raw!r} is not exactly 1')
    with pytest.raises(ActiveProbesSettingError, match=pattern) as info:
        parse_active_probes(raw)
    # The error says why this setting does not warn and fall back like the tool surface.
    assert 'Unlike UNIFI_MCP_TOOL_SURFACE' in str(info.value)
    assert 'agent-triggered SSH' in str(info.value)
    with pytest.raises(ActiveProbesSettingError, match=pattern):
        load_server_settings({ACTIVE_PROBES_ENV: raw}, warn=pytest.fail)
    # The fallback the registry uses before main() has validated the setting reads it as off,
    # never as on; main() itself refuses to start (the test below).
    assert active_probes_allowed({ACTIVE_PROBES_ENV: raw}) is False


def test_the_tool_surface_warns_and_falls_back_where_the_gate_refuses() -> None:
    # The contrast the guide documents: an invalid surface is a warning with a default.
    seen: list[str] = []
    surface = server.resolve_surface(None, {server.SURFACE_ENV: 'yes'})
    assert surface == server.DEFAULT_SURFACE
    with pytest.raises(ActiveProbesSettingError):
        load_server_settings({ACTIVE_PROBES_ENV: 'yes'}, warn=seen.append)
    assert seen == []  # no warning: the error is the whole response


@pytest.mark.parametrize('argv', [[], ['--check']])
@pytest.mark.parametrize('raw', ['0', 'true', 'yes', 'TRUE', ' 1 '])
def test_main_refuses_to_start_on_a_bad_value(
    argv: list[str], raw: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[object] = []
    monkeypatch.setattr(server.UnifiFastMCP, 'run', lambda self, *a, **k: ran.append(a))
    monkeypatch.setattr(server, '_settings', None)
    monkeypatch.setitem(server.os.environ, ACTIVE_PROBES_ENV, raw)
    with pytest.raises(SystemExit) as exc:
        server.main(argv)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert f'{ACTIVE_PROBES_ENV}={raw!r} is not exactly 1' in err
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


# ---------------------------------------------------------------------------
# Gate on: listed with the trust class, run through ToolRunner over a real SSH server
# ---------------------------------------------------------------------------

GATEWAY = '192.0.2.1'  # UNIFI_URL's host: the gateway the probes connect to
PING_OK = (
    '3 packets transmitted, 3 received, 0% packet loss\n'
    'rtt min/avg/max/mdev = 0.100/0.200/0.300/0.050 ms\n'
)
TRACEROUTE_OK = (
    'traceroute to 192.0.2.10 (192.0.2.10), 5 hops max, 38 byte packets\n'
    ' 1  192.0.2.10  0.512 ms  0.401 ms  0.388 ms\n'
)
NSLOOKUP_OK = (
    'Server:\t\t127.0.0.1\nAddress:\t127.0.0.1:53\n\n'
    'Non-authoritative answer:\nName:\texample.com\nAddress: 192.0.2.80\n'
)
REPLIES: dict[str, dict[str, Reply]] = {
    'gateway_ping': {'ping': PING_OK},
    'gateway_traceroute': {'traceroute': TRACEROUTE_OK},
    'gateway_dns_check': {'nslookup': NSLOOKUP_OK},
    'run_latency_matrix': {'ping': PING_OK},
}
# The planted gateway SSH password, echoed where each probe's parser copies text into its
# result (a hop's name, an answer's name) or its error (ping's stderr on a failed run).
PLANTED: dict[str, dict[str, Reply]] = {
    'gateway_traceroute': {'traceroute': f' 1  {PASSWORD} (192.0.2.10)  0.512 ms\n'},
    'gateway_dns_check': {'nslookup': NSLOOKUP_OK.replace('example.com', PASSWORD)},
}
HANDLERS = {
    'gateway_ping': gateway_ping,
    'gateway_traceroute': gateway_traceroute,
    'gateway_dns_check': gateway_dns_check,
    'run_latency_matrix': run_latency_matrix,
}
CONTROLLER_ROUTES = {
    f'{API}/stat/device': legacy(
        [{'name': 'Core Switch', 'mac': '02:00:00:00:00:01', 'ip': '192.0.2.20'}]
    ),
    f'{API}/stat/sta': legacy(
        [{'hostname': 'laptop', 'mac': '02:00:00:00:00:02', 'ip': '192.0.2.30'}]
    ),
}


@pytest.fixture(scope='module')
def host_keys() -> tuple[asyncssh.SSHKey, asyncssh.SSHKey]:
    return asyncssh.generate_private_key('ssh-ed25519'), asyncssh.generate_private_key(
        'ssh-ed25519'
    )


def _gate_on(monkeypatch: pytest.MonkeyPatch, call_audit: CallAuditSetting) -> None:
    """Probes on; controller and SSH credentials exported; the call log as given."""
    _use(monkeypatch, ServerSettings(active_probes=True, call_audit=call_audit))
    monkeypatch.setenv('UNIFI_URL', f'https://{GATEWAY}')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)
    monkeypatch.setenv('UNIFI_SSH_PASSWORD', PASSWORD)


@pytest.fixture
def gate_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Probes on; the call log off."""
    _gate_on(monkeypatch, CallAuditSetting('off'))


@pytest.fixture
def gate_on_logged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Probes on; the call log at a known path, returned."""
    log = tmp_path / 'calls.jsonl'
    _gate_on(monkeypatch, CallAuditSetting('path', log))
    return log


def _ssh_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Count every ``asyncssh.connect`` call (and refuse it); the probes must make none."""
    connects: list[tuple[str, dict[str, Any]]] = []

    async def connect(host: str, **options: Any) -> Any:
        connects.append((host, options))
        raise AssertionError('the probe reached asyncssh.connect')

    monkeypatch.setattr(asyncssh, 'connect', connect)
    return connects


@asynccontextmanager
async def _controller_spy(
    monkeypatch: pytest.MonkeyPatch, routes: dict[str, Any] | None = None
) -> AsyncIterator[tuple[FakeController, list[str]]]:
    """A fake controller behind the shared client, plus a count of ``UniFiClient`` entries."""
    entered: list[str] = []
    real_aenter = UniFiClient.__aenter__

    async def aenter(self: UniFiClient) -> Any:
        entered.append(type(self).__name__)
        return await real_aenter(self)

    monkeypatch.setattr(UniFiClient, '__aenter__', aenter)
    controller = FakeController(CONTROLLER_ROUTES if routes is None else routes)
    async with serving(controller):
        yield controller, entered


def _error(out: Any) -> dict[str, Any]:
    envelope = out.structuredContent
    assert out.isError is True and envelope is not None and envelope['ok'] is False, envelope
    return envelope


@asynccontextmanager
async def _gateway(
    monkeypatch: pytest.MonkeyPatch,
    present: asyncssh.SSHKey,
    trusted: asyncssh.SSHKey | None,
    replies: dict[str, Reply],
) -> AsyncIterator[tuple[list[str], list[str], list[str]]]:
    """A real SSH gateway the probes reach through ``asyncssh.connect``, unchanged options.

    The known-hosts file is the default one under ``HOME`` (the test's directory), which is
    where ``gateway_session``'s ``known_hosts=()`` looks; only the socket is injected.
    Yields ``(passwords offered, commands run, hosts connected to)``.
    """
    write_known_hosts(Path(os.environ['HOME']) / '.ssh' / 'known_hosts', trusted, GATEWAY)
    commands: list[str] = []
    hosts: list[str] = []
    async with serve(present, replies, commands) as (sock, attempts):

        async def connect(host: str, **options: Any) -> Any:
            hosts.append(host)
            assert 'sock' not in options and options['known_hosts'] == ()
            return await REAL_CONNECT(host, sock=sock, **options)

        monkeypatch.setattr(asyncssh, 'connect', connect)
        yield attempts, commands, hosts


@asynccontextmanager
async def _controller() -> AsyncIterator[None]:
    async with serving(FakeController(CONTROLLER_ROUTES)):
        yield


def _result(out: Any) -> Any:
    envelope = out.structuredContent
    assert envelope is not None and envelope['ok'] is True, envelope
    return envelope['result']


def _without_clock(value: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k != 'timestamp'}


async def test_the_probes_are_listed_with_their_trust_class(gate_on: None) -> None:
    listed = {tool.name: tool for tool in await server.create_server('direct').list_tools()}
    assert set(PROBES) <= set(listed)
    for name, (program, _) in PROBES.items():
        tool = listed[name]
        assert tool.description is not None
        assert tool.description.startswith(f'Runs {program} on the gateway over SSH: ')
        assert tool.annotations is not None
        a = tool.annotations
        assert (a.readOnlyHint, a.destructiveHint, a.idempotentHint, a.openWorldHint) == (
            False,
            False,
            False,
            True,
        )
        info = await server.get_tool_info(name)
        assert info is not None
        assert info['annotations'] == {
            'title': tool.title,
            'readOnlyHint': False,
            'destructiveHint': False,
            'idempotentHint': False,
            'openWorldHint': True,
        }
        assert info['input_schema'] == tool.inputSchema
    assert {hit['name'] for hit in await server.search_tools(query='gateway ssh')} >= set(PROBES)
    categories = await server.list_categories()
    assert {'gateway_ping', 'gateway_traceroute', 'gateway_dns_check'} <= set(
        categories['connectivity']
    )
    assert 'run_latency_matrix' in categories['analysis']


@pytest.mark.parametrize('name', sorted(PROBES))
async def test_execute_tool_runs_each_probe_as_the_handler_does(
    gate_on: None,
    monkeypatch: pytest.MonkeyPatch,
    host_keys: tuple[asyncssh.SSHKey, asyncssh.SSHKey],
    name: str,
) -> None:
    key, _ = host_keys
    async with _controller():
        async with _gateway(monkeypatch, key, key, REPLIES[name]) as (attempts, commands, hosts):
            out = await server.execute_tool(name, CALLS[name])
        async with _gateway(monkeypatch, key, key, REPLIES[name]):
            direct = await HANDLERS[name](**CALLS[name])
    result = _result(out)
    assert attempts == [PASSWORD]  # the key was trusted, then the password sent once
    assert hosts == [GATEWAY]
    assert commands and all(c.split()[0] == PROBES[name][0] for c in commands)
    expected = json.loads(json.dumps(_to_jsonable(direct)))
    if name == 'run_latency_matrix':
        assert _without_clock(result) == _without_clock(expected)
        assert result['targets_reachable'] == 2
    else:
        assert result == expected


@pytest.mark.parametrize('name', sorted(PLANTED))
async def test_a_planted_ssh_password_never_reaches_a_result(
    gate_on: None,
    monkeypatch: pytest.MonkeyPatch,
    host_keys: tuple[asyncssh.SSHKey, asyncssh.SSHKey],
    name: str,
) -> None:
    key, _ = host_keys
    async with _gateway(monkeypatch, key, key, PLANTED[name]):
        out = await server.execute_tool(name, CALLS[name])
    async with _gateway(monkeypatch, key, key, PLANTED[name]):
        direct = await HANDLERS[name](**CALLS[name])
    assert PASSWORD in json.dumps(direct)  # the plant reached the handler's result...
    _result(out)
    assert PASSWORD not in json.dumps(out.structuredContent)  # ...and MCP masked it
    assert PASSWORD not in out.content[0].text  # type: ignore[union-attr]


async def test_a_planted_ssh_password_never_reaches_an_error(
    gate_on: None, monkeypatch: pytest.MonkeyPatch, host_keys: tuple[asyncssh.SSHKey, ...]
) -> None:
    key = host_keys[0]
    failing: dict[str, Reply] = {'ping': ('', f'ping: {PASSWORD}: permission denied\n', 2)}
    async with _gateway(monkeypatch, key, key, failing):
        out = await server.execute_tool('gateway_ping', CALLS['gateway_ping'])
    envelope = out.structuredContent
    assert envelope is not None and envelope['error_code'] == 'API_ERROR', envelope
    assert 'ping could not run on the gateway (exit status 2)' in envelope['message']
    assert PASSWORD not in json.dumps(envelope)
    assert PASSWORD not in out.content[0].text  # type: ignore[union-attr]


async def test_a_missing_ssh_password_is_config_missing(
    gate_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv('UNIFI_SSH_PASSWORD')
    out = await server.execute_tool('gateway_ping', CALLS['gateway_ping'])
    envelope = out.structuredContent
    assert envelope is not None and envelope['error_code'] == 'CONFIG_MISSING', envelope
    assert 'UNIFI_SSH_PASSWORD' in envelope['message']


async def test_the_direct_surface_runs_a_probe(
    gate_on: None, monkeypatch: pytest.MonkeyPatch, host_keys: tuple[asyncssh.SSHKey, ...]
) -> None:
    key = host_keys[0]
    async with _gateway(monkeypatch, key, key, REPLIES['gateway_ping']) as (attempts, _, _):
        out = await server.create_server('direct').call_tool('gateway_ping', CALLS['gateway_ping'])
    assert out.isError is False
    assert out.structuredContent is not None
    assert out.structuredContent['loss_pct'] == 0.0
    assert attempts == [PASSWORD]


def test_an_active_probe_is_never_annotated_read_only() -> None:
    # Whatever the entry's other keys say, a probe sends traffic from the gateway.
    meta = ToolMetadata(
        'probe', 'm', 'h', 'd', 'c', active_probe=True, open_world=False, idempotent=True
    )
    a = annotations_for(meta)
    assert (a.readOnlyHint, a.destructiveHint, a.idempotentHint, a.openWorldHint) == (
        False,
        False,
        False,
        True,
    )


# ---------------------------------------------------------------------------
# Host-key refusal (issue 038) through execute_tool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('trusted', ['nothing', 'another key'])
async def test_an_untrusted_host_key_is_the_038_error_and_no_password_is_sent(
    gate_on: None,
    monkeypatch: pytest.MonkeyPatch,
    host_keys: tuple[asyncssh.SSHKey, asyncssh.SSHKey],
    trusted: str,
) -> None:
    key, other = host_keys
    known = None if trusted == 'nothing' else other
    async with _gateway(monkeypatch, key, known, REPLIES['gateway_ping']) as (attempts, cmds, _):
        out = await server.execute_tool('gateway_ping', CALLS['gateway_ping'])
    envelope = out.structuredContent
    assert out.isError is True and envelope is not None
    assert envelope['error_code'] == 'CONTROLLER_UNREACHABLE', envelope
    assert f'SSH connection to {USER}@{GATEWAY} refused' in envelope['message']
    assert 'the password was not sent' in envelope['message']
    assert f'Connect once with `ssh {USER}@{GATEWAY}` to record the key' in envelope['suggestion']
    assert attempts == [] and cmds == []


# ---------------------------------------------------------------------------
# Catalog rule: only a probe module's read can carry the flag
# ---------------------------------------------------------------------------

PROBE_MODULES = frozenset(
    {
        'unifi_mapper.connectivity.gateway_probe',
        'unifi_mapper.analysis.latency_matrix',
        'unifi_mapper.diagnostics.client_connectivity',
    }
)


def active_probe_rule_problems(registry: ToolRegistry) -> list[str]:
    """Every way an ``active_probe`` entry breaks the issue 092 catalog rule, one line each."""
    problems = []
    for name, meta in sorted(registry.held_active_probes().items()):
        if meta.writes_local:
            problems.append(f'{name}: an active probe must not write a local file')
        if _names_a_write(name):
            problems.append(f'{name}: an active probe must not carry a writer name')
        if meta.module not in PROBE_MODULES:
            problems.append(f'{name}: {meta.module} is not a gateway probe module')
        if not server.PROBE_DESCRIPTION.match(meta.description):
            problems.append(f'{name}: description must begin "Runs <command> on the gateway"')
    return problems


def test_the_shipped_probes_keep_the_catalog_rule() -> None:
    assert active_probe_rule_problems(ToolRegistry(strict=True)) == []


def test_the_catalog_rule_catches_a_probe_that_is_not_one(tmp_path: Path) -> None:
    (tmp_path / 'x.yaml').write_text(
        'category: analysis\ntools:\n'
        '  set_thing:\n    module: unifi_mapper.analysis.poe_budget\n    title: T\n'
        '    active_probe: true\n    writes_local: true\n    description: Sets a thing\n'
    )
    assert active_probe_rule_problems(ToolRegistry(tmp_path, strict=True)) == [
        'set_thing: an active probe must not write a local file',
        'set_thing: an active probe must not carry a writer name',
        'set_thing: unifi_mapper.analysis.poe_budget is not a gateway probe module',
        'set_thing: description must begin "Runs <command> on the gateway"',
    ]


@pytest.mark.parametrize('name', sorted(PROBES))
def test_a_probe_declares_exactly_its_handlers_parameters(name: str) -> None:
    # test_manifest_parity's rule 2, which a default (holding) registry does not reach.
    meta = ToolRegistry(strict=True).held_active_probes()[name]
    signature = inspect.signature(HANDLERS[name])
    assert set(meta.parameters) == set(signature.parameters)
    for parameter, spec in meta.parameters.items():
        required = signature.parameters[parameter].default is inspect.Parameter.empty
        assert bool(spec.get('required')) is required, parameter
        if not required:
            assert spec.get('default') == signature.parameters[parameter].default, parameter


# ---------------------------------------------------------------------------
# Council pass A: the refusal touches nothing; writers stay refused; validators run first
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('name', sorted(PROBES))
async def test_a_refusal_opens_no_ssh_session_and_asks_the_controller_nothing(
    gate_off: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    connects = _ssh_spy(monkeypatch)
    monkeypatch.setenv('UNIFI_URL', f'https://{GATEWAY}')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)
    monkeypatch.setenv('UNIFI_SSH_PASSWORD', PASSWORD)
    async with _controller_spy(monkeypatch) as (controller, entered):
        envelope = _error(await server.execute_tool(name, CALLS[name]))
    assert envelope['error_code'] == 'ACTIVE_PROBES_DISABLED'
    assert connects == []
    assert controller.calls == [] and entered == []


async def test_a_mutating_tool_stays_refused_with_the_gate_on(
    gate_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    connects = _ssh_spy(monkeypatch)
    for name in ('apply_stp_changes', 'apply_radio_optimization', 'restore_radio_config'):
        envelope = _error(await server.execute_tool(name, {}))
        assert envelope['error_code'] == 'MUTATION_REFUSED', envelope
    listed = _names(await server.create_server('direct').list_tools())
    assert not listed & {'apply_stp_changes', 'apply_radio_optimization', 'restore_radio_config'}
    assert connects == []


# Each row drives one require_* check through execute_tool and the runner. The expected code
# is the handler's own; the probe must fail before asyncssh.connect and run no command.
VALIDATOR_CASES: list[tuple[str, dict[str, Any], str, str]] = [
    # a shell metacharacter in a target: not an address, looked up as a name, nothing matches
    ('gateway_ping', {'target': '192.0.2.10; reboot'}, 'DEVICE_NOT_FOUND', 'metacharacter'),
    # a leading-option target: likewise never reaches a command line
    ('gateway_ping', {'target': '-c 9999'}, 'DEVICE_NOT_FOUND', 'leading option'),
    # the same two shapes where the value goes on the command line directly (require_hostname)
    ('gateway_dns_check', {'hostname': 'example.com; reboot'}, 'CONFIG_INVALID', 'metachar'),
    ('gateway_dns_check', {'hostname': '-f'}, 'CONFIG_INVALID', 'leading option'),
    ('gateway_dns_check', {'hostname': 'example.com', 'server': '1.2.3.4 -x'}, 'INVALID_IP', 'x'),
    # bounds (require_bounded_int / require_bounded_float)
    ('gateway_ping', {'target': '192.0.2.10', 'count': 101}, 'CONFIG_INVALID', 'count'),
    ('gateway_ping', {'target': '192.0.2.10', 'interval': 0.1}, 'CONFIG_INVALID', 'interval'),
    ('gateway_traceroute', {'target': '192.0.2.10', 'max_hops': 31}, 'CONFIG_INVALID', 'hops'),
    ('run_latency_matrix', {'ping_count': 101}, 'CONFIG_INVALID', 'ping_count'),
    ('run_latency_matrix', {'timeout': 61}, 'CONFIG_INVALID', 'timeout'),
]


@pytest.mark.parametrize(
    ('name', 'params', 'code', 'kind'), VALIDATOR_CASES, ids=[c[3] for c in VALIDATOR_CASES]
)
async def test_a_validator_refuses_before_any_ssh_connect(
    gate_on: None,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    params: dict[str, Any],
    code: str,
    kind: str,
) -> None:
    connects = _ssh_spy(monkeypatch)
    empty = {f'{API}/stat/device': legacy([]), f'{API}/stat/sta': legacy([])}
    async with _controller_spy(monkeypatch, empty) as (controller, _):
        envelope = _error(await server.execute_tool(name, params))
    assert envelope['error_code'] == code, envelope
    assert connects == []
    # Only a name lookup may ask the controller, and only for reads.
    assert controller.methods <= {'GET'}


async def test_a_controller_reported_address_is_checked_before_the_command_line(
    gate_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A name matches a client whose address the controller reports with a shell
    # metacharacter: require_ip refuses it; no SSH session is opened.
    connects = _ssh_spy(monkeypatch)
    routes = {
        f'{API}/stat/device': legacy([]),
        f'{API}/stat/sta': legacy(
            [{'hostname': 'printer', 'mac': '02:00:00:00:00:03', 'ip': '192.0.2.40; reboot'}]
        ),
    }
    async with _controller_spy(monkeypatch, routes):
        envelope = _error(await server.execute_tool('gateway_ping', {'target': 'printer'}))
    assert envelope['error_code'] == 'INVALID_IP', envelope
    assert connects == []


async def test_the_runner_rejects_a_wrong_type_before_the_handler(
    gate_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    connects = _ssh_spy(monkeypatch)
    envelope = _error(
        await server.execute_tool('gateway_ping', {'target': '192.0.2.10', 'count': 'x'})
    )
    assert envelope['error_code'] == 'INVALID_PARAMETERS'
    assert connects == []


# ---------------------------------------------------------------------------
# Council pass A: the planted password reaches none of the four outputs; the deadline
# ---------------------------------------------------------------------------


@pytest.fixture
def loguru_lines() -> list[str]:
    """Every loguru line at DEBUG and above, as rendered (message plus the record's text)."""
    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(str(m)), level='DEBUG', format='{level} {message}')
    yield seen
    logger.remove(sink)


@pytest.mark.parametrize(
    ('name', 'replies', 'outcome'),
    [
        ('gateway_traceroute', PLANTED['gateway_traceroute'], 'ok'),
        ('gateway_dns_check', PLANTED['gateway_dns_check'], 'ok'),
        ('gateway_ping', {'ping': ('', f'ping: {PASSWORD}: permission denied\n', 2)}, 'API_ERROR'),
    ],
    ids=['traceroute result', 'dns result', 'ping error'],
)
async def test_a_planted_ssh_password_reaches_no_result_error_log_line_or_audit_record(
    gate_on_logged: Path,
    monkeypatch: pytest.MonkeyPatch,
    host_keys: tuple[asyncssh.SSHKey, asyncssh.SSHKey],
    loguru_lines: list[str],
    name: str,
    replies: dict[str, Reply],
    outcome: str,
) -> None:
    key = host_keys[0]
    async with _gateway(monkeypatch, key, key, replies):
        out = await server.execute_tool(name, CALLS[name])
    envelope = out.structuredContent
    assert envelope is not None
    assert (envelope.get('error_code') or 'ok') == outcome, envelope
    # 1 the structured result or error, 2 the text block
    assert PASSWORD not in json.dumps(envelope)
    assert PASSWORD not in out.content[0].text  # type: ignore[union-attr]
    # 3 every loguru line the call produced (a success logs none; the failed run logs its code)
    if outcome != 'ok':
        assert any(f'MCP tool {name} returned {outcome}' in line for line in loguru_lines)
    assert all(PASSWORD not in line for line in loguru_lines), loguru_lines
    # 4 the call-audit record
    records = gate_on_logged.read_text(encoding='utf-8')
    assert PASSWORD not in records
    [line] = [json.loads(raw) for raw in records.splitlines()]
    assert (line['tool'], line['outcome']) == (name, outcome)
    assert set(line) & {'result', 'message', 'params', 'arguments', 'values'} == set()


async def test_a_probe_finishes_well_inside_the_ordinary_deadline(
    gate_on: None, monkeypatch: pytest.MonkeyPatch, host_keys: tuple[asyncssh.SSHKey, ...]
) -> None:
    # The probes run under the same per-call deadline as every tool, 270 s by default; a
    # fake-gateway round trip takes a fraction of a second, so a [TIMEOUT] would mean an
    # outage or a stalled gateway, not the probe's own length.
    assert server.current_settings().tool_timeout == 270.0
    assert server.get_runner().settings.tool_timeout == 270.0
    key = host_keys[0]
    started = time.monotonic()
    async with _gateway(monkeypatch, key, key, REPLIES['gateway_ping']):
        out = await server.execute_tool('gateway_ping', CALLS['gateway_ping'])
    elapsed = time.monotonic() - started
    _result(out)
    assert elapsed < 10, elapsed


async def test_a_probe_failure_text_holding_the_password_is_masked_in_the_log_line(
    gate_on_logged: Path,
    monkeypatch: pytest.MonkeyPatch,
    host_keys: tuple[asyncssh.SSHKey, asyncssh.SSHKey],
    loguru_lines: list[str],
) -> None:
    # A TOOL_FAILED is the one outcome whose stderr line carries the exception's text (and,
    # at DEBUG, its traceback): force one whose text holds the planted password.
    from unifi_mapper.connectivity import gateway_probe

    def blow_up(output: str) -> Any:
        raise RuntimeError(f'parser failed on {PASSWORD}')

    monkeypatch.setattr(gateway_probe, 'parse_traceroute_output', blow_up)
    key = host_keys[0]
    async with _gateway(monkeypatch, key, key, REPLIES['gateway_traceroute']):
        out = await server.execute_tool('gateway_traceroute', CALLS['gateway_traceroute'])
    envelope = _error(out)
    assert envelope['error_code'] == 'TOOL_FAILED'
    assert envelope['message'].startswith('RuntimeError: parser failed on ')
    assert PASSWORD not in json.dumps(envelope)
    failed = [line for line in loguru_lines if 'MCP tool gateway_traceroute failed' in line]
    assert failed, loguru_lines
    assert all(PASSWORD not in line for line in loguru_lines), loguru_lines
    assert PASSWORD not in gate_on_logged.read_text(encoding='utf-8')
