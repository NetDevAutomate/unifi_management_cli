"""Tests for the read-only port diagnostic MCP tools (no live controller)."""

import importlib
import inspect
import json
import pytest
import yaml
from contextlib import contextmanager
from pathlib import Path
from tests.fixtures_unifi import (
    API,
    NAS_MAC,
    NOW,
    PROFILE_10G_NAME,
    PROFILE_AUTO_NAME,
    SITE,
    SWITCH_MAC,
    SWITCH_NAME,
    FakeSession,
    assert_no_secrets,
    default_routes,
    fake_client,
)
from unifi_mapper.core.utils.readonly import ReadOnlySession, install_read_only_guard
from unifi_mapper.diagnostics import port_diagnostics_tools as tools
from unifi_mapper.mcp import server
from unifi_mapper.mcp.registry import ToolRegistry


pytestmark = pytest.mark.usefixtures('block_network')

MANIFESTS = Path(server.__file__).parent / 'manifests'
NEW_TOOLS = {
    'diagnose_switch_port': 'diagnostics',
    'get_switch_ports': 'diagnostics',
    'diff_port_profiles': 'diagnostics',
    'get_client_history': 'discovery',
    'get_device_events': 'observability',
    'get_port_counter_rates': 'observability',
}


@pytest.fixture(scope='module')
def registry() -> ToolRegistry:
    return ToolRegistry(MANIFESTS)


def _envelope(out):
    """Return execute_tool's envelope (its structuredContent)."""
    return out.structuredContent


@pytest.fixture
def fake_controller(monkeypatch):
    """Point every tool at an in-memory controller instead of the env credentials."""
    # Fake controller env so the MCP credential gate passes before the patched client.
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', 'FAKE-GATE-TOKEN')  # pragma: allowlist secret
    session = FakeSession(default_routes())
    client = fake_client(session)
    install_read_only_guard(client)

    @contextmanager
    def fake_readonly_sync_client():
        yield client, SITE

    monkeypatch.setattr(tools, '_readonly_sync_client', fake_readonly_sync_client)
    monkeypatch.setattr(server, 'get_registry', lambda: ToolRegistry(MANIFESTS))
    return client, session


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(('name', 'category'), sorted(NEW_TOOLS.items()))
def test_manifest_parameters_match_the_handler_signature(registry, name, category):
    meta = registry.get_metadata(name)
    assert meta is not None and meta.category == category
    handler = getattr(importlib.import_module(meta.module), meta.handler)
    signature = inspect.signature(handler).parameters
    assert list(meta.parameters) == list(signature)
    for param, spec in meta.parameters.items():
        has_default = signature[param].default is not inspect.Parameter.empty
        assert bool(spec.get('required')) is not has_default, param
    assert meta.mutates is False


@pytest.mark.parametrize('name', sorted(NEW_TOOLS))
def test_manifest_descriptions_use_folded_blocks(name):
    text = (MANIFESTS / f'{NEW_TOOLS[name]}.yaml').read_text()
    after = text.split(f'\n  {name}:\n', 1)[1]
    first = next(line for line in after.splitlines() if line.strip().startswith('description:'))
    assert first.strip() == 'description: >-'
    assert yaml.safe_load(text)['tools'][name]['description']


def test_registry_totals(registry):
    categories = registry.get_categories()
    assert len(registry) == 87
    assert len(categories['analysis']) == 49
    assert len(categories['diagnostics']) == 11
    assert len(categories['discovery']) == 5
    assert len(categories['observability']) == 7


# ---------------------------------------------------------------------------
# Execution through execute_tool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('name', 'params', 'key'),
    [
        ('get_switch_ports', {'switch': SWITCH_NAME}, 'ports'),
        (
            'diff_port_profiles',
            {'profile_a': PROFILE_10G_NAME, 'profile_b': PROFILE_AUTO_NAME},
            'differences',
        ),
        ('get_client_history', {'client': NAS_MAC, 'switch': SWITCH_NAME, 'port': 5}, 'records'),
        ('get_device_events', {'device': SWITCH_NAME, 'port': 5, 'clients': [NAS_MAC]}, 'matched'),
        ('get_port_counter_rates', {'switch': SWITCH_NAME, 'port': 5, 'samples': 1}, 'verdict'),
        ('diagnose_switch_port', {'switch': SWITCH_NAME, 'port': 5}, 'request_audit'),
    ],
)
async def test_execute_tool_runs_each_tool_read_only(fake_controller, name, params, key):
    client, session = fake_controller
    raw = await server.execute_tool(name, params)
    out = _envelope(raw)
    assert out['ok'] is True, out
    assert key in out['result']
    assert out['result']['schema_version'] == 1
    assert_no_secrets(raw.model_dump(mode='json'))
    assert isinstance(client.session, ReadOnlySession)
    assert {c['method'] for c in session.calls} <= {'GET', 'POST'}


async def test_counter_tools_report_the_recorded_history_and_write_nothing(fake_controller):
    from tests.fixtures_unifi import fake_devices
    from unifi_mapper.analysis.counter_history import (
        append_history,
        build_history_records,
        default_history_path,
    )
    from unifi_mapper.mcp.call_audit import CALL_AUDIT_FILENAME

    # The MCP call log (on by default, issue 013) is the server's own record, written beside
    # the history; this test's point is that the reads leave the history alone.
    call_log = {CALL_AUDIT_FILENAME, f'{CALL_AUDIT_FILENAME}.lock'}

    def _state(directory: Path) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in directory.iterdir() if p.name not in call_log}

    append_history(build_history_records(fake_devices(), taken_at='T', epoch=1.0), now=1.0)
    state = default_history_path().parent
    before = _state(state)

    rates = _envelope(
        await server.execute_tool(
            'get_port_counter_rates', {'switch': SWITCH_NAME, 'port': 5, 'samples': 1}
        )
    )
    bundle = _envelope(
        await server.execute_tool('diagnose_switch_port', {'switch': SWITCH_NAME, 'port': 5})
    )

    for history in (
        rates['result']['baselines']['history'],
        bundle['result']['counters']['baselines']['history'],
    ):
        assert history['found'] is True and history['records'] == 1
        assert 'rx_crc_errors' in history['first_increase']
    assert _state(state) == before


async def test_the_call_log_appears_in_the_state_directory_by_default(
    fake_controller: tuple[object, FakeSession],
) -> None:
    from unifi_mapper.analysis.port_counter_baseline import state_dir
    from unifi_mapper.mcp.call_audit import CALL_AUDIT_FILENAME

    params = {'switch': SWITCH_NAME, 'port': 5, 'samples': 1}
    out = _envelope(await server.execute_tool('get_port_counter_rates', params))
    assert out['ok'] is True, out
    text = (state_dir() / CALL_AUDIT_FILENAME).read_text(encoding='utf-8')
    lines = [json.loads(line) for line in text.splitlines()]
    assert [(line['kind'], line['tool'], line['arg_keys']) for line in lines] == [
        ('call', 'get_port_counter_rates', ['port', 'samples', 'switch'])
    ]
    assert lines[0]['outcome'] == 'ok' and SWITCH_NAME not in text  # keys, never values


async def test_client_history_confirms_the_target_port(fake_controller):
    out = _envelope(
        await server.execute_tool(
            'get_client_history', {'client': NAS_MAC, 'switch': SWITCH_NAME, 'port': 5}
        )
    )
    assert out['result']['records'][0]['matches_target'] is True


@pytest.mark.parametrize(
    ('name', 'params', 'code'),
    [
        ('get_switch_ports', {'switch': 'nope'}, 'DEVICE_NOT_FOUND'),
        ('get_switch_ports', {'switch': 'Flex XG'}, 'DEVICE_NOT_FOUND'),
        (
            'get_port_counter_rates',
            {'switch': SWITCH_NAME, 'port': 9, 'samples': 1},
            'INVALID_PORT',
        ),
        ('diagnose_switch_port', {'switch': SWITCH_NAME, 'port': 9}, 'INVALID_PORT'),
        (
            'diff_port_profiles',
            {'profile_a': 'Nope', 'profile_b': PROFILE_AUTO_NAME},
            'PROFILE_NOT_FOUND',
        ),
        (
            'get_port_counter_rates',
            {'switch': SWITCH_NAME, 'port': 5, 'samples': 9},
            'CONFIG_INVALID',
        ),
        ('get_device_events', {'device': SWITCH_NAME, 'since_days': 0}, 'CONFIG_INVALID'),
        ('get_client_history', {'client': NAS_MAC, 'port': 5}, 'CONFIG_INVALID'),
        (
            'diagnose_switch_port',
            {'switch': SWITCH_NAME, 'port': 5, 'compare_profiles': ['A']},
            'CONFIG_INVALID',
        ),
    ],
)
async def test_failures_come_back_as_specific_error_envelopes(fake_controller, name, params, code):
    out = _envelope(await server.execute_tool(name, params))
    assert out['ok'] is False
    assert out['error_code'] == code, out


async def test_a_refused_write_is_reported_as_read_only_violation(fake_controller, monkeypatch):
    import unifi_mapper.port_diagnostics as module

    def writer(client, site, ctx):
        client.session.put(f'{client.base_url}{API}/rest/device/x', json={})

    monkeypatch.setattr(module, 'collect_controller_info', writer)
    out = _envelope(
        await server.execute_tool('diagnose_switch_port', {'switch': SWITCH_NAME, 'port': 5})
    )
    assert out['ok'] is False
    assert out['error_code'] == 'READ_ONLY_VIOLATION'  # not mislabelled MUTATION_REFUSED


async def test_unknown_parameters_are_rejected_by_the_manifest(fake_controller):
    out = _envelope(
        await server.execute_tool('get_switch_ports', {'switch': SWITCH_NAME, 'colour': 'red'})
    )
    assert out['error_code'] == 'INVALID_PARAMETERS'


async def test_login_failure_is_controller_unreachable(monkeypatch):
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', 'FAKE-TOKEN')  # pragma: allowlist secret
    monkeypatch.setattr('unifi_mapper.api_client.UnifiApiClient.login', lambda self: False)
    out = _envelope(await server.execute_tool('get_switch_ports', {'switch': SWITCH_NAME}))
    assert out['ok'] is False and out['error_code'] == 'CONTROLLER_UNREACHABLE'


# ---------------------------------------------------------------------------
# Fleet audits (analysis.yaml) over the same read-only fake controller
# ---------------------------------------------------------------------------


@pytest.fixture
def frozen_clock(monkeypatch):
    from unifi_mapper.analysis import link_speed_audit

    monkeypatch.setattr(link_speed_audit, '_now', lambda: NOW)


async def test_audit_link_speeds_runs_read_only(fake_controller, frozen_clock):
    client, session = fake_controller
    raw = await server.execute_tool('audit_link_speeds', {'switch': SWITCH_NAME})
    assert raw.isError is False
    out = _envelope(raw)
    assert out['ok'] is True, out
    result = out['result']
    assert result['schema_version'] == 1 and result['validation_passed'] is False
    assert [(f['switch_mac'], f['port_idx'], f['code']) for f in result['findings']] == [
        (SWITCH_MAC, 5, 'FORCED_SPEED_MISMATCH')
    ]
    assert result['integration']['status'] == 'ok'
    assert_no_secrets(raw.model_dump(mode='json'))
    assert isinstance(client.session, ReadOnlySession)
    assert {c['method'] for c in session.calls} == {'GET'}


@pytest.mark.parametrize(
    ('params', 'code'),
    [
        ({'switch': 'nope'}, 'DEVICE_NOT_FOUND'),
        ({'switch': 'Flex XG'}, 'DEVICE_NOT_FOUND'),
        ({'limit': 0}, 'CONFIG_INVALID'),
        ({'offset': -1}, 'CONFIG_INVALID'),
    ],
)
async def test_audit_link_speeds_errors(fake_controller, frozen_clock, params, code):
    raw = await server.execute_tool('audit_link_speeds', params)
    out = _envelope(raw)
    assert raw.isError is True and out['ok'] is False
    assert out['error_code'] == code, out


async def test_audit_port_profile_usage_runs_read_only(fake_controller):
    client, session = fake_controller
    raw = await server.execute_tool('audit_port_profile_usage', {'profile': PROFILE_10G_NAME})
    assert raw.isError is False
    out = _envelope(raw)
    assert out['ok'] is True, out
    result = out['result']
    assert result['schema_version'] == 1
    assert [p['name'] for p in result['profiles']] == [PROFILE_10G_NAME]
    assert [f['code'] for f in result['findings']] == ['FORCED_SPEED_PROFILE']
    assert_no_secrets(raw.model_dump(mode='json'))
    assert isinstance(client.session, ReadOnlySession)
    assert {c['method'] for c in session.calls} == {'GET'}


@pytest.mark.parametrize(
    ('params', 'code'),
    [({'profile': 'Nope'}, 'PROFILE_NOT_FOUND'), ({'limit': 1001}, 'CONFIG_INVALID')],
)
async def test_audit_port_profile_usage_errors(fake_controller, params, code):
    raw = await server.execute_tool('audit_port_profile_usage', params)
    out = _envelope(raw)
    assert raw.isError is True and out['error_code'] == code, out
