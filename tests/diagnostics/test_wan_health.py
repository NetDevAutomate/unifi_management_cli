"""WAN health from ``stat/health`` and ``diagnose wan [--record]``.

Ported from the prototype (a local archive, not in the repo) and adapted: documentation
addresses only, no speedtest trigger (a controller command the port does not build), and
every controller read driven through the real read-only guard over
``tests/fake_controller.py``, so each test can assert that only GETs left the host.
"""

import inspect
import json
import os
import pytest
from pathlib import Path
from tests.fake_controller import API, FakeController, legacy, route_cli, serving
from typer.testing import CliRunner
from typing import Any
from unifi_mapper.diagnostics.wan_health import build_wan_health, get_wan_health
from unifi_mapper.diagnostics.wan_history import (
    default_speedtest_history_path,
    read_speedtest_history,
)
from unifi_mapper.typer_cli import app


runner = CliRunner()
RUN_EPOCH = 1_790_000_000

HEALTH = [
    {
        'subsystem': 'wan',
        'status': 'ok',
        'isp_name': 'Example ISP',
        'isp_organization': 'Example Org',
        'wan_ip': '203.0.113.10',
        'nameservers': ['198.51.100.53'],
        'gw_version': '4.0.0',
        'uptime': '123456',
    },
    {
        'subsystem': 'www',
        'status': 'ok',
        'latency': '12',
        'uptime': 123456,
        'drops': 0,
        'xput_up': 107.0,
        'xput_down': '1050.5',
        'speedtest_status': 'Success',
        'speedtest_lastrun': RUN_EPOCH,
        'speedtest_ping': 8.5,
        'rx_bytes-r': 1000,
        'tx_bytes-r': 2000,
    },
    {'subsystem': 'lan', 'status': 'ok'},
]


def _without(subsystem: str) -> list[dict[str, Any]]:
    return [dict(s) for s in HEALTH if s['subsystem'] != subsystem]


def _www(**over: Any) -> list[dict[str, Any]]:
    rows = [dict(s) for s in HEALTH]
    for row in rows:
        if row['subsystem'] == 'www':
            row.update(over)
            for key, value in over.items():
                if value is None:
                    row.pop(key)
    return rows


# --- build_wan_health ----------------------------------------------------------------------


def test_the_summary_reads_both_subsystems_and_coerces_numbers() -> None:
    result = build_wan_health(HEALTH)
    assert result['wan']['isp_name'] == 'Example ISP' and result['wan']['uptime'] == 123456
    assert result['www']['latency_ms'] == 12.0 and result['www']['drops'] == 0
    assert result['healthy'] is True
    assert result['last_speedtest'] == {
        'run_epoch': RUN_EPOCH,
        'up_mbps': 107.0,
        'down_mbps': 1050.5,
        'ping_ms': 8.5,
        'status': 'Success',
    }
    assert any('nothing here starts one' in note for note in result['notes'])


def test_a_missing_or_failing_subsystem_is_unhealthy() -> None:
    assert build_wan_health(_without('wan'))['healthy'] is False
    assert build_wan_health(_www(status='error'))['healthy'] is False
    empty = build_wan_health([])
    assert (empty['wan']['status'], empty['last_speedtest'], empty['healthy']) == (
        None,
        None,
        False,
    )
    assert build_wan_health('not a list')['healthy'] is False


def test_no_speedtest_in_the_payload_gives_none() -> None:
    rows = _www(speedtest_status=None, xput_up=None, xput_down=None)
    assert build_wan_health(rows)['last_speedtest'] is None


# --- get_wan_health, through the read-only guard --------------------------------------------


async def test_get_wan_health_sends_one_get() -> None:
    controller = FakeController({f'{API}/stat/health': legacy(HEALTH)})
    async with serving(controller):
        result = await get_wan_health()
    assert result['healthy'] is True
    assert controller.reads == [('GET', f'{API}/stat/health')]
    assert controller.methods == {'GET'}


def test_get_wan_health_is_a_coroutine_function() -> None:
    assert inspect.iscoroutinefunction(get_wan_health)


# --- diagnose wan [--record] --------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeController:
    """Route `diagnose wan` to a fake controller; XDG state under tmp_path."""
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    controller = FakeController({f'{API}/stat/health': legacy(HEALTH)})
    route_cli(monkeypatch, controller)
    return controller


def test_diagnose_wan_prints_a_table_and_json(cli: FakeController) -> None:
    table = runner.invoke(app, ['diagnose', 'wan'])
    assert table.exit_code == 0, table.output
    assert 'Example ISP' in table.stdout and '1050.5' in table.stdout
    as_json = runner.invoke(app, ['diagnose', 'wan', '--json'])
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.stdout)['healthy'] is True
    assert not default_speedtest_history_path().exists()  # nothing written without --record
    assert cli.methods == {'GET'}


def test_record_appends_once_per_run_under_xdg_state(cli: FakeController) -> None:
    first = runner.invoke(app, ['diagnose', 'wan', '--record', '--json'])
    assert first.exit_code == 0, first.output
    assert json.loads(first.stdout)['healthy'] is True  # stdout stays JSON
    assert 'Recorded the speedtest' in first.stderr
    second = runner.invoke(app, ['diagnose', 'wan', '--record'])
    assert second.exit_code == 0, second.output
    assert 'Already recorded' in second.stderr
    path = default_speedtest_history_path()
    assert path.parent == Path(os.environ['XDG_STATE_HOME']) / 'unifi_mapper'
    assert read_speedtest_history()['total'] == 1
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert cli.reads == [('GET', f'{API}/stat/health')] * 2
    assert cli.methods == {'GET'}


def test_record_without_a_speedtest_says_nothing_to_record(
    monkeypatch: pytest.MonkeyPatch, cli: FakeController
) -> None:
    cli.routes[f'{API}/stat/health'] = legacy(
        _www(speedtest_status=None, xput_up=None, xput_down=None)
    )
    result = runner.invoke(app, ['diagnose', 'wan', '--record'])
    assert result.exit_code == 0, result.output
    assert 'Nothing to record' in result.stderr
    assert not default_speedtest_history_path().exists()


def test_an_unwritable_history_still_prints_health_then_exits_1(
    monkeypatch: pytest.MonkeyPatch, cli: FakeController, tmp_path: Path
) -> None:
    """Issue 076 item 32: a record that could not be written is the run's failure, so a
    schedule notices; the health report is still printed first."""
    blocker = tmp_path / 'not-a-dir'
    blocker.write_text('a file where the state directory should be\n')
    monkeypatch.setenv('XDG_STATE_HOME', str(blocker))
    result = runner.invoke(app, ['diagnose', 'wan', '--record', '--json'])
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)['healthy'] is True
    assert 'Not recorded' in result.stderr and 'Traceback' not in result.output


def test_a_held_lock_fails_the_record_after_the_bound_with_the_reason(
    monkeypatch: pytest.MonkeyPatch, cli: FakeController
) -> None:
    from tests.lock_helpers import held_read_only, run_bounded
    from unifi_mapper.diagnostics import wan_history

    monkeypatch.setattr(wan_history, 'HISTORY_LOCK_TIMEOUT_S', 0.2)
    path = default_speedtest_history_path()
    path.parent.mkdir(parents=True)
    with held_read_only(Path(f'{path}.lock')):
        run = run_bounded(lambda: runner.invoke(app, ['diagnose', 'wan', '--record']), 5)
    assert run.done, 'the command waited on the held lock past its limit'
    result = run.result
    assert result is not None and result.exit_code == 1, getattr(result, 'output', None)
    flat = ' '.join(result.stderr.split())
    assert 'Not recorded' in flat and f'the lock {path}.lock was held for more than 0.2 s' in flat
    assert not path.exists()


def test_a_controller_failure_is_one_error_line(cli: FakeController) -> None:
    cli.routes[f'{API}/stat/health'] = lambda _request: _server_error()
    result = runner.invoke(app, ['diagnose', 'wan', '--json'])
    assert result.exit_code == 1
    assert result.stdout == ''
    assert 'HTTP 500' in result.stderr


def _server_error() -> Any:
    import httpx

    return httpx.Response(500, json={'meta': {'rc': 'error', 'msg': 'boom'}})


def test_diagnose_wan_has_help() -> None:
    result = runner.invoke(app, ['diagnose', 'wan', '--help'])
    assert result.exit_code == 0
    flat = ' '.join(result.output.split())
    assert 'Never starts a speedtest' in flat and 'Read-only' in flat


def test_this_package_resolves_no_real_config(tmp_path: Path) -> None:
    from unifi_mapper.cli import get_default_config_path

    assert not get_default_config_path().exists()
    assert Path.cwd() == tmp_path
