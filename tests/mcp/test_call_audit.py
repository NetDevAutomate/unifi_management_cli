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
from tests.lock_helpers import held_read_only, run_bounded, umask
from tests.mcp import fakes
from typing import Any
from unifi_mapper.analysis.port_counter_baseline import state_dir
from unifi_mapper.core.utils.readonly import audit_request, configure_request_audit
from unifi_mapper.mcp import call_audit as call_audit_module
from unifi_mapper.mcp import runner as runner_module
from unifi_mapper.mcp import server
from unifi_mapper.mcp.call_audit import (
    CALL_AUDIT_FILENAME,
    MAX_LOGGED_KEYS,
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


async def test_unset_writes_a_call_line_at_the_default_path(
    make_runner: Callable[..., ToolRunner],
) -> None:
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


async def test_off_writes_no_file(make_runner: Callable[..., ToolRunner]) -> None:
    runner = make_runner(CallAuditSetting('off'))
    assert (await runner.run('no_params', {})).isError is False
    assert not (state_dir() / CALL_AUDIT_FILENAME).exists()
    assert runner.call_audit is not None and runner.call_audit.target() is None


async def test_an_absolute_path_is_written(
    make_runner: Callable[..., ToolRunner], tmp_path: Path
) -> None:
    path = tmp_path / 'logs' / 'calls.jsonl'
    runner = make_runner(CallAuditSetting('path', path))
    await runner.run('no_params', {}, surface='direct')
    assert [(line['tool'], line['surface']) for line in _lines(path)] == [('no_params', 'direct')]
    assert not (state_dir() / CALL_AUDIT_FILENAME).exists()


async def test_an_unregistered_tool_is_written_by_length_only(
    make_runner: Callable[..., ToolRunner],
) -> None:
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


async def test_unknown_keys_are_a_count_never_a_name(
    make_runner: Callable[..., ToolRunner],
) -> None:
    out = await make_runner().run('int_param', {'n': 1, FAKE_KEY: FAKE_VALUE})
    assert out.structuredContent is not None
    assert out.structuredContent['error_code'] == 'INVALID_PARAMETERS'
    (line,) = _lines()
    assert (line['arg_keys'], line['unknown_keys']) == (['n'], 1)
    assert FAKE_KEY not in json.dumps(line) and FAKE_VALUE not in json.dumps(line)


def test_names_past_the_cap_are_not_counted_as_unknown() -> None:
    """Review finding: past 64 names, parameter names were counted as unknown keys."""
    log = CallAuditLog(CallAuditSetting('default'))
    known = {f'p{i:02d}' for i in range(70)}
    log.record(
        tool='find_device',
        registered=True,
        surface='direct',
        arg_keys=[*sorted(known), 'not_a_parameter'],
        known_keys=known,
        duration_ms=1.0,
        outcome='ok',
    )
    (line,) = _lines()
    assert len(line['arg_keys']) == MAX_LOGGED_KEYS and line['unknown_keys'] == 1


async def test_a_secret_named_parameter_logs_its_key_never_its_value(
    make_runner: Callable[..., ToolRunner],
) -> None:
    await make_runner().run('api_key_param', {'api_key': FAKE_VALUE})
    (line,) = _lines()
    assert line['arg_keys'] == ['api_key'] and line['outcome'] == 'INVALID_PARAMETERS'
    assert FAKE_VALUE not in (state_dir() / CALL_AUDIT_FILENAME).read_text(encoding='utf-8')


async def test_refusals_are_logged(
    make_runner: Callable[..., ToolRunner], monkeypatch: pytest.MonkeyPatch
) -> None:
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


async def test_a_cancelled_call_is_logged_and_still_cancelled(
    make_runner: Callable[..., ToolRunner],
) -> None:
    runner = make_runner()
    task = asyncio.create_task(runner.run('sleeper', {'seconds': 30}))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    (line,) = _lines()
    assert (line['tool'], line['outcome']) == ('sleeper', 'CANCELLED')


async def test_the_file_is_compacted_at_its_cap(
    make_runner: Callable[..., ToolRunner], tmp_path: Path
) -> None:
    path = tmp_path / 'calls.jsonl'
    runner = make_runner(CallAuditSetting('path', path), max_bytes=4000)
    for n in range(60):
        await runner.run('int_param', {'n': n})
    assert path.stat().st_size <= 4000
    lines = _lines(path)
    assert 10 < len(lines) < 60 and lines[-1]['tool'] == 'int_param'


async def test_an_unwritable_path_leaves_the_result_and_warns_once(
    make_runner: Callable[..., ToolRunner], tmp_path: Path, warned: list[str]
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
    make_runner: Callable[..., ToolRunner], monkeypatch: pytest.MonkeyPatch, warned: list[str]
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


def _record(log: CallAuditLog) -> None:
    log.record(
        tool='find_device',
        registered=True,
        surface='direct',
        arg_keys=['query'],
        known_keys={'query'},
        duration_ms=1.0,
        outcome='ok',
    )


def test_a_permissive_call_log_and_directory_are_made_private() -> None:
    """Review finding: 0o600 and 0o700 applied on creation only, so a call log or state
    directory that already existed group- or world-readable stayed so."""
    path = state_dir() / CALL_AUDIT_FILENAME
    path.parent.mkdir(parents=True)
    os.chmod(path.parent, 0o755)
    path.write_text('', encoding='utf-8')
    os.chmod(path, 0o644)
    _record(CallAuditLog(CallAuditSetting('default')))
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [line['tool'] for line in _lines(path)] == ['find_device']


def test_a_call_log_owned_by_another_user_turns_the_log_off_with_one_warning(
    monkeypatch: pytest.MonkeyPatch, warned: list[str]
) -> None:
    path = state_dir() / CALL_AUDIT_FILENAME
    path.parent.mkdir(parents=True)
    os.chmod(path.parent, 0o755)
    me = os.geteuid()
    log = CallAuditLog(CallAuditSetting('default'))
    with monkeypatch.context() as patched:
        patched.setattr(os, 'geteuid', lambda: me + 1)  # the state directory is someone else's
        _record(log)
        _record(log)
    assert log.enabled is False
    (warning,) = [w for w in warned if 'call log disabled' in w]
    assert 'owned by another user' in warning
    assert not path.exists() and stat.S_IMODE(path.parent.stat().st_mode) == 0o755


def test_two_writes_that_fail_together_warn_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warned: list[str]
) -> None:
    """Issue 076 item 35: ``_write`` checked ``_disabled`` outside the lock and the generic
    handler set it and warned with no guard, so two writes already past the check (the
    runner records in worker threads) could both fail and both warn."""
    import errno
    import threading

    gate = threading.Barrier(2, timeout=5)

    def _both_fail(*_args: object, **_kwargs: object) -> None:
        gate.wait()  # both writes are past the enabled check before either fails
        raise OSError(errno.EACCES, 'Permission denied')

    monkeypatch.setattr(call_audit_module, 'append_capped_jsonl', _both_fail)
    log = CallAuditLog(CallAuditSetting('path', tmp_path / CALL_AUDIT_FILENAME))
    threads = [threading.Thread(target=_record, args=(log,), daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert log.enabled is False
    assert len([w for w in warned if 'MCP call log disabled' in w]) == 1


@pytest.mark.parametrize('link', ['lock', 'log'])
def test_a_link_in_the_locks_place_is_named_in_the_warning(
    tmp_path: Path, warned: list[str], link: str
) -> None:
    """Issue 076 item 36: the lock's ``O_NOFOLLOW`` open fails with ELOOP, and the warning
    named the log (which may not exist), not the lock."""
    directory = tmp_path / 'logs'
    directory.mkdir()
    path = directory / CALL_AUDIT_FILENAME
    target = tmp_path / 'elsewhere.jsonl'
    target.write_text('', encoding='utf-8')
    (Path(f'{path}.lock') if link == 'lock' else path).symlink_to(target)
    log = _given(directory)
    _record(log)
    _record(log)
    assert log.enabled is False
    (warning,) = [w for w in warned if 'call log disabled' in w]
    assert f'cannot write {path}: OSError (ELOOP)' in warning
    if link == 'lock':
        assert f'on {CALL_AUDIT_FILENAME}.lock' in warning
    else:
        assert '.lock' not in warning  # today's warning, unchanged
    assert target.read_text(encoding='utf-8') == ''  # nothing written through the link


# --- a given path: its directory is the user's, never changed ------------


def _given(directory: Path) -> CallAuditLog:
    """A call log at a path the user gives (``UNIFI_MCP_CALL_AUDIT``) in ``directory``."""
    return CallAuditLog(CallAuditSetting('path', directory / CALL_AUDIT_FILENAME))


@pytest.mark.parametrize('mode', [0o755, 0o750], ids=oct)
def test_a_given_path_under_home_leaves_the_home_directory_mode_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: int
) -> None:
    """Review finding: with ``~/mcp-audit.jsonl``, every call set the home
    directory to 0o700."""
    home = tmp_path / 'home'
    home.mkdir()
    os.chmod(home, mode)
    monkeypatch.setenv('HOME', str(home))
    _record(CallAuditLog(parse_call_audit('~/mcp-audit.jsonl', pytest.fail)))
    path = home / 'mcp-audit.jsonl'
    assert (stat.S_IMODE(home.stat().st_mode), stat.S_IMODE(path.stat().st_mode)) == (mode, 0o600)
    assert [line['tool'] for line in _lines(path)] == ['find_device']


@pytest.mark.parametrize('mode', [0o777, 0o775], ids=oct)
def test_a_given_directory_others_can_write_turns_the_log_off_with_one_warning(
    tmp_path: Path, warned: list[str], mode: int
) -> None:
    directory = tmp_path / 'shared'
    directory.mkdir()
    os.chmod(directory, mode)
    log = _given(directory)
    _record(log)
    _record(log)
    assert log.enabled is False
    (warning,) = [w for w in warned if 'call log disabled' in w]
    assert 'group or other write permission' in warning
    assert list(directory.iterdir()) == []  # no file and no lock file
    assert stat.S_IMODE(directory.stat().st_mode) == mode


def test_a_given_directory_owned_by_another_user_turns_the_log_off_with_one_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warned: list[str]
) -> None:
    directory = tmp_path / 'theirs'
    directory.mkdir()
    os.chmod(directory, 0o755)
    me = os.geteuid()
    log = _given(directory)
    with monkeypatch.context() as patched:
        patched.setattr(os, 'geteuid', lambda: me + 1)  # the given directory is someone else's
        _record(log)
        _record(log)
    assert log.enabled is False
    (warning,) = [w for w in warned if 'call log disabled' in w]
    assert 'owned by another user' in warning
    assert list(directory.iterdir()) == [] and stat.S_IMODE(directory.stat().st_mode) == 0o755


def test_a_permissive_given_call_log_is_made_private_in_a_directory_left_alone(
    tmp_path: Path,
) -> None:
    directory = tmp_path / 'logs'
    directory.mkdir()
    os.chmod(directory, 0o755)
    path = directory / CALL_AUDIT_FILENAME
    path.write_text('', encoding='utf-8')
    os.chmod(path, 0o644)
    _record(_given(directory))
    assert (stat.S_IMODE(directory.stat().st_mode), stat.S_IMODE(path.stat().st_mode)) == (
        0o755,
        0o600,
    )
    assert [line['tool'] for line in _lines(path)] == ['find_device']


def test_a_given_paths_missing_directory_is_created_private(tmp_path: Path) -> None:
    directory = tmp_path / 'new' / 'logs'
    _record(_given(directory))
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((directory / CALL_AUDIT_FILENAME).stat().st_mode) == 0o600


# --- the lock: private, and never waited on past its limit ----------------

# How much longer than the patched limit a write may take before a test calls it a stall.
LOCK_SLACK_S = 1.0


def _lock_warnings(warned: list[str]) -> list[str]:
    return [w for w in warned if 'its lock was held' in w]


def test_a_given_path_in_a_searchable_directory_leaves_a_private_lock(tmp_path: Path) -> None:
    """VS-1: the lock beside a given path was 0o644 under umask 022, so in a directory other
    accounts can search (a 0o755 home), any of them could open it and hold its flock."""
    directory = tmp_path / 'logs'
    directory.mkdir()
    os.chmod(directory, 0o755)
    with umask(0o022):
        _record(_given(directory))
    path = directory / CALL_AUDIT_FILENAME
    modes = [stat.S_IMODE(p.stat().st_mode) for p in (directory, path, Path(f'{path}.lock'))]
    assert modes == [0o755, 0o600, 0o600]


def test_a_held_lock_drops_the_write_with_one_warning_and_keeps_the_log_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warned: list[str]
) -> None:
    import time

    monkeypatch.setattr(call_audit_module, 'LOCK_TIMEOUT_S', 0.2)
    monkeypatch.setattr(call_audit_module, 'LOCK_COOLDOWN_S', 0.3)
    directory = tmp_path / 'logs'
    directory.mkdir()
    os.chmod(directory, 0o755)
    log = _given(directory)
    path = directory / CALL_AUDIT_FILENAME
    with held_read_only(Path(f'{path}.lock')):
        for _ in range(2):  # the second drop logs no second warning
            held = run_bounded(lambda: _record(log), join_s=5)
            assert held.done, 'record() waited on the held lock past its limit'
            assert held.error is None and held.elapsed < 0.2 + LOCK_SLACK_S
    assert log.enabled is True and not path.exists()
    assert len(_lock_warnings(warned)) == 1
    time.sleep(0.35)  # the lock is free and the cool-down over: the next call is written
    _record(log)
    assert [(line['kind'], line.get('tool')) for line in _lines(path)] == [
        ('lock_timeout', None),
        ('call', 'find_device'),
    ]
    assert _lines(path)[0]['dropped'] == 2  # the timed-out write and the one in the cool-down
    assert len(_lock_warnings(warned)) == 1
    assert not [w for w in warned if 'call log disabled' in w]


def test_a_held_lock_never_holds_a_tool_result_past_the_limit(
    make_runner: Callable[..., ToolRunner], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VS-1: the runner awaits the write, shielded, in ``finally``, so the held lock held
    the tool's result too."""
    monkeypatch.setattr(call_audit_module, 'LOCK_TIMEOUT_S', 0.2)
    path = tmp_path / 'logs' / CALL_AUDIT_FILENAME
    path.parent.mkdir()
    os.chmod(path.parent, 0o755)
    runner = make_runner(CallAuditSetting('path', path))
    with held_read_only(Path(f'{path}.lock')):
        held = run_bounded(lambda: asyncio.run(runner.run('no_params', {})), join_s=5)
    assert held.done, 'the tool call waited on the held lock past its limit'
    assert held.error is None and held.elapsed < 0.2 + LOCK_SLACK_S
    assert getattr(held.result, 'structuredContent', None) == {'ok': True, 'result': {'ok': True}}
    assert runner.call_audit is not None and runner.call_audit.enabled is True


def test_after_a_lock_timeout_the_lock_is_not_tried_again_during_the_cool_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warned: list[str]
) -> None:
    """Issue 076 item 33: a lock that is never released cost every logged call the whole
    limit; after a timeout the next writes skip the lock attempt for LOCK_COOLDOWN_S."""
    monkeypatch.setattr(call_audit_module, 'LOCK_TIMEOUT_S', 0.2)
    monkeypatch.setattr(call_audit_module, 'LOCK_COOLDOWN_S', 60.0)
    directory = tmp_path / 'logs'
    directory.mkdir()
    log = _given(directory)
    path = directory / CALL_AUDIT_FILENAME
    with held_read_only(Path(f'{path}.lock')):
        timed_out = run_bounded(lambda: _record(log), join_s=5)
        assert timed_out.done and timed_out.error is None
        assert 0.2 <= timed_out.elapsed < 0.2 + LOCK_SLACK_S
        for _ in range(3):  # in the cool-down: no wait at all
            skipped = run_bounded(lambda: _record(log), join_s=5)
            assert skipped.done and skipped.error is None
            assert skipped.elapsed < 0.1, 'a write in the cool-down waited on the lock'
    assert log.enabled is True and not path.exists()
    assert len(_lock_warnings(warned)) == 1
    assert call_audit_module.LOCK_COOLDOWN_S == 60.0  # patched; see the shipped value below


def test_the_shipped_cool_down_is_one_minute() -> None:
    assert call_audit_module.LOCK_COOLDOWN_S == 60.0


def test_the_next_write_after_the_cool_down_records_how_many_lines_were_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue 076 item 33: after the first warning the dropped lines left no trace; now the
    next successful write starts with a ``lock_timeout`` line counting them, as
    ``request_overflow`` does for request lines."""
    import time

    monkeypatch.setattr(call_audit_module, 'LOCK_TIMEOUT_S', 0.2)
    monkeypatch.setattr(call_audit_module, 'LOCK_COOLDOWN_S', 0.3)
    directory = tmp_path / 'logs'
    directory.mkdir()
    log = _given(directory)
    path = directory / CALL_AUDIT_FILENAME
    with held_read_only(Path(f'{path}.lock')):
        log.note_request('GET', '/x')  # a buffered request line is dropped with its call line
        assert run_bounded(lambda: _record(log), join_s=5).done  # times out: 2 lines dropped
        assert run_bounded(lambda: _record(log), join_s=5).done  # in the cool-down: 1 more
    time.sleep(0.35)  # past the cool-down; the lock is free again
    _record(log)
    kinds = [(line['kind'], line.get('dropped')) for line in _lines(path)]
    assert kinds == [('lock_timeout', 3), ('call', None)]
    _record(log)  # the count was reset: no second marker
    assert [line['kind'] for line in _lines(path)] == ['lock_timeout', 'call', 'call']


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


async def test_logging_runs_in_a_worker_thread(
    make_runner: Callable[..., ToolRunner], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []
    real = anyio.to_thread.run_sync

    async def _spy(fn: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(True)
        return await real(fn, *args, **kwargs)

    monkeypatch.setattr(runner_module.anyio.to_thread, 'run_sync', _spy)
    await make_runner().run('no_params', {})
    assert seen == [True] and len(_lines()) == 1
