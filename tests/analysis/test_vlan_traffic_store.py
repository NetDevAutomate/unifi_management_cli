"""The per-VLAN traffic store (``analysis/vlan_traffic_store.py``) and its two MCP tools.

Ported from the July work (a local archive, not in the repo) and adapted: documentation values
and generic network names; the store under the XDG state directory (never the working
directory) with ``--db`` instead of ``UNIFI_VLAN_TRAFFIC_DB``; reads open it read-only
through a file URI and never create it; SQLite's default rollback journal (not WAL) with
errors mapped by name; the rollups' cadence tests (the sweep, the five-minute cadence and the
double run) unchanged in logic. No controller and no SSH here.
"""

import inspect
import os
import pytest
import shutil
import sqlite3
import stat
from pathlib import Path
from typing import Any
from unifi_mapper.analysis import vlan_traffic_store as store
from unifi_mapper.analysis.vlan_traffic_store import (
    GAP_THRESHOLD_SECONDS,
    RAW_RETENTION_SECONDS,
    compute_rates,
    default_db_path,
    floor_to_day,
    floor_to_hour,
    get_vlan_traffic_report,
    list_vlan_traffic_periods,
    open_store,
    read_vlan_traffic_periods,
    read_vlan_traffic_report,
    rollup_day,
    rollup_hour,
    run_rollups,
)
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.diagnostics.wan_history import get_wan_speedtest_history


FAR_FUTURE = 2_000_000_000  # so the 'now' and '1d' windows include the rows


def _writable(path: Path) -> sqlite3.Connection:
    return open_store(path, writable=True)


def _insert_raw(conn: sqlite3.Connection, ts: int, vlan: int, name: str, rx: int, tx: int) -> None:
    conn.execute(
        'INSERT INTO raw_samples (ts_utc, vlan_id, network_name, iface, rx_bytes, tx_bytes) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (ts, vlan, name, f'br{vlan}', rx, tx),
    )


def _insert_rollup(conn: sqlite3.Connection, table: str, bucket: int, vlan: int, *v: Any) -> None:
    column = 'hour_utc' if table == 'hourly_rollup' else 'day_utc'
    conn.execute(
        f'INSERT INTO {table} ({column}, vlan_id, network_name, avg_rx_bps, avg_tx_bps, '
        'peak_rx_bps, peak_tx_bps, sample_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (bucket, vlan, f'VLAN {vlan}', *v),
    )


# --- compute_rates, rollups, floors (July's, unchanged in logic) --------------------------


def test_the_first_sample_has_no_rate() -> None:
    assert compute_rates(None, {'ts_utc': 1000, 'rx_bytes': 100, 'tx_bytes': 50}) is None


def test_a_normal_interval_is_bits_per_second() -> None:
    prev = {'ts_utc': 1000, 'rx_bytes': 1_000_000, 'tx_bytes': 500_000}
    cur = {'ts_utc': 1060, 'rx_bytes': 1_060_000, 'tx_bytes': 530_000}
    assert compute_rates(prev, cur) == {'rx_bps': 8000.0, 'tx_bps': 4000.0}


@pytest.mark.parametrize(
    'cur',
    [
        {'ts_utc': 1060, 'rx_bytes': 100, 'tx_bytes': 50},  # both counters reset
        {'ts_utc': 1060, 'rx_bytes': 2000, 'tx_bytes': 10},  # tx alone reset
        {'ts_utc': 1000, 'rx_bytes': 2000, 'tx_bytes': 6000},  # no time passed
    ],
    ids=['reset', 'tx reset', 'zero interval'],
)
def test_a_reset_or_an_empty_interval_has_no_rate(cur: dict[str, int]) -> None:
    prev = {'ts_utc': 1000, 'rx_bytes': 1000, 'tx_bytes': 5000}
    assert compute_rates(prev, cur) is None


def test_flat_counters_are_a_zero_rate() -> None:
    sample = {'ts_utc': 1000, 'rx_bytes': 100, 'tx_bytes': 50}
    assert compute_rates(sample, {**sample, 'ts_utc': 1060}) == {'rx_bps': 0.0, 'tx_bps': 0.0}


def test_an_hour_rollup_averages_and_peaks() -> None:
    rows = [
        {'bucket': 3600, 'vlan_id': 10, 'network_name': 'LAN', 'rx_bps': rx, 'tx_bps': rx / 10}
        for rx in (100.0, 300.0, 200.0)
    ]
    (row,) = rollup_hour(rows)
    assert (row['hour_utc'], row['avg_rx_bps'], row['peak_rx_bps']) == (3600, 200.0, 300.0)
    assert (row['avg_tx_bps'], row['peak_tx_bps'], row['sample_count']) == (20.0, 30.0, 3)
    assert rollup_hour([]) == []


def test_rollups_separate_vlans_and_buckets() -> None:
    rows = [
        {'bucket': 3600, 'vlan_id': 10, 'network_name': 'A', 'rx_bps': 100.0, 'tx_bps': 0.0},
        {'bucket': 3600, 'vlan_id': 20, 'network_name': 'B', 'rx_bps': 500.0, 'tx_bps': 0.0},
        {'bucket': 7200, 'vlan_id': 10, 'network_name': 'A', 'rx_bps': 900.0, 'tx_bps': 0.0},
    ]
    keyed = {(r['hour_utc'], r['vlan_id']): r['avg_rx_bps'] for r in rollup_hour(rows)}
    assert keyed == {(3600, 10): 100.0, (3600, 20): 500.0, (7200, 10): 900.0}
    day = [{**row, 'bucket': 86400} for row in rows[:1]] * 2
    (daily,) = rollup_day(day)
    assert (daily['day_utc'], daily['sample_count']) == (86400, 2)


def test_floors() -> None:
    assert [floor_to_hour(t) for t in (3661, 3600, 3599)] == [3600, 3600, 0]
    assert [floor_to_day(t) for t in (86401, 86400, 86399)] == [86400, 86400, 0]


# --- where the store lives, and how it is opened -------------------------------------------


def test_the_default_store_is_under_xdg_state_and_never_the_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    assert default_db_path() == tmp_path / 'xdg' / 'unifi_mapper' / 'vlan-traffic.sqlite3'
    monkeypatch.delenv('XDG_STATE_HOME')
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    path = default_db_path()
    assert path.is_absolute() and path.parts[-4:-1] == ('.local', 'state', 'unifi_mapper')
    assert not path.parent.exists()  # asking creates nothing


def test_a_writable_open_creates_the_schema_with_private_modes(tmp_path: Path) -> None:
    path = tmp_path / 'new' / 'store.sqlite3'
    _writable(path).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    with sqlite3.connect(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'raw_samples', 'hourly_rollup', 'daily_rollup', 'rollup_state'} <= tables
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'


def test_an_existing_directory_keeps_its_mode(tmp_path: Path) -> None:
    folder = tmp_path / 'shared'
    folder.mkdir(mode=0o755)
    folder.chmod(0o755)
    _writable(folder / 'store.sqlite3').close()
    assert stat.S_IMODE(folder.stat().st_mode) == 0o755


def test_a_read_of_a_missing_store_is_no_data_and_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / 'absent' / 'store.sqlite3'
    for read in (
        lambda: read_vlan_traffic_report('now', path),
        lambda: read_vlan_traffic_periods(path),
    ):
        with pytest.raises(ToolError) as caught:
            read()
        assert caught.value.error_code == ErrorCodes.NO_DATA
        assert 'vlan-traffic sample' in (caught.value.suggestion or '')
    assert not path.parent.exists()


def test_a_read_only_open_works_on_a_path_holding_uri_characters(tmp_path: Path) -> None:
    path = tmp_path / 'odd?name#1 %41' / 'store.sqlite3'
    with _writable(path) as conn:
        _insert_raw(conn, 1000, 10, 'LAN', 0, 0)
    assert read_vlan_traffic_periods(path)['raw']['count'] == 1
    with pytest.raises(sqlite3.OperationalError):  # the read-only handle refuses a write
        open_store(path, writable=False).execute('DELETE FROM raw_samples')


def test_a_hot_journal_asks_for_recovery_and_rollup_recovers_it(tmp_path: Path) -> None:
    live = tmp_path / 'live.sqlite3'
    _writable(live).close()
    conn = sqlite3.connect(live, isolation_level=None)
    conn.execute('PRAGMA cache_size=1')
    conn.execute('BEGIN')
    for i in range(3000):  # enough to spill the open transaction into the journal
        _insert_raw(conn, i, 10, 'LAN', i, i)
    crashed = tmp_path / 'crashed.sqlite3'
    shutil.copyfile(live, crashed)
    shutil.copyfile(f'{live}-journal', f'{crashed}-journal')  # as a crashed sampler left it
    conn.execute('ROLLBACK')
    conn.close()
    with pytest.raises(ToolError) as caught:
        read_vlan_traffic_periods(crashed)
    assert caught.value.error_code == ErrorCodes.API_ERROR
    assert (
        'needs recovery' in caught.value.message and 'vlan-traffic rollup' in caught.value.message
    )
    run_rollups(crashed)
    assert read_vlan_traffic_periods(crashed)['raw']['count'] == 0
    assert not Path(f'{crashed}-journal').exists()


def test_a_store_held_by_a_writer_is_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / 'store.sqlite3'
    _writable(path).close()
    monkeypatch.setattr(store, 'BUSY_TIMEOUT_SECONDS', 0.05)
    writer = sqlite3.connect(path, isolation_level=None)
    writer.execute('BEGIN EXCLUSIVE')
    try:
        with pytest.raises(ToolError) as caught:
            read_vlan_traffic_periods(path)
    finally:
        writer.execute('ROLLBACK')
        writer.close()
    assert caught.value.error_code == ErrorCodes.API_ERROR
    assert caught.value.message.startswith('store busy')


def test_a_file_that_is_not_a_store_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    path.write_bytes(b'not a database' * 100)
    with pytest.raises(ToolError) as caught:
        read_vlan_traffic_periods(path)
    assert caught.value.message == 'store unreadable: SQLITE_NOTADB'


# --- the report and the coverage (July's logic) --------------------------------------------


@pytest.mark.parametrize(
    ('period', 'tier'),
    [('now', 'raw'), ('1d', 'raw'), ('1w', 'hourly'), ('1m', 'hourly'), ('1y', 'daily')],
)
def test_each_period_reads_its_tier(tmp_path: Path, period: str, tier: str) -> None:
    path = tmp_path / 'store.sqlite3'
    _writable(path).close()
    report = read_vlan_traffic_report(period, path)
    assert (report['period'], report['methodology']['tier_used'], report['vlans']) == (
        period,
        tier,
        [],
    )


def test_an_unknown_period_is_refused(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    _writable(path).close()
    with pytest.raises(ToolError) as caught:
        read_vlan_traffic_report('never', path)
    assert caught.value.error_code == ErrorCodes.CONFIG_INVALID


def test_the_raw_tier_computes_rates_from_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store.time, 'time', lambda: float(FAR_FUTURE))
    path = tmp_path / 'store.sqlite3'
    with _writable(path) as conn:
        _insert_raw(conn, FAR_FUTURE - 60, 10, 'LAN', 0, 0)
        _insert_raw(conn, FAR_FUTURE, 10, 'LAN', 1_000_000, 500_000)
    (vlan,) = read_vlan_traffic_report('now', path)['vlans']
    assert vlan['vlan_id'] == 10 and vlan['avg_rx_bps'] > 0
    assert (vlan['samples'], vlan['coverage_pct']) == (2, 50.0)


def test_the_hourly_and_daily_tiers_fold_rollups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store.time, 'time', lambda: float(FAR_FUTURE))
    path = tmp_path / 'store.sqlite3'
    hour, day = floor_to_hour(FAR_FUTURE), floor_to_day(FAR_FUTURE)
    with _writable(path) as conn:
        _insert_rollup(conn, 'hourly_rollup', hour, 20, 100.0, 10.0, 400.0, 40.0, 60)
        _insert_rollup(conn, 'hourly_rollup', hour - 3600, 20, 300.0, 30.0, 600.0, 60.0, 60)
        _insert_rollup(conn, 'daily_rollup', day, 10, 100.0, 10.0, 500.0, 50.0, 24)
    (hourly,) = read_vlan_traffic_report('1w', path)['vlans']
    assert (hourly['avg_rx_bps'], hourly['peak_rx_bps'], hourly['samples']) == (200.0, 600.0, 2)
    yearly = read_vlan_traffic_report('1y', path)
    assert yearly['vlans'][0]['peak_rx_bps'] == 500.0
    assert any('smooth' in c.lower() for c in yearly['methodology']['caveats'])


def test_coverage_counts_rows_and_gaps_by_tier(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    base = 1_000_000
    with _writable(path) as conn:
        for ts in (base, base + 60, base + 60 + GAP_THRESHOLD_SECONDS + 900):
            _insert_raw(conn, ts, 10, 'LAN', ts, ts)
        for i in range(3):
            _insert_rollup(conn, 'hourly_rollup', 3_600_000 + i * 3600, 10, 1.0, 1.0, 2, 2, 60)
    periods = read_vlan_traffic_periods(path)
    assert periods['raw'] == {
        'earliest': base,
        'latest': base + 60 + GAP_THRESHOLD_SECONDS + 900,
        'count': 3,
        'gaps_over_5min': 1,
    }
    assert (periods['hourly']['count'], periods['hourly']['gaps_over_5min']) == (3, 0)
    assert periods['daily'] == {'earliest': None, 'latest': None, 'count': 0, 'gaps_over_5min': 0}


# --- run_rollups: correct under any cadence (July's sweep tests) ---------------------------

START_HOUR = 1_700_000_000 // 3600 * 3600


def _seed_hours(path: Path, hours: int, interval: int = 60, bps: int = 1_000_000) -> int:
    """Insert ``hours`` hours of samples ``interval`` s apart, growing at a constant rate."""
    step = bps * interval // 8
    with _writable(path) as conn:
        ts, counter, end = START_HOUR, 10_000, START_HOUR + hours * 3600
        while ts < end:
            _insert_raw(conn, ts, 20, 'IoT', counter, counter * 2)
            ts, counter = ts + interval, counter + step
    return end


def _hourly(path: Path) -> list[tuple[int, int, float]]:
    with sqlite3.connect(path) as conn:
        return list(
            conn.execute(
                'SELECT hour_utc, sample_count, avg_rx_bps FROM hourly_rollup ORDER BY hour_utc'
            )
        )


def _freeze(monkeypatch: pytest.MonkeyPatch, now: int) -> None:
    monkeypatch.setattr(store.time, 'time', lambda: float(now))


def test_rollups_on_an_empty_store_are_all_zero(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    assert run_rollups(path) == {
        'raw_rows_rolled': 0,
        'hourly_rows_written': 0,
        'hourly_rows_rolled': 0,
        'daily_rows_written': 0,
    }


def test_one_run_over_the_whole_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / 'store.sqlite3'
    end = _seed_hours(path, hours=4)
    _freeze(monkeypatch, end + RAW_RETENTION_SECONDS + 7200)
    run_rollups(path)
    rows = _hourly(path)
    assert [r[0] for r in rows] == [START_HOUR + i * 3600 for i in range(4)]
    assert [r[1] for r in rows] == [59, 60, 60, 60]  # the first hour has no earlier sample


def test_the_cutoff_sweeping_hour_by_hour_loses_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / 'store.sqlite3'
    _seed_hours(path, hours=4)
    for i in range(1, 5):
        _freeze(monkeypatch, START_HOUR + RAW_RETENTION_SECONDS + i * 3600)
        run_rollups(path)
    assert [r[1] for r in _hourly(path)] == [59, 60, 60, 60]


def test_a_five_minute_cadence_equals_one_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    one, many = tmp_path / 'one.sqlite3', tmp_path / 'many.sqlite3'
    assert _seed_hours(one, hours=3) == _seed_hours(many, hours=3)
    final = START_HOUR + RAW_RETENTION_SECONDS + 4 * 3600
    _freeze(monkeypatch, final)
    run_rollups(one)
    for now in range(START_HOUR + RAW_RETENTION_SECONDS, final + 1, 300):
        _freeze(monkeypatch, now)
        run_rollups(many)
    assert _hourly(one) == _hourly(many)
    assert [r[1] for r in _hourly(many)] == [59, 60, 60]


def test_a_second_run_at_the_same_instant_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / 'store.sqlite3'
    end = _seed_hours(path, hours=2)
    _freeze(monkeypatch, end + RAW_RETENTION_SECONDS + 7200)
    first = run_rollups(path)
    snapshot = _hourly(path)
    second = run_rollups(path)
    assert _hourly(path) == snapshot and first['hourly_rows_written'] == 2
    assert (second['raw_rows_rolled'], second['hourly_rows_written']) == (0, 0)


def test_an_unwritable_store_is_one_error(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    _writable(path).close()
    path.chmod(0o444)
    try:
        with pytest.raises(ToolError) as caught:
            run_rollups(path)
    finally:
        path.chmod(0o600)
    assert caught.value.error_code == ErrorCodes.API_ERROR
    assert 'writable' in (caught.value.suggestion or '')


# --- the MCP tools -------------------------------------------------------------------------


def test_the_handlers_are_coroutine_functions() -> None:
    for handler in (get_vlan_traffic_report, list_vlan_traffic_periods, get_wan_speedtest_history):
        assert inspect.iscoroutinefunction(handler)


async def test_the_tools_read_the_default_store_in_a_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    with pytest.raises(ToolError) as caught:
        await list_vlan_traffic_periods()
    assert caught.value.error_code == ErrorCodes.NO_DATA
    _writable(default_db_path()).close()
    threads: list[str] = []
    real = store.read_vlan_traffic_report

    def _spy(period: str, path: Path | None = None) -> dict[str, Any]:
        import threading

        threads.append(threading.current_thread().name)
        return real(period, path)

    monkeypatch.setattr(store, 'read_vlan_traffic_report', _spy)
    report = await get_vlan_traffic_report('1d')
    assert report['methodology']['tier_used'] == 'raw'
    assert threads and threads[0] != 'MainThread'
    assert (await list_vlan_traffic_periods())['raw']['count'] == 0


def test_the_store_imports_no_controller_client() -> None:
    source = Path(store.__file__).read_text(encoding='utf-8')
    for name in ('UniFiClient', 'UnifiApiClient', 'get_credentials', 'httpx', 'asyncssh'):
        assert name not in source
    assert os.path.basename(store.__file__) == 'vlan_traffic_store.py'
