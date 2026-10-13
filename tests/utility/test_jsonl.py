"""The shared capped JSON Lines writer (``core/utils/jsonl``).

``tests/analysis/test_counter_history.py`` passes unchanged over it (the refactor's proof);
these tests pin the generic parts the newer histories use: deduplication under the lock,
modes, and ``epoch_field``.
"""

import errno
import fcntl
import json
import math
import os
import pytest
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tests.lock_helpers import held_read_only, run_bounded, umask
from unifi_mapper.core.utils import jsonl
from unifi_mapper.core.utils.jsonl import (
    COMPACT_LOW_WATER_RATIO,
    CappedWriteResult,
    append_capped_jsonl,
    compact_jsonl_lines,
    epoch_field,
)


EPOCH = epoch_field('epoch')


def _line(epoch: float, **extra: object) -> str:
    return json.dumps({'epoch': epoch, **extra}, sort_keys=True) + '\n'


def _run_time(line: str) -> str | None:
    try:
        return str(json.loads(line)['run'])
    except (ValueError, KeyError, TypeError):
        return None


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _epochs(path: Path) -> list[float]:
    return [json.loads(line)['epoch'] for line in path.read_text().splitlines()]


# --- epoch_field -------------------------------------------------------------------------


@pytest.mark.parametrize(('value', 'expected'), [(1.5, 1.5), (3, 3.0), (0, 0.0)])
def test_epoch_field_returns_the_number(value: float, expected: float) -> None:
    assert EPOCH(json.dumps({'epoch': value})) == expected


@pytest.mark.parametrize(
    'line',
    [
        json.dumps({'other': 1}),
        json.dumps({'epoch': '1'}),
        json.dumps({'epoch': True}),
        json.dumps({'epoch': None}),
        '{"epoch": NaN}',
        '{"epoch": Infinity}',
        json.dumps([1, 2]),
        json.dumps(5),
        'not json',
        '',
    ],
)
def test_epoch_field_is_none_for_a_line_it_cannot_use(line: str) -> None:
    assert EPOCH(line) is None


def test_epoch_field_reads_the_named_field() -> None:
    assert epoch_field('ts')(json.dumps({'ts': 7, 'epoch': 1})) == 7.0


# --- appending ---------------------------------------------------------------------------


def test_append_creates_the_directory_and_reports_what_it_wrote(tmp_path: Path) -> None:
    path = tmp_path / 'a' / 'b' / 'h.jsonl'
    result = append_capped_jsonl(
        path, [_line(1), _line(2).rstrip('\n')], max_bytes=10_000, epoch_of=EPOCH
    )
    assert isinstance(result, CappedWriteResult)
    assert (result.lines_written, result.compacted, result.earliest_epoch) == (2, False, 1.0)
    assert result.bytes == path.stat().st_size
    assert _epochs(path) == [1, 2]  # a missing newline is added


def test_a_torn_last_line_is_repaired_before_appending(tmp_path: Path) -> None:
    path = tmp_path / 'h.jsonl'
    path.write_text(_line(1) + '{"epoch": 2, "torn')
    append_capped_jsonl(path, [_line(3)], max_bytes=10_000, epoch_of=EPOCH)
    lines = path.read_text().splitlines()
    assert lines[0] == _line(1).strip() and lines[-1] == _line(3).strip()
    assert len(lines) == 3  # the torn line stays its own line; the new one is intact


def test_max_bytes_below_one_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='max_bytes must be at least 1'):
        append_capped_jsonl(tmp_path / 'h.jsonl', [_line(1)], max_bytes=0, epoch_of=EPOCH)
    assert not (tmp_path / 'h.jsonl').exists()


def test_duplicates_are_dropped_against_the_file_and_the_batch(tmp_path: Path) -> None:
    path = tmp_path / 'h.jsonl'
    append_capped_jsonl(path, [_line(1, run=10)], max_bytes=10_000, epoch_of=EPOCH)
    result = append_capped_jsonl(
        path,
        [_line(2, run=10), _line(3, run=11), _line(4, run=11), _line(5)],
        max_bytes=10_000,
        epoch_of=EPOCH,
        dedup_key=_run_time,
    )
    assert (result.lines_written, result.skipped_duplicates) == (2, 2)
    assert _epochs(path) == [1, 3, 5]  # a line without a key is never a duplicate


def test_concurrent_appends_of_the_same_run_write_it_once(tmp_path: Path) -> None:
    """Each writer runs in a pool so its exception, if any, surfaces (issue 076 item 17)."""
    path = tmp_path / 'h.jsonl'

    def _append() -> CappedWriteResult:
        return append_capped_jsonl(
            path, [_line(1, run=42)], max_bytes=10_000, epoch_of=EPOCH, dedup_key=_run_time
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [
            future.result(timeout=10) for future in [pool.submit(_append) for _ in range(8)]
        ]
    assert sorted(r.lines_written for r in results) == [0] * 7 + [1]
    assert _epochs(path) == [1]


def test_append_waits_for_the_lock(tmp_path: Path) -> None:
    path = tmp_path / 'h.jsonl'
    done = threading.Event()
    with (tmp_path / 'h.jsonl.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        worker = threading.Thread(
            target=lambda: (
                append_capped_jsonl(path, [_line(1)], max_bytes=10_000, epoch_of=EPOCH),
                done.set(),
            )
        )
        worker.start()
        time.sleep(0.2)
        assert not done.is_set() and not path.exists()
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    worker.join(timeout=5)
    assert done.is_set() and _epochs(path) == [1]


# --- compaction --------------------------------------------------------------------------


def test_compaction_at_the_cap_keeps_the_newest_lines_under_the_low_water_mark(
    tmp_path: Path,
) -> None:
    path = tmp_path / 'h.jsonl'
    cap = 400
    for epoch in range(40):
        result = append_capped_jsonl(path, [_line(epoch)], max_bytes=cap, epoch_of=EPOCH)
    assert result.compacted or path.stat().st_size <= cap
    assert path.stat().st_size <= cap
    epochs = _epochs(path)
    assert epochs == sorted(epochs) and epochs[-1] == 39  # oldest dropped first


def test_compaction_drops_invalid_lines_and_reports_them(tmp_path: Path) -> None:
    path = tmp_path / 'h.jsonl'
    path.write_text('junk\n' + _line(1))
    result = append_capped_jsonl(path, [_line(2)], max_bytes=10_000, epoch_of=EPOCH)
    assert (result.compacted, result.dropped_invalid, result.lines_kept) == (True, 1, 2)
    assert _epochs(path) == [1, 2]


def test_compaction_by_age_waits_for_the_grace_then_drops_old_lines(tmp_path: Path) -> None:
    path = tmp_path / 'h.jsonl'
    append_capped_jsonl(path, [_line(100), _line(200)], max_bytes=10_000, epoch_of=EPOCH)
    within_grace = append_capped_jsonl(
        path, [_line(300)], max_bytes=10_000, epoch_of=EPOCH, cutoff_epoch=150, age_grace_s=60
    )
    assert within_grace.compacted is False and _epochs(path) == [100, 200, 300]
    past_grace = append_capped_jsonl(
        path, [_line(400)], max_bytes=10_000, epoch_of=EPOCH, cutoff_epoch=250, age_grace_s=60
    )
    assert (past_grace.compacted, past_grace.dropped_by_age) == (True, 2)
    assert _epochs(path) == [300, 400]


def test_compact_jsonl_lines_is_pure_and_keeps_order() -> None:
    lines = [_line(1), 'junk\n', _line(5), _line(9).rstrip('\n')]
    kept = compact_jsonl_lines(lines, epoch_of=EPOCH, cutoff_epoch=2, max_bytes=10_000)
    assert kept == [_line(5), _line(9)]
    assert compact_jsonl_lines(lines, epoch_of=EPOCH, cutoff_epoch=None, max_bytes=1) == []
    assert COMPACT_LOW_WATER_RATIO == 0.8


# --- modes -------------------------------------------------------------------------------


def test_modes_apply_to_a_new_directory_and_file(tmp_path: Path) -> None:
    path = tmp_path / 'state' / 'h.jsonl'
    append_capped_jsonl(
        path, [_line(1)], max_bytes=10_000, epoch_of=EPOCH, file_mode=0o600, dir_mode=0o700
    )
    assert (_mode(path.parent), _mode(path)) == (0o700, 0o600)


def test_an_existing_directory_keeps_its_mode(tmp_path: Path) -> None:
    directory = tmp_path / 'state'
    directory.mkdir(mode=0o755)
    os.chmod(directory, 0o755)
    append_capped_jsonl(
        directory / 'h.jsonl',
        [_line(1)],
        max_bytes=10_000,
        epoch_of=EPOCH,
        file_mode=0o600,
        dir_mode=0o700,
    )
    assert _mode(directory) == 0o755


def test_a_compacted_file_keeps_its_file_mode(tmp_path: Path) -> None:
    path = tmp_path / 'h.jsonl'
    path.write_text('junk\n')
    os.chmod(path, 0o640)
    append_capped_jsonl(path, [_line(1)], max_bytes=10_000, epoch_of=EPOCH, file_mode=0o600)
    assert _epochs(path) == [1]
    assert _mode(path) == 0o600  # rewritten through mkstemp, then given file_mode


def test_without_modes_a_compacted_file_is_0600_as_before(tmp_path: Path) -> None:
    path = tmp_path / 'h.jsonl'
    path.write_text('junk\n')
    os.chmod(path, 0o644)
    append_capped_jsonl(path, [_line(1)], max_bytes=10_000, epoch_of=EPOCH)
    assert _mode(path) == 0o600


def test_epoch_field_rejects_non_finite_numbers_from_python() -> None:
    assert EPOCH(json.dumps({'epoch': math.inf})) is None


def test_compaction_never_loosens_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / 'h.jsonl'
    path.write_text('junk\n')
    os.chmod(path, 0o600)
    append_capped_jsonl(path, [_line(1)], max_bytes=10_000, epoch_of=EPOCH, file_mode=0o644)
    assert _epochs(path) == [1]
    assert _mode(path) == 0o600  # the stricter of the existing mode and file_mode


def _private(path: Path, line: str) -> None:
    """One append that enforces 0o600 and 0o700 on every open (the MCP call log's)."""
    append_capped_jsonl(
        path,
        [line],
        max_bytes=10_000,
        epoch_of=EPOCH,
        file_mode=0o600,
        dir_mode=0o700,
        enforce_modes=True,
    )


def test_enforced_modes_tighten_an_existing_file_and_directory(tmp_path: Path) -> None:
    """Review finding: the modes applied on creation only, so a file or directory that
    already existed with group or other bits stayed readable by other local users."""
    directory = tmp_path / 'state'
    directory.mkdir()
    os.chmod(directory, 0o755)
    path = directory / 'h.jsonl'
    path.write_text(_line(1), encoding='utf-8')
    os.chmod(path, 0o644)
    _private(path, _line(2))
    assert (_mode(directory), _mode(path)) == (0o700, 0o600)
    assert _epochs(path) == [1, 2]


def test_enforced_modes_tighten_on_every_append(tmp_path: Path) -> None:
    path = tmp_path / 'state' / 'h.jsonl'
    _private(path, _line(1))
    os.chmod(path.parent, 0o750)
    os.chmod(path, 0o640)
    _private(path, _line(2))
    assert (_mode(path.parent), _mode(path)) == (0o700, 0o600)


def test_enforced_modes_refuse_a_directory_owned_by_another_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / 'state'
    directory.mkdir()
    os.chmod(directory, 0o755)
    me = os.geteuid()
    monkeypatch.setattr(os, 'geteuid', lambda: me + 1)  # everything here is someone else's
    with pytest.raises(jsonl.NotOwnedError, match='directory is owned by another user'):
        _private(directory / 'h.jsonl', _line(1))
    assert list(directory.iterdir()) == [] and _mode(directory) == 0o755


def test_enforced_modes_refuse_a_file_owned_by_another_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / 'state' / 'h.jsonl'
    _private(path, _line(1))
    os.chmod(path, 0o644)
    real_fstat = os.fstat

    def someone_elses(fd: int) -> os.stat_result:
        st = real_fstat(fd)
        fields = list(st[:10])
        fields[stat.ST_UID] = st.st_uid + 1
        return os.stat_result(fields)

    with monkeypatch.context() as patched:
        patched.setattr(os, 'fstat', someone_elses)
        with pytest.raises(jsonl.NotOwnedError, match='file is owned by another user'):
            _private(path, _line(2))
    assert _epochs(path) == [1] and _mode(path) == 0o644


def test_without_enforcement_an_existing_file_keeps_its_mode(tmp_path: Path) -> None:
    """Without ``enforce_modes`` a mode is set on creation only (the generic path; every
    history enforces since issue 076 items 7 and 32)."""
    path = tmp_path / 'h.jsonl'
    path.write_text(_line(1), encoding='utf-8')
    os.chmod(path, 0o644)
    append_capped_jsonl(path, [_line(2)], max_bytes=10_000, epoch_of=EPOCH, file_mode=0o600)
    assert _mode(path) == 0o644


# --- the lock: its mode and a bounded wait -------------------------------


def _lock_of(path: Path) -> Path:
    return path.with_name(path.name + '.lock')


def test_the_lock_is_created_with_the_file_mode(tmp_path: Path) -> None:
    """VS-1: the lock was created 0o644 under umask 022, so in a directory other accounts can
    search, any of them could open it and hold its flock."""
    directory = tmp_path / 'state'
    directory.mkdir()
    os.chmod(directory, 0o755)
    path = directory / 'h.jsonl'
    with umask(0o022):
        append_capped_jsonl(path, [_line(1)], max_bytes=10_000, epoch_of=EPOCH, file_mode=0o600)
    assert (_mode(directory), _mode(path), _mode(_lock_of(path))) == (0o755, 0o600, 0o600)


def test_without_a_file_mode_the_lock_keeps_the_umask_mode(tmp_path: Path) -> None:
    """A caller that gives no mode gets a lock created as before (the histories all give one
    since issue 076 item 32; this pins the generic path)."""
    path = tmp_path / 'h.jsonl'
    with umask(0o022):
        append_capped_jsonl(path, [_line(1)], max_bytes=10_000, epoch_of=EPOCH)
    assert _mode(_lock_of(path)) == 0o644


def test_enforced_modes_tighten_an_existing_lock(tmp_path: Path) -> None:
    path = tmp_path / 'state' / 'h.jsonl'
    _private(path, _line(1))
    os.chmod(_lock_of(path), 0o644)
    _private(path, _line(2))
    assert (_mode(_lock_of(path)), _mode(path)) == (0o600, 0o600)
    assert _epochs(path) == [1, 2]


@pytest.mark.parametrize('kind', ['lock file', 'file'])
def test_enforced_modes_refuse_a_lock_or_file_owned_by_another_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Only the one descriptor is someone else's: the lock, or (a pin) the file itself."""
    path = tmp_path / 'state' / 'h.jsonl'
    _private(path, _line(1))
    theirs = os.stat(_lock_of(path) if kind == 'lock file' else path)
    real_fstat = os.fstat

    def someone_elses(fd: int) -> os.stat_result:
        st = real_fstat(fd)
        if (st.st_dev, st.st_ino) != (theirs.st_dev, theirs.st_ino):
            return st
        fields = list(st[:10])
        fields[stat.ST_UID] = st.st_uid + 1
        return os.stat_result(fields)

    with monkeypatch.context() as patched:
        patched.setattr(os, 'fstat', someone_elses)
        with pytest.raises(jsonl.NotOwnedError, match=f'^the {kind} is owned by another user$'):
            _private(path, _line(2))
    assert _epochs(path) == [1]


@pytest.mark.parametrize('link', ['file', 'lock'])
def test_enforced_modes_refuse_a_symbolic_link_in_place_of_the_file_or_its_lock(
    tmp_path: Path, link: str
) -> None:
    directory = tmp_path / 'state'
    directory.mkdir(mode=0o700)
    path = directory / 'h.jsonl'
    target = tmp_path / 'elsewhere.jsonl'
    target.write_text(_line(9), encoding='utf-8')
    (path if link == 'file' else _lock_of(path)).symlink_to(target)
    with pytest.raises(OSError) as raised:
        _private(path, _line(1))
    assert raised.value.errno == errno.ELOOP
    assert target.read_text(encoding='utf-8') == _line(9)  # nothing written through the link
    if link == 'lock':
        assert not path.exists()


def test_a_bounded_wait_gives_up_on_a_held_lock_and_appends_nothing(tmp_path: Path) -> None:
    """VS-1's probe: LOCK_EX on an O_RDONLY descriptor kept every writer waiting."""
    path = tmp_path / 'h.jsonl'
    append_capped_jsonl(path, [_line(1)], max_bytes=10_000, epoch_of=EPOCH)

    def _append() -> object:
        return append_capped_jsonl(
            path, [_line(2)], max_bytes=10_000, epoch_of=EPOCH, lock_timeout_s=0.2
        )

    with held_read_only(_lock_of(path)):
        held = run_bounded(_append, join_s=5)
    assert held.done, 'the append waited on the held lock past its limit'
    assert isinstance(held.error, jsonl.LockTimeoutError) and isinstance(held.error, OSError)
    assert 0.2 <= held.elapsed < 1.0
    assert _epochs(path) == [1]
    released = run_bounded(_append, join_s=5)
    assert released.done and released.error is None
    assert _epochs(path) == [1, 2]


class _CountingFcntl:
    """``jsonl``'s ``fcntl`` for one test: the real ``flock``, counting each refusal."""

    LOCK_EX = fcntl.LOCK_EX
    LOCK_NB = fcntl.LOCK_NB
    LOCK_UN = fcntl.LOCK_UN

    def __init__(self) -> None:
        self.blocked = 0

    def flock(self, fd: int, operation: int) -> None:
        try:
            fcntl.flock(fd, operation)
        except BlockingIOError:
            self.blocked += 1
            raise


def test_a_bounded_wait_takes_a_lock_released_during_the_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding: the contention the call log stays on for. A loop that slept out the whole
    limit would fail on the time, a write that took the lock without appending on the lines,
    and a writer that found the lock already free on the refusals."""
    path = tmp_path / 'h.jsonl'
    append_capped_jsonl(path, [_line(1)], max_bytes=10_000, epoch_of=EPOCH)
    counting = _CountingFcntl()
    monkeypatch.setattr(jsonl, 'fcntl', counting)  # the holder and the timer keep the real one
    fd = os.open(_lock_of(path), os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release = threading.Timer(0.1, fcntl.flock, args=(fd, fcntl.LOCK_UN))
        release.start()
        try:
            took = run_bounded(
                lambda: append_capped_jsonl(
                    path, [_line(2)], max_bytes=10_000, epoch_of=EPOCH, lock_timeout_s=2
                ),
                join_s=5,
            )
        finally:
            release.cancel()
            release.join()
    finally:
        os.close(fd)  # also releases the lock if the timer did not
    assert took.done, 'the append waited on the released lock past its limit'
    assert took.error is None
    assert counting.blocked >= 1, 'the append found the lock free: it never met it held'
    assert took.elapsed < 1.0, 'the append slept past the release'
    assert _epochs(path) == [1, 2]


def _open_descriptors() -> int | None:
    """How many descriptors this process has open, or None where ``/dev/fd`` isn't there."""
    try:
        return len(os.listdir('/dev/fd'))
    except OSError:
        return None


@pytest.mark.parametrize('limit', [0, -0.1, math.nan])
def test_a_limit_of_zero_or_less_or_nan_gives_up_at_once_on_a_held_lock(
    tmp_path: Path, limit: float
) -> None:
    """Review finding: the deadline check raises on each of these; none of them loops."""
    path = tmp_path / 'h.jsonl'
    append_capped_jsonl(path, [_line(1)], max_bytes=10_000, epoch_of=EPOCH)

    def _append() -> object:
        return append_capped_jsonl(
            path, [_line(2)], max_bytes=10_000, epoch_of=EPOCH, lock_timeout_s=limit
        )

    with held_read_only(_lock_of(path)):
        before = _open_descriptors()
        held = run_bounded(_append, join_s=5)
        after = _open_descriptors()
    assert held.done, f'a limit of {limit} waited on the held lock'
    assert isinstance(held.error, jsonl.LockTimeoutError)
    assert held.elapsed < 0.5
    assert _epochs(path) == [1]
    if before is not None:
        assert after == before, 'the timed-out append left a descriptor open'


def test_a_limit_of_zero_still_appends_when_the_lock_is_free(tmp_path: Path) -> None:
    """The first ``LOCK_NB`` attempt comes before the deadline check, so a free lock is taken."""
    path = tmp_path / 'h.jsonl'
    append_capped_jsonl(path, [_line(1)], max_bytes=10_000, epoch_of=EPOCH)
    append_capped_jsonl(path, [_line(2)], max_bytes=10_000, epoch_of=EPOCH, lock_timeout_s=0)
    assert _epochs(path) == [1, 2]


# --- readers ------------------------------------------------------------------------------


def test_the_readers_skip_the_incomplete_last_line_of_an_append_in_progress(
    tmp_path: Path,
) -> None:
    # Readers take no lock, and an append writes to the live file: mid-append, a reader can
    # see the last line cut short. Both readers of these files must skip it.
    from unifi_mapper.analysis.counter_history import read_port_history
    from unifi_mapper.diagnostics.wan_history import read_speedtest_history

    record = {'epoch': 1_790_000_000, 'device_id': 'a1', 'ports': [{'port_idx': 5}]}
    counters = tmp_path / 'counters.jsonl'
    counters.write_text(json.dumps(record) + '\n' + json.dumps(record)[:-9])
    assert [p.epoch for p in read_port_history('a1', 5, path=counters)] == [1_790_000_000]

    speedtests = tmp_path / 'speedtests.jsonl'
    speedtests.write_text(_line(1_790_000_000, run=1) + _line(1_790_000_001, run=2)[:-12])
    result = read_speedtest_history(speedtests)
    assert (result['total'], [e['epoch'] for e in result['entries']]) == (1, [1_790_000_000])
