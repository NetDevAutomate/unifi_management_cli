"""Site-wide recent events: the collector, the MCP tool and ``controller events``.

The collector reuses the device-scoped readers of ``port_history``, so these tests drive it
over the same in-memory controller (``tests/fixtures_unifi``) through a real
``UnifiApiClient`` behind the read-only guard. No test reaches a network.
"""

import json
import pytest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tests.fixtures_unifi import (
    FAKE_EVENT_SECRET,
    NOW,
    SITE,
    FakeSession,
    default_routes,
    fake_client,
)
from typer.testing import CliRunner
from typing import Any
from unifi_mapper import typer_cli
from unifi_mapper.core.utils.readonly import install_read_only_guard
from unifi_mapper.diagnostics import port_diagnostics_tools
from unifi_mapper.mcp.config import ServerSettings
from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir
from unifi_mapper.mcp.runner import ToolRunner
from unifi_mapper.port_history import (
    RecentEvents,
    collect_recent_events,
    validate_recent_window,
)
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()
HOUR_MS = 3_600_000


def _guarded_client(**routes: Any) -> tuple[Any, FakeSession]:
    session = FakeSession(default_routes(**routes))
    client = fake_client(session)
    install_read_only_guard(client)
    return client, session


def _recent(client: Any, **kwargs: Any) -> RecentEvents:
    return collect_recent_events(client, SITE, now=lambda: NOW, **kwargs)


def _alarms(*stamps: Any) -> dict[str, Any]:
    alarms = [
        {'_id': f'al{i}', 'key': 'EVT_AP_Lost_Contact', 'msg': 'AP 1 lost contact'}
        for i in range(len(stamps))
    ]
    for alarm, stamp in zip(alarms, stamps, strict=True):
        if stamp is not None:
            alarm['time'] = stamp
    return {'data': alarms}


# The only POSTs the collector may send: the read-shaped queries of stat/event and the four
# v2 system-log classes. Pinned by (method, path) (issue 076 item 18): a method-only check
# would let a POST to any other path through as long as it was a POST.
READ_POSTS = frozenset(
    {
        ('POST', f'/proxy/network/api/s/{SITE}/stat/event'),
        *(
            ('POST', f'/proxy/network/v2/api/site/{SITE}/system-log/{cls}')
            for cls in ('device-alert', 'admin-activity', 'update-alert', 'client-alert')
        ),
    }
)


def _assert_reads_only(calls: list[dict[str, Any]]) -> None:
    """Every call is a GET, or one of the read-shaped POSTs the collector is allowed."""
    for call in calls:
        assert call['method'] == 'GET' or (call['method'], call['path']) in READ_POSTS, call


def test_the_post_pin_refuses_a_post_to_any_other_path() -> None:
    with pytest.raises(AssertionError):
        _assert_reads_only([{'method': 'POST', 'path': f'/proxy/network/api/s/{SITE}/cmd/devmgr'}])
    _assert_reads_only([{'method': 'GET', 'path': '/anything'}])


# --- the window ---------------------------------------------------------------------------


def test_one_hour_asks_for_one_hour_from_every_source() -> None:
    client, session = _guarded_client()
    recent = _recent(client, since_hours=1)
    [stat_event] = [c for c in session.calls if c['path'].endswith('/stat/event')]
    assert stat_event['json']['within'] == 1
    logs = [c for c in session.calls if '/system-log/' in c['path']]
    assert len(logs) == 4
    assert {c['json']['timestampTo'] - c['json']['timestampFrom'] for c in logs} == {HOUR_MS}
    assert recent.window.since_hours == 1
    _assert_reads_only(session.calls)
    assert {(c['method'], c['path']) for c in session.calls} >= READ_POSTS  # every source asked


def test_alarms_outside_the_window_are_dropped_and_undated_ones_kept() -> None:
    inside, outside = (NOW - 60) * 1000, (NOW - 2 * 3600) * 1000
    client, _ = _guarded_client(alarms=_alarms(inside, outside, None))
    recent = _recent(client, since_hours=1)
    alarm_ids = [e.raw['_id'] for e in recent.events if e.source == 'alarms']
    assert sorted(alarm_ids) == ['al0', 'al2']
    assert recent.sources.alarms.records_returned == 3 and recent.sources.alarms.matched == 2


@pytest.mark.parametrize(
    ('since_hours', 'max_events'), [(0, 100), (8761, 100), (24, 0), (24, 1001)]
)
def test_the_window_validator_refuses_out_of_range_bounds(
    since_hours: int, max_events: int
) -> None:
    with pytest.raises(ValueError):
        validate_recent_window(since_hours, max_events)
    client, session = _guarded_client()
    with pytest.raises(ValueError):
        _recent(client, since_hours=since_hours, max_events=max_events)
    assert session.calls == []  # validated before any request


def test_the_largest_window_and_cap_are_accepted() -> None:
    validate_recent_window(8760, 1000)
    validate_recent_window(1, 1)


# --- normalisation, filters, order and secrets ---------------------------------------------


def test_entries_are_site_wide_newest_first_with_secrets_removed() -> None:
    client, _ = _guarded_client()
    recent = _recent(client, since_hours=24 * 30)
    stamps = [e.epoch_ms for e in recent.events]
    assert stamps == sorted(stamps, key=lambda s: s or 0, reverse=True)
    sources = {e.source for e in recent.events}
    assert {'stat_event', 'system_log.admin-activity', 'system_log.device-alert'} <= sources
    assert any(e.key == 'EVT_AP_Connected' for e in recent.events)  # no device filter
    dumped = json.dumps(recent.to_json_dict())
    assert FAKE_EVENT_SECRET not in dumped
    assert any(path.endswith('.x_internal') for path in recent.sanitised_paths)


def test_category_severity_and_text_filters() -> None:
    log = {
        'data': [
            {
                'id': 's1',
                'timestamp': (NOW - 60) * 1000,
                'key': 'K1',
                'category': 'Security',
                'severity': 'HIGH',
                'message': 'Blocked a threat',
            },
            {
                'id': 's2',
                'timestamp': (NOW - 120) * 1000,
                'key': 'K2',
                'category': 'System',
                'severity': 'low',
                'message': 'Backup done',
            },
        ],
        'totalElements': 2,
    }
    client, _ = _guarded_client(
        system_log=lambda path, **_: log
        if 'device-alert' in path
        else {'data': [], 'totalElements': 0}
    )
    by_category = _recent(client, since_hours=1, category='security')
    assert [e.key for e in by_category.events] == ['K1']
    assert by_category.events[0].severity == 'HIGH'
    assert [e.key for e in _recent(client, since_hours=1, severity='LOW').events] == ['K2']
    assert [e.key for e in _recent(client, since_hours=1, contains='backup').events] == ['K2']


def test_the_newest_entries_survive_the_cap() -> None:
    client, _ = _guarded_client()
    everything = _recent(client, since_hours=24 * 30)
    capped = _recent(client, since_hours=24 * 30, max_events=2)
    assert [e.epoch_ms for e in capped.events] == [e.epoch_ms for e in everything.events[:2]]
    assert capped.truncated is True and capped.matched_total == everything.matched_total


def test_a_source_the_controller_lacks_is_reported_not_fatal() -> None:
    client, _ = _guarded_client(alarms=(404, {'meta': {'rc': 'error'}}))
    recent = _recent(client, since_hours=24)
    assert recent.sources.alarms.status == 'unavailable'
    assert recent.sources.stat_event.status == 'ok'


# --- the MCP tool ---------------------------------------------------------------------------


@pytest.fixture
def sync_client(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    """Serve the MCP tool's read-only sync client from the in-memory controller."""
    client, session = _guarded_client()

    @contextmanager
    def _fake() -> Iterator[tuple[Any, str]]:
        yield client, SITE

    monkeypatch.setattr(port_diagnostics_tools, '_readonly_sync_client', _fake)
    return session


async def test_get_recent_events_returns_the_collector_s_json(sync_client: FakeSession) -> None:
    out = await port_diagnostics_tools.get_recent_events(since_hours=720, max_events=3)
    assert out['returned'] == 3 and out['window']['since_hours'] == 720
    assert FAKE_EVENT_SECRET not in json.dumps(out)
    _assert_reads_only(sync_client.calls)


@pytest.mark.parametrize(
    'params', [{'since_hours': 0}, {'since_hours': 8761}, {'max_events': 1001}]
)
async def test_out_of_range_parameters_are_refused_before_the_handler(
    sync_client: FakeSession, params: dict[str, Any]
) -> None:
    tool_runner = ToolRunner(ToolRegistry(default_manifests_dir()), settings=ServerSettings())
    out = (await tool_runner.run('get_recent_events', params)).structuredContent
    assert out is not None and out['error_code'] == 'INVALID_PARAMETERS'
    assert sync_client.calls == []


# --- controller events --------------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    """Run `controller events` against the in-memory controller; load no config."""
    client, session = _guarded_client()

    @contextmanager
    def _fake() -> Iterator[tuple[Any, str]]:
        yield client, SITE

    monkeypatch.setattr(typer_cli, '_readonly_client', _fake)
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    return session


def test_controller_events_prints_json_and_tables(cli: FakeSession) -> None:
    as_json = runner.invoke(app, ['controller', 'events', '--since-hours', '720', '--json'])
    assert as_json.exit_code == 0, as_json.output
    data = json.loads(as_json.stdout)
    assert data['window']['since_hours'] == 720 and data['returned'] > 0
    table = runner.invoke(app, ['controller', 'events', '--since-hours', '720'])
    assert table.exit_code == 0, table.output
    flat = ' '.join(table.stdout.split())
    assert 'Window:' in flat and 'Sources (earliest' in flat and 'Entries (' in flat
    for result in (as_json, table):
        assert FAKE_EVENT_SECRET not in result.output


@pytest.mark.parametrize(
    'args', [['--since-hours', '0'], ['--since-hours', '8761'], ['--max-events', '1001']]
)
def test_bad_bounds_exit_2_before_connecting(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    opened: list[bool] = []

    @contextmanager
    def _never() -> Iterator[tuple[None, str]]:
        opened.append(True)
        yield None, SITE

    monkeypatch.setattr(typer_cli, '_readonly_client', _never)
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    result = runner.invoke(app, ['controller', 'events', *args])
    assert result.exit_code == 2, result.output
    assert 'must be between' in result.stderr
    assert opened == []


def test_a_reader_failure_is_one_redacted_error_line(
    monkeypatch: pytest.MonkeyPatch, cli: FakeSession
) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(f'reader broke, token={FAKE_EVENT_SECRET}')

    monkeypatch.setattr('unifi_mapper.port_history._read_alarms', _boom)
    result = runner.invoke(app, ['controller', 'events'])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)  # a clean exit, not Typer's traceback
    assert 'Error: reader broke, token=***redacted***' in ' '.join(result.stderr.split())
    assert FAKE_EVENT_SECRET not in result.output


def test_controller_events_has_help() -> None:
    result = runner.invoke(app, ['controller', 'events', '--help'])
    assert result.exit_code == 0
    assert 'Read-only' in ' '.join(result.output.split())


def test_this_package_resolves_no_real_config(tmp_path: Path) -> None:
    from unifi_mapper.cli import get_default_config_path

    assert not get_default_config_path().exists()
    assert Path.cwd() == tmp_path
