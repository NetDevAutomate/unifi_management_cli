"""The MCP call log (``mcp/call_audit.py``; issue 013 D5, design section 4.6).

On by default under the test's XDG state (isolated per test); one line per catalog call
with the registered tool's name, its own parameter names only, a count of any other key,
the duration and the outcome code. Values, results and messages never appear.
"""

import anyio
import asyncio
import json
import os
import pytest
import stat
from collections.abc import Callable
from contextlib import ExitStack
from loguru import logger
from pathlib import Path
from tests.mcp import fakes
from typing import Any
from unifi_mapper.analysis.port_counter_baseline import state_dir
from unifi_mapper.core.utils.readonly import audit_request, configure_request_audit
from unifi_mapper.mcp import runner as runner_module
from unifi_mapper.mcp import server
from unifi_mapper.mcp.call_audit import (
    CALL_AUDIT_FILENAME,
    MAX_PENDING_REQUESTS,
    UNREGISTERED,
    CallAuditLog,
    CallAuditSetting,
    env_switch,
    parse_call_audit,
)
from unifi_mapper.mcp.config import CredentialsMissingError, ServerSettings, load_server_settings
from unifi_mapper.mcp.runner import ToolRunner


FAKE_VALUE = 'FAKE-CALL-LOG-VALUE-MUST-NOT-APPEAR'  # pragma: allowlist secret
FAKE_TOOL_NAME = 'FAKE-UNREGISTERED-TOOL-NAME'
FAKE_KEY = 'FAKE_UNKNOWN_KEY_NAME'


@pytest.fixture
def warned() -> list[str]:
    """Capture loguru WARNING messages for the test."""
    seen: list[str] = []
    handler = logger.add(lambda m: seen.append(m.record['message']), level='WARNING')
    try:
        yield seen
    finally:
        logger.remove(handler)


@pytest.fixture
def make_runner(tmp_path: Path) -> Callable[..., ToolRunner]:
    def _make(
        setting: CallAuditSetting | None = None, credentials: str = 'none', **kwargs: Any
    ) -> ToolRunner:
        registry = fakes.fake_registry(tmp_path, credentials=credentials)
        log = CallAuditLog(setting or CallAuditSetting('default'), **kwargs)
        return ToolRunner(registry, settings=ServerSettings(), call_audit=log)

    return _make


def _lines(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or state_dir() / CALL_AUDIT_FILENAME
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


# --- the setting ---------------------------------------------------------------------------


@pytest.mark.parametrize('raw', [None, '', '  ', 'on', 'TRUE', '1', 'default', 'Default'])
def test_unset_and_the_on_family_are_the_default_path(raw: str | None) -> None:
    assert parse_call_audit(raw, pytest.fail) == CallAuditSetting('default')


@pytest.mark.parametrize('raw', ['off', 'OFF', ' false ', '0', 'none', 'None'])
def test_the_off_family_turns_the_log_off(raw: str) -> None:
    assert parse_call_audit(raw, pytest.fail) == CallAuditSetting('off')


def test_an_absolute_or_home_path_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    assert parse_call_audit(str(tmp_path / 'a.jsonl'), pytest.fail).path == tmp_path / 'a.jsonl'
    assert parse_call_audit('~/b.jsonl', pytest.fail).path == tmp_path / 'b.jsonl'


def test_a_relative_path_is_refused_with_one_warning() -> None:
    seen: list[str] = []
    assert parse_call_audit('calls.jsonl', seen.append) == CallAuditSetting('off')
    assert len(seen) == 1 and 'absolute path' in seen[0]
    settings = load_server_settings({'UNIFI_MCP_CALL_AUDIT': 'rel/calls.jsonl'}, seen.append)
    assert settings.call_audit.mode == 'off' and len(seen) == 2


def test_the_switch_families_are_shared() -> None:
    assert [env_switch(v) for v in ('on', ' 1 ', 'true', 'off', '0', 'none', 'x', None)] == [
        'on',
        'on',
        'on',
        'off',
        'off',
        'off',
        None,
        None,
    ]


# --- lines ---------------------------------------------------------------------------------


async def test_unset_writes_a_call_line_at_the_default_path(make_runner) -> None:
    runner = make_runner(parse_call_audit(None, pytest.fail))
    out = await runner.run('str_param', {'s': FAKE_VALUE})
    assert out.isError is False
    path = state_dir() / CALL_AUDIT_FILENAME
    (line,) = _lines(path)
    assert {k: line[k] for k in ('kind', 'tool', 'surface', 'arg_keys', 'unknown_keys')} == {
        'kind': 'call',
        'tool': 'str_param',
        'surface': 'execute_tool',
        'arg_keys': ['s'],
        'unknown_keys': 0,
    }
    assert line['outcome'] == 'ok' and line['pid'] == os.getpid()
    assert isinstance(line['duration_ms'], float) and isinstance(line['epoch'], float)
    assert FAKE_VALUE not in path.read_text(encoding='utf-8')
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


async def test_off_writes_no_file(make_runner) -> None:
    runner = make_runner(CallAuditSetting('off'))
    assert (await runner.run('no_params', {})).isError is False
    assert not (state_dir() / CALL_AUDIT_FILENAME).exists()
    assert runner.call_audit is not None and runner.call_audit.target() is None


async def test_an_absolute_path_is_written(make_runner, tmp_path: Path) -> None:
    path = tmp_path / 'logs' / 'calls.jsonl'
    runner = make_runner(CallAuditSetting('path', path))
    await runner.run('no_params', {}, surface='direct')
    assert [(line['tool'], line['surface']) for line in _lines(path)] == [('no_params', 'direct')]
    assert not (state_dir() / CALL_AUDIT_FILENAME).exists()


async def test_an_unregistered_tool_is_written_by_length_only(make_runner) -> None:
    runner = make_runner()
    out = await runner.run(FAKE_TOOL_NAME, {FAKE_KEY: FAKE_VALUE})
    assert out.structuredContent is not None
    assert out.structuredContent['error_code'] == 'TOOL_NOT_FOUND'
    (line,) = _lines()
    assert line['tool'] == UNREGISTERED and line['tool_name_length'] == len(FAKE_TOOL_NAME)
    assert (line['arg_keys'], line['unknown_keys'], line['outcome']) == ([], 1, 'TOOL_NOT_FOUND')
    text = (state_dir() / CALL_AUDIT_FILENAME).read_text(encoding='utf-8')
    for leaked in (FAKE_TOOL_NAME, FAKE_KEY, FAKE_VALUE):
        assert leaked not in text


async def test_unknown_keys_are_a_count_never_a_name(make_runner) -> None:
    out = await make_runner().run('int_param', {'n': 1, FAKE_KEY: FAKE_VALUE})
    assert out.structuredContent is not None
    assert out.structuredContent['error_code'] == 'INVALID_PARAMETERS'
    (line,) = _lines()
    assert (line['arg_keys'], line['unknown_keys']) == (['n'], 1)
    assert FAKE_KEY not in json.dumps(line) and FAKE_VALUE not in json.dumps(line)


async def test_a_secret_named_parameter_logs_its_key_never_its_value(make_runner) -> None:
    await make_runner().run('api_key_param', {'api_key': FAKE_VALUE})
    (line,) = _lines()
    assert line['arg_keys'] == ['api_key'] and line['outcome'] == 'INVALID_PARAMETERS'
    assert FAKE_VALUE not in (state_dir() / CALL_AUDIT_FILENAME).read_text(encoding='utf-8')


async def test_refusals_are_logged(make_runner, monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing(timeout: float, tried: Any = ()) -> None:
        raise CredentialsMissingError('no controller credentials', tried=())

    monkeypatch.setattr(runner_module, 'ensure_controller_credentials', missing)
    runner = make_runner(credentials='controller')
    await runner.run('apply_things', {})
    await runner.run('int_param', {'n': 'not a number'})
    await runner.run(FAKE_TOOL_NAME, None)
    await runner.run('read_port', {'switch': 'Switch A', 'port': 1})
    assert [line['outcome'] for line in _lines()] == [
        'MUTATION_REFUSED',
        'INVALID_PARAMETERS',
        'TOOL_NOT_FOUND',
        'CONFIG_MISSING',
    ]


async def test_a_cancelled_call_is_logged_and_still_cancelled(make_runner) -> None:
    runner = make_runner()
    task = asyncio.create_task(runner.run('sleeper', {'seconds': 30}))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    (line,) = _lines()
    assert (line['tool'], line['outcome']) == ('sleeper', 'CANCELLED')


async def test_the_file_is_compacted_at_its_cap(make_runner, tmp_path: Path) -> None:
    path = tmp_path / 'calls.jsonl'
    runner = make_runner(CallAuditSetting('path', path), max_bytes=4000)
    for n in range(60):
        await runner.run('int_param', {'n': n})
    assert path.stat().st_size <= 4000
    lines = _lines(path)
    assert 10 < len(lines) < 60 and lines[-1]['tool'] == 'int_param'


async def test_an_unwritable_path_leaves_the_result_and_warns_once(
    make_runner, tmp_path: Path, warned: list[str]
) -> None:
    blocker = tmp_path / 'a-file'
    blocker.write_text('x', encoding='utf-8')
    runner = make_runner(CallAuditSetting('path', blocker / 'calls.jsonl'))
    for _ in range(2):
        out = await runner.run('no_params', {})
        assert out.structuredContent == {'ok': True, 'result': {'ok': True}}
    assert len([w for w in warned if 'call log disabled' in w]) == 1
    assert runner.call_audit is not None and runner.call_audit.enabled is False


async def test_no_home_directory_leaves_the_result_and_warns_once(
    make_runner, monkeypatch: pytest.MonkeyPatch, warned: list[str]
) -> None:
    def _no_home() -> Path:
        raise RuntimeError('Could not determine home directory')

    monkeypatch.delenv('XDG_STATE_HOME', raising=False)
    monkeypatch.setattr(Path, 'home', _no_home)
    runner = make_runner()
    for _ in range(2):
        out = await runner.run('no_params', {})
        assert out.structuredContent == {'ok': True, 'result': {'ok': True}}
    assert len([w for w in warned if 'call log disabled' in w]) == 1


# --- request lines -------------------------------------------------------------------------


def _request_audit(monkeypatch: pytest.MonkeyPatch, value: str, log: CallAuditLog | None) -> None:
    monkeypatch.setenv('UNIFI_MCP_REQUEST_AUDIT', value)
    with ExitStack() as stack:
        server._configure_request_audit(stack, log)
        audit_request('GET', '/proxy/network/api/s/default/stat/device')
        audit_request('POST', '/proxy/network/api/s/default/stat/event')
    audit_request('GET', '/after/the/lifespan')  # cleared on exit: goes nowhere


@pytest.mark.parametrize('value', ['on', 'ON', 'true', '1'])
def test_request_audit_on_puts_request_lines_before_the_call_line(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    log = CallAuditLog(CallAuditSetting('default'))
    _request_audit(monkeypatch, value, log)
    log.record(
        tool='find_device',
        registered=True,
        surface='direct',
        arg_keys=['query'],
        known_keys={'query'},
        duration_ms=1.0,
        outcome='ok',
    )
    assert [(line['kind'], line.get('method')) for line in _lines()] == [
        ('request', 'GET'),
        ('request', 'POST'),
        ('call', None),
    ]


def test_request_audit_on_with_the_call_log_off_warns_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, warned: list[str]
) -> None:
    log = CallAuditLog(CallAuditSetting('off'))
    _request_audit(monkeypatch, 'on', log)
    log.flush()
    assert any('call log, which is off' in w for w in warned)
    assert not (state_dir() / CALL_AUDIT_FILENAME).exists()


@pytest.mark.parametrize('value', ['off', 'OFF', 'false', '0', 'none', 'default'])
def test_request_audit_off_family_and_default_write_no_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str
) -> None:
    monkeypatch.chdir(tmp_path)
    log = CallAuditLog(CallAuditSetting('default'))
    _request_audit(monkeypatch, value, log)
    log.flush()
    assert not Path(value).exists() and not (tmp_path / value).exists()  # never ./off
    assert not (state_dir() / CALL_AUDIT_FILENAME).exists()


def test_request_audit_path_keeps_the_separate_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / 'requests.jsonl'
    log = CallAuditLog(CallAuditSetting('default'))
    _request_audit(monkeypatch, str(path), log)
    log.flush()
    lines = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert [line['method'] for line in lines] == ['GET', 'POST']
    assert not (state_dir() / CALL_AUDIT_FILENAME).exists()


def test_a_full_request_buffer_becomes_one_overflow_line() -> None:
    log = CallAuditLog(CallAuditSetting('default'))
    for _ in range(MAX_PENDING_REQUESTS + 5):
        log.note_request('GET', '/x')
    log.flush()
    lines = _lines()
    assert len(lines) == MAX_PENDING_REQUESTS + 1
    assert lines[-1]['kind'] == 'request_overflow' and lines[-1]['dropped'] == 5


def test_a_sink_and_a_path_together_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='not both'):
        configure_request_audit(tmp_path / 'x.jsonl', sink=lambda _m, _p: None)


# --- the server: the cached runner and --check ---------------------------------------------


@pytest.fixture
def fresh_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, '_settings', None)
    monkeypatch.setattr(server, '_runner', None)


@pytest.mark.parametrize(
    ('value', 'expected'),
    [(None, 'default'), ('off', 'off'), ('ABS', 'path')],
    ids=['unset', 'off', 'absolute path'],
)
def test_check_reports_the_call_log(
    fresh_server: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str | None,
    expected: str,
) -> None:
    from unifi_mapper.mcp.config import resolve_mcp_config

    absolute = tmp_path / 'calls.jsonl'
    if value is None:
        monkeypatch.delenv('UNIFI_MCP_CALL_AUDIT', raising=False)
    else:
        monkeypatch.setenv('UNIFI_MCP_CALL_AUDIT', str(absolute) if value == 'ABS' else value)
    report = server.check_report(resolve_mcp_config(None), 'discovery', load_server_settings())
    assert (
        report['call_audit']
        == {
            'default': str(state_dir() / CALL_AUDIT_FILENAME),
            'off': 'off',
            'path': str(absolute),
        }[expected]
    )


async def test_the_server_runner_logs_by_default(fresh_server: None) -> None:
    runner = server.get_runner()
    assert runner.call_audit is not None and runner.call_audit.setting.mode == 'default'
    await runner.run(FAKE_TOOL_NAME, None)
    assert [line['tool'] for line in _lines()] == [UNREGISTERED]


async def test_logging_runs_shielded_in_a_worker_thread(
    make_runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []
    real = anyio.to_thread.run_sync

    async def _spy(fn: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(True)
        return await real(fn, *args, **kwargs)

    monkeypatch.setattr(runner_module.anyio.to_thread, 'run_sync', _spy)
    await make_runner().run('no_params', {})
    assert seen == [True] and len(_lines()) == 1
