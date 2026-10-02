"""Tests for the capped JSON Lines port counter history (issues 002 and 004)."""

import fcntl
import json
import os
import pytest
import threading
import time
from pathlib import Path
from tests.fixtures_unifi import NOW, SWITCH_ID, SWITCH_MAC, SWITCH_NAME, fake_switch
from typing import Any
from unifi_mapper.analysis import counter_history
from unifi_mapper.analysis.counter_history import (
    DEFAULT_RETENTION_DAYS,
    HISTORY_FILENAME,
    HistoryPoint,
    append_history,
    build_history_records,
    compact_history_lines,
    default_history_path,
    read_port_history,
    summarise_port_history,
)
from unifi_mapper.analysis.port_counter_baseline import (
    default_baseline_path,
    snapshots_from_devices,
    state_dir,
)


DAY = 86400


def _record(
    epoch: float, *, device_id: str = SWITCH_ID, uptime: int = 1000, **port: Any
) -> dict[str, Any]:
    return {
        'schema_version': 1,
        'taken_at': f't{int(epoch)}',
        'epoch': epoch,
        'device_id': device_id,
        'uptime': uptime,
        'ports': [{'port_idx': 5, 'rx_errors': 0, 'rx_crc_errors': 0, **port}],
    }


def _lines(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding='utf-8')
    assert text.endswith('\n')
    return [json.loads(line) for line in text.splitlines()]


# --- state root and baseline snapshots ---------------------------------------------


def test_state_dir_follows_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    assert state_dir() == tmp_path / 'state' / 'unifi_mapper'
    assert default_baseline_path() == tmp_path / 'state' / 'unifi_mapper' / 'port-counters.json'
    assert default_history_path() == tmp_path / 'state' / 'unifi_mapper' / HISTORY_FILENAME
    assert not (tmp_path / 'state').exists()  # resolving a path creates nothing


def test_state_dir_defaults_to_local_state(monkeypatch):
    monkeypatch.delenv('XDG_STATE_HOME')
    assert state_dir() == Path.home() / '.local' / 'state' / 'unifi_mapper'


def test_snapshots_from_devices_keys_switch_ports_and_reads_crc():
    unadopted = {'type': 'usw', 'port_table': [{'port_idx': 1, 'rx_errors': 9}]}
    ap = {'_id': 'ap1', 'type': 'uap', 'port_table': [{'port_idx': 1, 'rx_errors': 9}]}
    snapshots = snapshots_from_devices([fake_switch(), unadopted, ap], timestamp='T')
    port5 = snapshots[f'{SWITCH_ID}:5']
    assert port5.timestamp == 'T'
    assert port5.rx_errors == 7 and port5.crc_errors == 3  # crc from port_stats
    assert all(key.startswith(f'{SWITCH_ID}:') for key in snapshots)


# --- building records ----------------------------------------------------------------


def test_build_history_records_skips_devices_without_id_and_non_switches():
    unadopted = {'type': 'usw', 'name': 'pending', 'port_table': [{'port_idx': 1}]}
    ap = {'_id': 'ap1', 'type': 'uap', 'port_table': [{'port_idx': 1}]}
    records = build_history_records([unadopted, fake_switch(), ap], taken_at='T', epoch=NOW)

    assert [r['device_id'] for r in records] == [SWITCH_ID]
    record = records[0]
    assert record['schema_version'] == 1 and record['taken_at'] == 'T' and record['epoch'] == NOW
    assert record['device_mac'] == SWITCH_MAC and record['device_name'] == SWITCH_NAME
    assert record['uptime'] == 86400 and record['last_seen'] == NOW - 20
    port5 = next(p for p in record['ports'] if p['port_idx'] == 5)
    assert port5 == {
        'port_idx': 5,
        'up': True,
        'speed': 5000,
        'full_duplex': True,
        'rx_errors': 7,
        'tx_errors': 0,
        'rx_dropped': 0,
        'tx_dropped': 0,
        'rx_crc_errors': 3,
        'link_down_count': 2,
        'rx_bytes': 5000,
        'tx_bytes': 10000,
    }
    json.dumps(records)  # serialisable as-is


# --- appending and compaction -------------------------------------------------------


def test_append_creates_the_directory_under_xdg_state(tmp_path):
    target = default_history_path()
    assert not target.parent.exists()

    result = append_history([_record(NOW)], now=NOW)

    assert target.exists() and result.path == str(target)
    assert result.records_written == 1 and result.compacted is False
    assert result.retention_days == DEFAULT_RETENTION_DAYS
    assert target.is_relative_to(tmp_path)  # the per-test XDG_STATE_HOME isolation
    assert len(_lines(target)) == 1


def test_age_retention_drops_old_lines(tmp_path):
    path = tmp_path / 'history.jsonl'
    old_lines = [_record(NOW - 20 * DAY), _record(NOW - 2 * DAY)]
    path.write_text(''.join(json.dumps(r) + '\n' for r in old_lines), encoding='utf-8')

    result = append_history([_record(NOW)], path=path, retention_days=14, now=NOW)

    assert result.compacted is True and result.dropped_by_age == 1
    assert [line['epoch'] for line in _lines(path)] == [NOW - 2 * DAY, NOW]


def test_byte_cap_drops_the_oldest_lines_down_to_the_low_water_mark(tmp_path):
    path = tmp_path / 'history.jsonl'
    for offset in range(5):
        append_history([_record(NOW + offset)], path=path, now=NOW + offset)
    line_size = len(path.read_text().splitlines(True)[0].encode())
    cap = line_size * 3

    result = append_history([_record(NOW + 5)], path=path, max_bytes=cap, now=NOW + 5)

    # 6 lines over a 3-line cap: trimmed to 80% of the cap (2 lines), not to just under it.
    assert result.compacted and result.dropped_by_size == 4 and result.lines_kept == 2
    assert [line['epoch'] for line in _lines(path)] == [NOW + 4, NOW + 5]
    assert path.stat().st_size <= cap * counter_history.COMPACT_LOW_WATER_RATIO


def test_the_append_after_a_size_compaction_does_not_rewrite_the_file(tmp_path):
    path = tmp_path / 'history.jsonl'
    append_history([_record(NOW)], path=path, now=NOW)
    line_size = len(path.read_text().encode())
    cap = line_size * 10
    for offset in range(1, 11):
        filled = append_history(
            [_record(NOW + offset)], path=path, max_bytes=cap, now=NOW + offset
        )
    assert filled.compacted and filled.lines_kept == 8  # 11 lines over a 10-line cap -> 80%
    inode = path.stat().st_ino

    rewrites = []
    for offset in range(11, 14):
        result = append_history(
            [_record(NOW + offset)], path=path, max_bytes=cap, now=NOW + offset
        )
        rewrites.append((result.compacted, path.stat().st_ino == inode))

    # Regression (code-review F6): without a low-water mark every append past the cap
    # rewrote the whole file. Now the two appends after a compaction append in place,
    # and the cap is still enforced by the next one.
    assert rewrites == [(False, True), (False, True), (True, False)]
    assert path.stat().st_size <= cap


def test_age_compaction_waits_for_the_grace_period_then_drops_to_the_cutoff(tmp_path):
    path = tmp_path / 'history.jsonl'
    days = 14
    lines = [_record(NOW - (days * DAY) - 3600), _record(NOW - days * DAY + 60), _record(NOW - 1)]
    path.write_text(''.join(json.dumps(r) + '\n' for r in lines), encoding='utf-8')
    inode = path.stat().st_ino

    # One hour past the cutoff is inside the one-day grace: appended in place.
    quiet = append_history([_record(NOW)], path=path, retention_days=days, now=NOW)
    assert quiet.compacted is False and path.stat().st_ino == inode
    assert quiet.span_days == round((days * DAY + 3600) / DAY, 1)

    # Once the oldest line is past the grace, every line older than the cutoff goes.
    later = NOW + DAY
    swept = append_history([_record(later)], path=path, retention_days=days, now=later)
    assert swept.compacted is True and swept.dropped_by_age == 2
    assert [line['epoch'] for line in _lines(path)] == [NOW - 1, NOW, later]
    assert swept.earliest_epoch == NOW - 1


def test_write_result_reports_the_window_the_file_holds(tmp_path):
    path = tmp_path / 'history.jsonl'
    append_history([_record(NOW - 2 * DAY)], path=path, now=NOW - 2 * DAY)

    result = append_history([_record(NOW)], path=path, now=NOW)

    assert result.earliest_epoch == NOW - 2 * DAY
    assert result.span_days == 2.0


def test_compaction_leaves_valid_jsonl_and_counts_unparsable_lines(tmp_path):
    path = tmp_path / 'history.jsonl'
    old, kept = _record(NOW - 30 * DAY), _record(NOW - 1)
    path.write_text(
        json.dumps(old) + '\n{not json\n[1, 2]\n' + json.dumps(kept) + '\n{"epoch": "x"}',
        encoding='utf-8',
    )

    # The too-old first line triggers compaction, which also drops unparsable lines
    # (readers skip them in the meantime). The last line had no newline.
    result = append_history([_record(NOW)], path=path, now=NOW)

    assert result.compacted and result.dropped_unparsable == 3 and result.dropped_by_age == 1
    assert [line['epoch'] for line in _lines(path)] == [NOW - 1, NOW]
    leftovers = [p for p in path.parent.iterdir() if p.name.endswith('.tmp')]
    assert leftovers == []  # the temp file was renamed into place


def test_a_torn_last_line_does_not_swallow_the_next_record(tmp_path):
    path = tmp_path / 'history.jsonl'
    path.write_text(json.dumps(_record(NOW - 1)), encoding='utf-8')  # no trailing newline

    append_history([_record(NOW)], path=path, now=NOW)

    assert [line['epoch'] for line in _lines(path)] == [NOW - 1, NOW]


def test_no_rewrite_when_under_both_caps(tmp_path):
    path = tmp_path / 'history.jsonl'
    append_history([_record(NOW)], path=path, now=NOW)
    inode = path.stat().st_ino

    result = append_history([_record(NOW + 1)], path=path, now=NOW + 1)

    assert result.compacted is False and result.lines_kept is None
    assert path.stat().st_ino == inode  # appended in place, not replaced


@pytest.mark.parametrize('days', [0, 366])
def test_retention_days_out_of_range_is_rejected(tmp_path, days):
    with pytest.raises(ValueError, match='retention_days'):
        append_history([_record(NOW)], path=tmp_path / 'h.jsonl', retention_days=days, now=NOW)
    assert not (tmp_path / 'h.jsonl').exists()


def test_compact_history_lines_is_pure_and_ordered():
    lines = [json.dumps({'epoch': e}) for e in (1, 5, 10)] + ['junk']
    assert compact_history_lines(lines, cutoff_epoch=5, max_bytes=10_000) == [
        '{"epoch": 5}\n',
        '{"epoch": 10}\n',
    ]
    assert compact_history_lines(lines, cutoff_epoch=0, max_bytes=14) == ['{"epoch": 10}\n']
    assert compact_history_lines(lines, cutoff_epoch=0, max_bytes=1) == []


def test_two_concurrent_appenders_lose_nothing(tmp_path):
    path = tmp_path / 'history.jsonl'

    def writer(base: int) -> None:
        for i in range(25):
            append_history([_record(NOW + base + i)], path=path, now=NOW + base + i)

    threads = [threading.Thread(target=writer, args=(base,)) for base in (0, 1000)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    epochs = sorted(line['epoch'] for line in _lines(path))
    assert epochs == sorted([NOW + i for i in range(25)] + [NOW + 1000 + i for i in range(25)])


def test_append_waits_for_the_lock(tmp_path):
    path = tmp_path / 'history.jsonl'
    lock_path = tmp_path / 'history.jsonl.lock'
    done = threading.Event()
    with lock_path.open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        worker = threading.Thread(
            target=lambda: (append_history([_record(NOW)], path=path, now=NOW), done.set())
        )
        worker.start()
        time.sleep(0.2)
        assert not done.is_set() and not path.exists()  # blocked behind the lock
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    worker.join(timeout=5)
    assert done.is_set() and len(_lines(path)) == 1


# --- reading and summarising --------------------------------------------------------


def test_reader_filters_by_device_port_and_time(tmp_path):
    path = tmp_path / 'history.jsonl'
    records = [
        _record(NOW, rx_errors=1),
        _record(NOW + 1, device_id='other', rx_errors=99),
        {**_record(NOW + 2), 'ports': [{'port_idx': 6, 'rx_errors': 99}]},
        _record(NOW + 3, rx_errors=2),
    ]
    path.write_text(''.join(json.dumps(r) + '\n' for r in records) + 'junk\n')
    before = (path.read_bytes(), os.stat(path).st_mtime_ns)

    points = read_port_history(SWITCH_ID, 5, path=path)
    since = read_port_history(SWITCH_ID, 5, path=path, since_epoch=NOW + 1)

    assert [(p.epoch, p.rx_errors) for p in points] == [(NOW, 1), (NOW + 3, 2)]
    assert [p.epoch for p in since] == [NOW + 3]
    assert (path.read_bytes(), os.stat(path).st_mtime_ns) == before
    assert read_port_history(SWITCH_ID, 5, path=tmp_path / 'missing.jsonl') == []


def _point(epoch: float, *, uptime: int = 1000, **counters: int) -> HistoryPoint:
    return HistoryPoint(taken_at=f't{int(epoch)}', epoch=epoch, uptime=uptime, **counters)


def test_summary_first_increase_and_deltas():
    points = [
        _point(3, rx_crc_errors=3, rx_errors=7),
        _point(1, rx_crc_errors=0, rx_errors=7),  # out of order on purpose
        _point(2, rx_crc_errors=3, rx_errors=7),
    ]
    view = summarise_port_history(points, limit=10, path='p', found=True)

    assert view.records == 3 and view.earliest == 't1' and view.latest == 't3'
    first = view.first_increase['rx_crc_errors']
    assert first is not None and (first.taken_at, first.previous, first.value) == ('t2', 0, 3)
    assert view.first_increase['rx_errors'] is None
    assert view.deltas['rx_crc_errors'] == 3 and view.deltas['rx_errors'] == 0
    assert view.deltas['tx_errors'] is None  # never recorded
    assert view.resets == [] and view.truncated is False
    assert [p.epoch for p in view.points] == [1, 2, 3]  # newest last


def test_summary_resets_suppress_deltas():
    points = [
        _point(1, uptime=5000, rx_errors=40),
        _point(2, uptime=10, rx_errors=0),  # reboot
        _point(3, uptime=70, rx_errors=5),
        _point(4, uptime=130, rx_errors=2),  # cleared
    ]
    view = summarise_port_history(points)

    assert [(r.epoch, r.reason) for r in view.resets] == [(2, 'uptime'), (4, 'rx_errors')]
    assert all(value is None for value in view.deltas.values())
    first = view.first_increase['rx_errors']
    assert first is not None and first.epoch == 3  # pairs across a reset are skipped


def test_summary_truncates_to_the_newest_points():
    view = summarise_port_history([_point(e, rx_errors=0) for e in range(1, 61)], limit=48)
    assert view.records == 60 and view.truncated is True
    assert len(view.points) == 48 and view.points[-1].epoch == 60 and view.points[0].epoch == 13


def test_summary_of_nothing_is_empty():
    view = summarise_port_history([], path='p', found=False)
    assert view.records == 0 and view.found is False and view.points == []
    assert view.first_increase == {} and view.deltas == {}


def test_module_never_writes_on_import_or_read(tmp_path):
    read_port_history(SWITCH_ID, 5)
    summarise_port_history(read_port_history(SWITCH_ID, 5))
    assert not default_history_path().parent.exists()
    assert counter_history.HISTORY_POINTS_LIMIT == 48
