"""The shared capped JSON Lines writer (``core/utils/jsonl``).

``tests/analysis/test_counter_history.py`` passes unchanged over it (the refactor's proof);
these tests pin the generic parts the newer histories use: deduplication under the lock,
modes, and ``epoch_field``.
"""

import fcntl
import json
import math
import os
import pytest
import stat
import threading
import time
from pathlib import Path
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
    path = tmp_path / 'h.jsonl'

    def _append() -> None:
        append_capped_jsonl(
            path, [_line(1, run=42)], max_bytes=10_000, epoch_of=EPOCH, dedup_key=_run_time
        )

    threads = [threading.Thread(target=_append) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
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
