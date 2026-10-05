"""The recorded WAN speedtest history: path, capped writer, reads, the MCP tool and the CLI.

Every test writes under ``tmp_path``; the default path is checked with ``XDG_STATE_HOME`` set
and unset, and never resolves relative to the working directory.
"""

import inspect
import json
import pytest
import threading
from pathlib import Path
from typer.testing import CliRunner
from unifi_mapper import typer_cli
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.diagnostics import wan_history
from unifi_mapper.diagnostics.wan_history import (
    SPEEDTEST_HISTORY_MAX_BYTES,
    append_speedtest,
    default_speedtest_history_path,
    get_wan_speedtest_history,
    read_speedtest_history,
    speedtest_line,
)
from unifi_mapper.typer_cli import app


runner = CliRunner()


def _speedtest(run_epoch: object = 1_790_000_000, down: float = 950.0) -> dict:
    return {
        'run_epoch': run_epoch,
        'up_mbps': 100.0,
        'down_mbps': down,
        'ping_ms': 9.0,
        'status': 'Success',
    }


# --- the default path ---------------------------------------------------------------------


def test_the_default_path_is_under_xdg_state_when_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    path = default_speedtest_history_path()
    assert path == tmp_path / 'xdg' / 'unifi_mapper' / 'wan-speedtest-history.jsonl'
    assert not path.parent.exists()  # nothing is created by asking


def test_the_default_path_falls_back_to_home_and_is_never_cwd_relative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv('XDG_STATE_HOME', raising=False)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    path = default_speedtest_history_path()
    assert path == tmp_path / 'home' / '.local' / 'state' / 'unifi_mapper' / path.name
    assert path.is_absolute()


# --- writing --------------------------------------------------------------------------------


def test_a_line_needs_a_run_time() -> None:
    line = speedtest_line(_speedtest())
    assert line is not None and json.loads(line)['epoch'] == 1_790_000_000
    for bad in (None, 0, -5, True, '1790000000'):
        assert speedtest_line(_speedtest(run_epoch=bad)) is None


def test_append_dedups_by_run_time_and_sets_modes(tmp_path: Path) -> None:
    path = tmp_path / 'state' / 'history.jsonl'
    first = append_speedtest(_speedtest(), path)
    again = append_speedtest(_speedtest(down=1.0), path)  # same run, other numbers
    later = append_speedtest(_speedtest(run_epoch=1_790_003_600), path)
    assert first is not None and first.lines_written == 1
    assert again is not None and (again.lines_written, again.skipped_duplicates) == (0, 1)
    assert later is not None and later.lines_written == 1
    assert len(path.read_text().splitlines()) == 2
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert append_speedtest(_speedtest(run_epoch=None), path) is None


def test_concurrent_appends_of_one_run_write_it_once(tmp_path: Path) -> None:
    path = tmp_path / 'history.jsonl'
    threads = [
        threading.Thread(target=append_speedtest, args=(_speedtest(), path)) for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(path.read_text().splitlines()) == 1  # the dedup ran under the writer's lock


def test_the_history_is_capped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wan_history, 'SPEEDTEST_HISTORY_MAX_BYTES', 1000)
    path = tmp_path / 'history.jsonl'
    for i in range(40):
        append_speedtest(_speedtest(run_epoch=1_790_000_000 + i * 3600), path)
    assert path.stat().st_size <= 1000
    newest = read_speedtest_history(path, limit=1)['entries'][0]
    assert newest['epoch'] == 1_790_000_000 + 39 * 3600
    assert SPEEDTEST_HISTORY_MAX_BYTES == 1024 * 1024


# --- reading ------------------------------------------------------------------------------


def test_a_missing_history_is_empty_with_a_hint(tmp_path: Path) -> None:
    result = read_speedtest_history(tmp_path / 'none.jsonl')
    assert (result['found'], result['total'], result['entries']) == (False, 0, [])
    assert 'diagnose wan --record' in result['note']
    assert not (tmp_path / 'none.jsonl').exists()  # reading never writes


def test_reads_are_newest_first_limited_and_skip_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / 'history.jsonl'
    for i in range(5):
        append_speedtest(_speedtest(run_epoch=1_790_000_000 + i), path)
    with path.open('a') as f:
        f.write('{"torn": \n["not", "an", "object"]\n{"epoch": "soon"}\n')
    result = read_speedtest_history(path, limit=2)
    assert (result['total'], result['returned']) == (5, 2)
    assert [e['epoch'] for e in result['entries']] == [1_790_000_004, 1_790_000_003]
    assert 'note' not in result


@pytest.mark.parametrize('limit', [0, 1001])
def test_an_out_of_range_limit_is_refused(tmp_path: Path, limit: int) -> None:
    with pytest.raises(ValueError):
        read_speedtest_history(tmp_path / 'h.jsonl', limit=limit)


# --- the MCP tool -------------------------------------------------------------------------


async def test_the_mcp_tool_reads_the_default_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    append_speedtest(_speedtest())
    result = await get_wan_speedtest_history(limit=10)
    assert result['total'] == 1 and result['entries'][0]['down_mbps'] == 950.0
    assert inspect.iscoroutinefunction(get_wan_speedtest_history)


def test_the_history_module_imports_no_controller_client() -> None:
    source = Path(wan_history.__file__).read_text(encoding='utf-8')
    for name in ('UniFiClient', 'UnifiApiClient', 'get_credentials', 'httpx'):
        assert name not in source


# --- diagnose wan-history and _offline_errors ------------------------------------------------


def test_wan_history_prints_the_recorded_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    empty = runner.invoke(app, ['diagnose', 'wan-history'])
    assert empty.exit_code == 0 and 'no history' in empty.stderr
    append_speedtest(_speedtest())
    table = runner.invoke(app, ['diagnose', 'wan-history'])
    assert table.exit_code == 0, table.output
    assert '950.0' in table.stdout
    as_json = runner.invoke(app, ['diagnose', 'wan-history', '--json', '--limit', '5'])
    assert json.loads(as_json.stdout)['returned'] == 1


@pytest.mark.parametrize('limit', ['0', '1001'])
def test_wan_history_refuses_a_bad_limit(limit: str) -> None:
    assert runner.invoke(app, ['diagnose', 'wan-history', '--limit', limit]).exit_code == 2


@pytest.mark.parametrize(
    ('error', 'code', 'text'),
    [
        (ToolError(message='bad path', error_code=ErrorCodes.CONFIG_INVALID), 2, 'bad path'),
        (ToolError(message='no store yet', error_code=ErrorCodes.NO_DATA), 1, 'no store yet'),
        (ValueError('limit must be between 1 and 1000'), 2, 'limit must be between'),
        (RuntimeError('disk said token=FAKE-OFFLINE-TOKEN'), 1, 'token=***redacted***'),
    ],
)
def test_offline_errors_exit_codes(
    monkeypatch: pytest.MonkeyPatch, error: Exception, code: int, text: str
) -> None:
    def _raise(**_kwargs: object) -> dict:
        raise error

    monkeypatch.setattr(wan_history, 'read_speedtest_history', _raise)
    result = runner.invoke(app, ['diagnose', 'wan-history'])
    assert result.exit_code == code, result.output
    assert isinstance(result.exception, SystemExit)
    assert text in ' '.join(result.stderr.split())
    assert 'FAKE-OFFLINE-TOKEN' not in result.output


def test_wan_history_contacts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no(*_args: object, **_kwargs: object) -> None:
        raise AssertionError('the history command must not load a config or a client')

    monkeypatch.setattr(typer_cli, 'load_env_from_config', _no)
    monkeypatch.setattr(typer_cli, '_shared_client_factory', _no)
    assert runner.invoke(app, ['diagnose', 'wan-history']).exit_code == 0
