"""The per-VLAN traffic store (``analysis/vlan_traffic_store.py``) and its two MCP tools.

Ported from the prototype (a local archive, not in the repo) and adapted: documentation values
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


# --- compute_rates, rollups, floors (the prototype's, unchanged in logic) --------------------------


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


# --- the report and the coverage (the prototype's logic) --------------------------------------------


@pytest.mark.parametrize(
    ('period', 'tier'),
    [('now', 'raw'), ('1d', 'raw'), ('1w', 'raw'), ('1m', 'hourly'), ('1y', 'daily')],
)
def test_each_period_reads_its_tier(tmp_path: Path, period: str, tier: str) -> None:
    """1w reads raw samples, which are kept 8 days."""
    path = tmp_path / 'store.sqlite3'
    _writable(path).close()
    report = read_vlan_traffic_report(period, path)
    assert (report['period'], report['methodology']['tier_used'], report['vlans']) == (
        period,
        tier,
        [],
    )
    caption = ' '.join(report['methodology']['caveats']).lower()
    assert {'raw': 'raw samples', 'hourly': 'hourly-rollup', 'daily': 'daily-rollup'}[
        tier
    ] in caption  # each caption names its tier


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
    assert (vlan['samples'], vlan['valid_sample_pct']) == (2, 50.0)
    assert 'coverage_pct' not in vlan  # a share of samples, not of time


def test_a_raw_window_pairs_its_first_sample_with_the_one_before(tmp_path: Path) -> None:
    """Review finding: each VLAN started the window with no previous counter, so the
    first interval was lost, and at a 5-minute cadence 'now' read one sample and no rate."""
    path = tmp_path / 'store.sqlite3'
    last = FAR_FUTURE - 100
    with _writable(path) as conn:  # every 5 minutes, 1 Mbit/s: 37.5 MB per interval
        for i, ts in enumerate(range(last - 3600, last + 1, 300)):
            _insert_raw(conn, ts, 10, 'LAN', i * 37_500_000, 0)
    now = last + 100  # a report 100 s after the last sample: 'now' holds just that one
    (latest,) = read_vlan_traffic_report('now', path, now=now)['vlans']
    assert (latest['samples'], latest['valid_sample_pct']) == (1, 100.0)
    assert latest['avg_rx_bps'] == latest['peak_rx_bps'] == 1_000_000.0
    (day,) = read_vlan_traffic_report('1d', path, now=now)['vlans']
    assert (day['samples'], day['valid_sample_pct']) == (13, 92.3)  # the oldest: none before
    with _writable(path) as conn:  # one more VLAN with a single sample ever: nothing measured
        _insert_raw(conn, last, 20, 'IoT', 5_000, 0)
    second = read_vlan_traffic_report('now', path, now=now)['vlans'][1]
    assert (second['vlan_id'], second['samples'], second['valid_sample_pct']) == (20, 1, 0.0)
    caption = read_vlan_traffic_report('now', path, now=now)['methodology']['caveats']
    assert any('0% valid samples' in line for line in caption)
    assert not any('coverage' in line for line in caption)


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
    (hourly,) = read_vlan_traffic_report('1m', path)['vlans']
    assert (hourly['avg_rx_bps'], hourly['peak_rx_bps'], hourly['samples']) == (200.0, 600.0, 2)
    yearly = read_vlan_traffic_report('1y', path)
    assert yearly['vlans'][0]['peak_rx_bps'] == 500.0
    caveats = yearly['methodology']['caveats']
    assert any('largest hourly peak' in c and 'largest sample rate' in c for c in caveats)
    assert any('shorter than the sampling interval' in c for c in caveats)


def test_no_tier_claims_to_smooth_peaks() -> None:
    """Issue 076 item 3: an hourly peak is the largest sample rate in the hour and a daily
    peak the largest hourly peak, so no tier smooths a peak beyond the sampling interval;
    the daily caveat, the tool's docstring and its manifest said otherwise."""
    for tier, methodology in store._TIER_METHODOLOGY.items():
        for caveat in methodology['caveats']:
            assert 'smooth' not in caveat.lower(), (tier, caveat)
    assert 'smooth' not in (get_vlan_traffic_report.__doc__ or '').lower()
    from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir

    registry = ToolRegistry(default_manifests_dir(), strict=True)
    description = registry.get_metadata('get_vlan_traffic_report').description or ''
    assert 'smooth' not in description.lower()
    assert 'largest sample rate' in description


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


# --- run_rollups: every complete bucket, recomputed, pruned only once rolled ---------------
# The prototype's rollup rolled an hour only once it was 8 days old and a
# day once about 61 days old, so 1w read nothing and 1m and 1y missed the newest 8 and 61
# days. Every run below passes ``now``, so nothing depends on the clock.

START_HOUR = 1_700_000_000 // 3600 * 3600
GRACE = store.MIN_GRACE_SECONDS  # twice a 60 s interval is below the 300 s floor


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


def _tables(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table, for comparing two runs."""
    with sqlite3.connect(path) as conn:
        return {
            table: sorted(conn.execute(f'SELECT * FROM {table}'))  # fixed table names
            for table in ('raw_samples', 'hourly_rollup', 'daily_rollup', 'rollup_state')
        }


def _marks(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as conn:
        return dict(conn.execute('SELECT tier, last_rolled_bucket FROM rollup_state'))


def test_rollups_on_an_empty_store_are_all_zero(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    assert run_rollups(path, now=START_HOUR) == {
        'raw_rows_rolled': 0,
        'hourly_rows_written': 0,
        'hourly_rows_rolled': 0,
        'daily_rows_written': 0,
        'raw_rows_pruned': 0,
        'hourly_rows_pruned': 0,
    }


@pytest.mark.parametrize(
    ('stamps', 'grace'),
    [([], 300), ([0], 300), ([0, 60, 120, 180], 300), ([0, 600, 1200, 1900], 1200)],
    ids=['no samples', 'one sample', 'every minute', 'every ten minutes'],
)
def test_the_grace_is_twice_the_sampling_interval_and_at_least_5_minutes(
    stamps: list[int], grace: int
) -> None:
    assert store.sampling_grace(stamps) == grace


def test_one_run_rolls_every_complete_hour(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    end = _seed_hours(path, hours=4)
    run_rollups(path, now=end + GRACE)
    rows = _hourly(path)
    assert [r[0] for r in rows] == [START_HOUR + i * 3600 for i in range(4)]
    assert [r[1] for r in rows] == [59, 60, 60, 60]  # the first hour has no earlier sample
    assert _marks(path)['hourly'] == end - 3600


@pytest.mark.parametrize(('interval', 'grace'), [(60, 300), (600, 1200)])
def test_an_hour_waits_for_its_grace_then_rolls(tmp_path: Path, interval: int, grace: int) -> None:
    path = tmp_path / 'store.sqlite3'
    end = _seed_hours(path, hours=3, interval=interval)
    run_rollups(path, now=end + grace - 1)
    assert [r[0] for r in _hourly(path)] == [START_HOUR, START_HOUR + 3600]
    run_rollups(path, now=end + grace)
    assert [r[0] for r in _hourly(path)] == [START_HOUR + i * 3600 for i in range(3)]


def test_the_cutoff_sweeping_hour_by_hour_loses_nothing(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    _seed_hours(path, hours=4)
    for i in range(1, 5):
        run_rollups(path, now=START_HOUR + i * 3600 + GRACE)
    assert [r[1] for r in _hourly(path)] == [59, 60, 60, 60]


def test_a_five_minute_cadence_equals_one_run(tmp_path: Path) -> None:
    one, many = tmp_path / 'one.sqlite3', tmp_path / 'many.sqlite3'
    assert _seed_hours(one, hours=3) == _seed_hours(many, hours=3)
    final = START_HOUR + 4 * 3600
    run_rollups(one, now=final)
    for now in range(START_HOUR, final + 1, 300):
        run_rollups(many, now=now)
    assert _tables(one) == _tables(many)
    assert [r[1] for r in _hourly(many)] == [59, 60, 60]


def test_two_runs_give_identical_rows(tmp_path: Path) -> None:
    """Recompute, never accumulate: the second run rewrites its window to the same rows."""
    path = tmp_path / 'store.sqlite3'
    end = _seed_hours(path, hours=30)
    first = run_rollups(path, now=end + GRACE)
    snapshot = _tables(path)
    second = run_rollups(path, now=end + GRACE)
    assert _tables(path) == snapshot
    assert first['hourly_rows_written'] == 30 and first['daily_rows_written'] >= 1
    assert second['hourly_rows_written'] == store.TRAILING_HOURS  # recomputed, not added


def test_a_late_sample_is_counted_on_the_next_run(tmp_path: Path) -> None:
    """A sample written after its hour was rolled changes that hour, and its day, next run."""
    path = tmp_path / 'store.sqlite3'
    day = floor_to_day(START_HOUR) + 86400
    with _writable(path) as conn:  # two days of samples a minute apart, 1 Mbit/s
        for i, ts in enumerate(range(day - 86400, day + 86400, 60)):
            _insert_raw(conn, ts, 20, 'IoT', i * 7_500_000, 0)
    now = day + 86400 + GRACE  # the day [day, day + 1 d) and its last hour are complete
    run_rollups(path, now=now)
    last_hour = day + 86400 - 3600
    with sqlite3.connect(path) as conn:
        before = conn.execute(
            'SELECT sample_count, peak_rx_bps FROM hourly_rollup WHERE hour_utc = ?', (last_hour,)
        ).fetchone()
        day_peak = conn.execute(
            'SELECT peak_rx_bps FROM daily_rollup WHERE day_utc = ?', (day,)
        ).fetchone()[0]
    assert before == (60, 1_000_000.0) and day_peak == 1_000_000.0
    i = (last_hour + 600 - (day - 86400)) // 60  # the sample at last_hour + 600
    with _writable(path) as conn:  # late: 30 s after it, 90% of the next minute's bytes
        _insert_raw(conn, last_hour + 630, 20, 'IoT', i * 7_500_000 + 6_750_000, 0)
    run_rollups(path, now=now)
    with sqlite3.connect(path) as conn:
        after = conn.execute(
            'SELECT sample_count, peak_rx_bps FROM hourly_rollup WHERE hour_utc = ?', (last_hour,)
        ).fetchone()
        day_after = conn.execute(
            'SELECT peak_rx_bps FROM daily_rollup WHERE day_utc = ?', (day,)
        ).fetchone()[0]
    assert after == (61, 1_800_000.0)  # the split interval: 1.8 and 0.2 Mbit/s
    assert day_after == 1_800_000.0


@pytest.mark.parametrize(
    ('delay', 'counted'),
    [(store.TRAILING_HOURS * 3600 - 1, True), (store.TRAILING_HOURS * 3600, False)],
    ids=['inside the trailing window', 'past it'],
)
def test_a_late_sample_counts_only_inside_the_trailing_window(
    tmp_path: Path, delay: int, counted: bool
) -> None:
    """A row written straight into ``raw_samples`` (not through ``insert_samples``, so no
    dirty bucket) is caught only by the trailing window: a run recomputes the newest
    TRAILING_HOURS complete hours whatever the dirty table says. Past that window such a row
    stays in the raw tier (now, 1d, 1w) only. The sampler's own writes go through
    ``insert_samples`` and are always counted (issue 071, the tests below)."""
    path = tmp_path / 'store.sqlite3'
    end = _seed_hours(path, hours=3)
    newest = end - 3600
    completed = end + GRACE  # the newest hour, [end - 1 h, end), is complete and rolled here
    run_rollups(path, now=completed)
    before = {hour: count for hour, count, _ in _hourly(path)}
    late = newest + 630  # between the samples at +600 and +660, half a minute's bytes on
    counter = 10_000 + (late - START_HOUR) // 60 * 7_500_000 + 3_750_000  # as _seed_hours
    with _writable(path) as conn:
        _insert_raw(conn, late, 20, 'IoT', counter, counter * 2)
    run_rollups(path, now=completed + delay)
    after = {hour: count for hour, count, _ in _hourly(path)}
    assert after[newest] == before[newest] + (1 if counted else 0)  # one interval split
    assert {h: c for h, c in after.items() if h != newest} == {
        h: c for h, c in before.items() if h != newest
    }
    with sqlite3.connect(path) as conn:
        kept = conn.execute('SELECT COUNT(*) FROM raw_samples WHERE ts_utc = ?', (late,))
        assert kept.fetchone()[0] == 1


# --- issue 071: the rollups follow the data (dirty buckets), not the clock ----------------


def _dirty(path: Path) -> list[tuple[str, int]]:
    with sqlite3.connect(path) as conn:
        return list(conn.execute('SELECT tier, bucket FROM dirty_buckets ORDER BY tier, bucket'))


def _minute_rows(start: int, end: int, *, step: int = 7_500_000) -> list[dict[str, Any]]:
    """Samples a minute apart from ``start`` to ``end`` at 1 Mbit/s, as the sampler writes them."""
    return [
        {
            'ts_utc': ts,
            'vlan_id': 20,
            'network_name': 'IoT',
            'iface': 'br20',
            'rx_bytes': i * step,
            'tx_bytes': 0,
        }
        for i, ts in enumerate(range(start, end, 60))
    ]


def test_insert_samples_records_each_hour_it_writes_into_as_dirty(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    hour = START_HOUR + 5 * 3600
    store.insert_samples(
        path,
        [
            {**_minute_rows(hour + 60, hour + 120)[0], 'vlan_id': 20},
            {**_minute_rows(hour + 60, hour + 120)[0], 'vlan_id': 30, 'network_name': 'Lab'},
            {**_minute_rows(hour + 3660, hour + 3720)[0], 'vlan_id': 20},
        ],
    )
    assert _dirty(path) == [('hourly', hour), ('hourly', hour + 3600)]


def test_a_sample_written_a_day_late_reaches_the_hourly_and_daily_rows(tmp_path: Path) -> None:
    """A sample stamped in an hour rolled a day earlier (past the trailing window) changes
    that hour's row and its day's row on the next run; two runs still give identical rows."""
    path = tmp_path / 'store.sqlite3'
    day = floor_to_day(START_HOUR) + 86400
    store.insert_samples(path, _minute_rows(day - 86400, day + 86400))  # two days, 1 Mbit/s
    rolled_at = day + 86400 + GRACE  # the day [day, day + 1 d) is complete
    run_rollups(path, now=rolled_at)
    assert _dirty(path) == []  # every dirty bucket rolled was cleared
    target = day + 3 * 3600  # 03:00 of the rolled day: complete since long before the run
    with sqlite3.connect(path) as conn:
        before = conn.execute(
            'SELECT sample_count, peak_rx_bps FROM hourly_rollup WHERE hour_utc = ?', (target,)
        ).fetchone()
        day_before = conn.execute(
            'SELECT peak_rx_bps, sample_count FROM daily_rollup WHERE day_utc = ?', (day,)
        ).fetchone()
    assert before == (60, 1_000_000.0) and day_before == (1_000_000.0, 24)
    # A day later a stalled sampler writes a sample it read at 03:10:30: 90% of the next
    # minute's bytes in 30 s, so the split interval is 1.8 and 0.2 Mbit/s.
    i = (target + 600 - (day - 86400)) // 60
    late = {**_minute_rows(target + 630, target + 690)[0], 'rx_bytes': i * 7_500_000 + 6_750_000}
    store.insert_samples(path, [late])
    assert _dirty(path) == [('hourly', target)]
    a_day_later = rolled_at + 86400
    result = run_rollups(path, now=a_day_later)
    with sqlite3.connect(path) as conn:
        after = conn.execute(
            'SELECT sample_count, peak_rx_bps FROM hourly_rollup WHERE hour_utc = ?', (target,)
        ).fetchone()
        day_after = conn.execute(
            'SELECT peak_rx_bps, sample_count FROM daily_rollup WHERE day_utc = ?', (day,)
        ).fetchone()
    assert after == (61, 1_800_000.0)
    assert day_after == (1_800_000.0, 24)
    assert result['hourly_rows_written'] >= 1 and result['daily_rows_written'] >= 1
    assert _dirty(path) == []
    snapshot = _tables(path)
    run_rollups(path, now=a_day_later)
    assert _tables(path) == snapshot


def test_a_late_sample_into_a_pruned_hour_is_dropped_not_rolled_from_part_of_its_data(
    tmp_path: Path,
) -> None:
    """Raw samples are pruned on hour boundaries, so an hour is either whole or gone; a
    sample written into a pruned hour is pruned with it and never rewrites that hour's row."""
    path = tmp_path / 'store.sqlite3'
    end = _seed_hours(path, hours=9 * 24)  # 9 days, a sample a minute
    now = end + GRACE
    run_rollups(path, now=now)
    cutoff = floor_to_hour(now - RAW_RETENTION_SECONDS)
    pruned_hour = cutoff - 3600  # holds only the carry sample now
    with sqlite3.connect(path) as conn:
        row = 'SELECT sample_count, avg_rx_bps FROM hourly_rollup WHERE hour_utc = ?'
        before = conn.execute(row, (pruned_hour,)).fetchone()
        kept = conn.execute(
            'SELECT COUNT(*) FROM raw_samples WHERE ts_utc >= ? AND ts_utc < ?',
            (pruned_hour, cutoff),
        ).fetchone()[0]
    assert before == (60, 1_000_000.0) and kept == 1
    late_ts = pruned_hour + 630
    counter = 10_000 + (late_ts - START_HOUR) // 60 * 7_500_000 + 3_750_000  # as _seed_hours
    store.insert_samples(
        path,
        [
            {
                'ts_utc': late_ts,
                'vlan_id': 20,
                'network_name': 'IoT',
                'iface': 'br20',
                'rx_bytes': counter,
                'tx_bytes': counter * 2,
            }
        ],
    )
    run_rollups(path, now=now)
    with sqlite3.connect(path) as conn:
        assert conn.execute(row, (pruned_hour,)).fetchone() == before
        gone = conn.execute('SELECT COUNT(*) FROM raw_samples WHERE ts_utc = ?', (late_ts,))
        assert gone.fetchone()[0] == 0
    assert _dirty(path) == []


def test_pruning_keeps_whole_buckets_only(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    now = START_HOUR + 70 * 86400 + 1234  # not on an hour or a day boundary
    with _writable(path) as conn:  # 70 days, one sample an hour
        for i, ts in enumerate(range(START_HOUR, now + 1, 3600)):
            _insert_raw(conn, ts, 20, 'IoT', i * 450_000_000, 0)
    run_rollups(path, now=now)
    with sqlite3.connect(path) as conn:
        raw = [r[0] for r in conn.execute('SELECT ts_utc FROM raw_samples ORDER BY ts_utc')]
        hours = [r[0] for r in conn.execute('SELECT hour_utc FROM hourly_rollup')]
    raw_cutoff = floor_to_hour(now - RAW_RETENTION_SECONDS)
    assert [ts for ts in raw if ts < raw_cutoff] == [raw_cutoff - 3600]  # the carry only
    assert min(hours) == floor_to_day(now - store.HOURLY_RETENTION_SECONDS)


# --- issue 072: an interval across a sampler outage is a gap, not a measurement -----------


def test_an_interval_longer_than_the_bound_has_no_rate() -> None:
    prev = {'ts_utc': 1000, 'rx_bytes': 1000, 'tx_bytes': 500}
    at_the_bound = {'ts_utc': 1600, 'rx_bytes': 2000, 'tx_bytes': 1000}
    past_it = {**at_the_bound, 'ts_utc': 1601}
    assert compute_rates(prev, at_the_bound, max_interval=600) is not None
    assert compute_rates(prev, past_it, max_interval=600) is None
    assert compute_rates(prev, past_it) is not None  # no bound: the prototype's behaviour


def _minute_run(start: int, minutes: int, counter: int, *, step: int = 7_500_000) -> list[Any]:
    """``minutes`` samples a minute apart from ``start`` at 1 Mbit/s, from ``counter``."""
    return [(start + i * 60, counter + i * step) for i in range(minutes)]


def test_the_raw_reader_treats_an_outage_as_a_gap_before_and_inside_a_window(
    tmp_path: Path,
) -> None:
    """Ten minutes of samples, a six-hour outage, ten more; then a three-day outage and one
    sample at ``now``. The two intervals across the outages give no rate but their samples
    count, so ``valid_sample_pct`` drops; the normal cadence beside them is unchanged."""
    path = tmp_path / 'store.sqlite3'
    now = FAR_FUTURE - 100
    first = _minute_run(now - 3 * 86400 - 6 * 3600 - 20 * 60, 10, 10_000)
    # Across the six-hour outage the counter grows as if at 5 Mbit/s, which must not show.
    second_start = first[-1][1] + 5 * 7_500_000 * 6 * 60
    second = _minute_run(first[-1][0] + 6 * 3600 + 60, 10, second_start)
    with _writable(path) as conn:
        for ts, counter in first + second:
            _insert_raw(conn, ts, 20, 'IoT', counter, 0)
        # One sample three days later: its only pairing is across the outage.
        _insert_raw(conn, now, 20, 'IoT', second[-1][1] + 10 * 7_500_000 * 3 * 1440, 0)
    (latest,) = read_vlan_traffic_report('now', path, now=now)['vlans']
    assert (latest['samples'], latest['valid_sample_pct']) == (1, 0.0)
    assert (latest['avg_rx_bps'], latest['peak_rx_bps']) == (0.0, 0.0)
    (week,) = read_vlan_traffic_report('1w', path, now=now)['vlans']
    # 21 samples: the first has none before it, two intervals span an outage, 18 are valid.
    assert week['samples'] == 21
    assert week['valid_sample_pct'] == round(100 * 18 / 21, 1)
    assert week['avg_rx_bps'] == week['peak_rx_bps'] == 1_000_000.0
    caption = read_vlan_traffic_report('1w', path, now=now)['methodology']['caveats']
    assert any('outage' in line for line in caption)


def test_the_hourly_carry_across_an_outage_is_a_gap(tmp_path: Path) -> None:
    """The first hour rolled after a three-day outage must not start from the sample before
    the outage: that interval is a gap, so the hour holds 59 intervals, not 60, and its peak
    is the cadence's rate, not the outage's average."""
    path = tmp_path / 'store.sqlite3'
    before = _minute_run(START_HOUR, 60, 10_000)
    resume = START_HOUR + 3 * 86400
    after_start = before[-1][1] + 5 * 7_500_000 * 3 * 1440  # 5 Mbit/s across the outage
    after = _minute_run(resume, 60, after_start)
    with _writable(path) as conn:
        for ts, counter in before + after:
            _insert_raw(conn, ts, 20, 'IoT', counter, 0)
    run_rollups(path, now=resume + 3600 + GRACE)
    rows = {hour: (count, avg) for hour, count, avg in _hourly(path)}
    assert rows[START_HOUR] == (59, 1_000_000.0)
    assert rows[resume] == (59, 1_000_000.0)
    with sqlite3.connect(path) as conn:
        peak = conn.execute(
            'SELECT peak_rx_bps FROM hourly_rollup WHERE hour_utc = ?', (resume,)
        ).fetchone()[0]
    assert peak == 1_000_000.0
    assert set(rows) == {START_HOUR, resume}  # the empty hours of the outage have no row


def test_raw_keeps_8_days_and_hourly_60_once_rolled(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    now = START_HOUR + 70 * 86400
    with _writable(path) as conn:  # 70 days, one sample an hour
        for i, ts in enumerate(range(START_HOUR, now + 1, 3600)):
            _insert_raw(conn, ts, 20, 'IoT', i * 450_000_000, 0)
    result = run_rollups(path, now=now)
    with sqlite3.connect(path) as conn:
        raw = [r[0] for r in conn.execute('SELECT ts_utc FROM raw_samples ORDER BY ts_utc')]
        hours = [r[0] for r in conn.execute('SELECT hour_utc FROM hourly_rollup')]
        days = [r[0] for r in conn.execute('SELECT day_utc FROM daily_rollup ORDER BY day_utc')]
    cutoff = now - RAW_RETENTION_SECONDS  # on an hour boundary: START_HOUR is, and so is now
    assert [ts for ts in raw if ts < cutoff] == [cutoff - 3600]  # the one kept to pair from
    assert min(ts for ts in raw if ts >= cutoff) == cutoff
    # Hourly rows are pruned on day boundaries (issue 071), so the day holding the 60-day
    # cutoff is kept whole.
    assert min(hours) == floor_to_day(now - store.HOURLY_RETENTION_SECONDS)
    assert days[0] == floor_to_day(START_HOUR) and days[-1] == floor_to_day(now) - 86400
    assert result['raw_rows_pruned'] > 0 and result['hourly_rows_pruned'] > 0


def test_a_row_is_never_pruned_before_its_bucket_is_rolled(tmp_path: Path) -> None:
    """Samples five days apart make the grace ten days, so a sample 9 days old, past raw's
    8-day retention, is in an hour that is not complete yet: it must stay in raw."""
    path = tmp_path / 'store.sqlite3'
    with _writable(path) as conn:
        for i in range(9):
            _insert_raw(conn, START_HOUR + i * 5 * 86400, 20, 'IoT', i * 1000, 0)
    now = START_HOUR + 8 * 5 * 86400 + 4 * 86400  # the last two samples are 9 and 4 days old
    run_rollups(path, now=now)
    mark = _marks(path)['hourly']
    assert mark == floor_to_hour(now - 10 * 86400) - 3600
    with sqlite3.connect(path) as conn:
        kept = [r[0] for r in conn.execute('SELECT ts_utc FROM raw_samples ORDER BY ts_utc')]
    nine_days_old = START_HOUR + 7 * 5 * 86400
    assert nine_days_old < now - RAW_RETENTION_SECONDS and nine_days_old in kept
    assert kept == [START_HOUR + 6 * 5 * 86400, nine_days_old, START_HOUR + 8 * 5 * 86400]


# --- end to end: sample, rollup, report, at a fixed now -----------------------------------


DAY = floor_to_day(1_790_000_000)
NOW = DAY + 12 * 3600 + 600  # 12:10 UTC: with 5-minute samples the grace is 10 minutes
BASE = 375_000  # bytes per 5-minute interval: 10 kbit/s


def _fill(path: Path, bursts: dict[int, int]) -> None:
    """70 days of 5-minute samples up to NOW through insert_samples (the sampler's write);
    ``bursts`` maps an interval's end time to a multiple of the base rate."""
    rows, counter = [], 0
    for ts in range(NOW - 70 * 86400, NOW + 1, 300):
        counter += BASE * bursts.get(ts, 1)
        rows.append(
            {
                'ts_utc': ts,
                'vlan_id': 30,
                'network_name': 'IoT',
                'iface': 'br7',
                'rx_bytes': counter,
                'tx_bytes': counter // 2,
            }
        )
    store.insert_samples(path, rows)


def test_each_period_includes_its_newest_complete_bucket(tmp_path: Path) -> None:
    """1d and 1w (raw) reach NOW; 1m (hourly) the newest complete hour; 1y (daily) the
    newest complete day; a bucket that is still open never shows in a rollup tier."""
    path = tmp_path / 'store.sqlite3'
    newest_hour = DAY + 11 * 3600  # 11:00-12:00, complete since 12:10
    newest_day = DAY - 86400  # yesterday; today is open
    _fill(path, {NOW: 9, newest_hour + 1500: 5, newest_day + 10 * 3600: 3})
    run_rollups(path, now=NOW)
    peaks = {
        period: read_vlan_traffic_report(period, path, now=NOW)['vlans'][0]['peak_rx_bps']
        for period in ('1d', '1w', '1m', '1y')
    }
    assert peaks == {'1d': 90_000.0, '1w': 90_000.0, '1m': 50_000.0, '1y': 30_000.0}
    coverage = read_vlan_traffic_periods(path)
    assert coverage['hourly']['latest'] == newest_hour
    assert coverage['daily']['latest'] == newest_day
    assert coverage['daily']['earliest'] == floor_to_day(NOW - 70 * 86400)  # past 60 days
    assert coverage['raw']['latest'] == NOW
    year = read_vlan_traffic_report('1y', path, now=NOW)
    assert year['methodology']['tier_used'] == 'daily' and year['vlans'][0]['samples'] == 70


def _as_the_old_code_left_it(path: Path, old_now: int) -> None:
    """A store as the prototype's rollup left it at ``old_now``: an hour rolled only once 8 days old,
    a day once about 61 days old, and each tier pruned as soon as it was rolled."""
    old_hour = floor_to_hour(old_now - RAW_RETENTION_SECONDS - 3600)
    old_day = floor_to_day(old_now - store.HOURLY_RETENTION_SECONDS - 86400)
    conn = open_store(path, writable=True)
    conn.row_factory = sqlite3.Row
    with conn:
        earliest = conn.execute('SELECT MIN(ts_utc) FROM raw_samples').fetchone()[0]
        store._roll_hours(conn, floor_to_hour(earliest), old_hour)
        store._prune_raw(conn, old_hour + 3600)
        store._set_high_water_mark(conn, 'hourly', old_hour)
        first_hour = conn.execute('SELECT MIN(hour_utc) FROM hourly_rollup').fetchone()[0]
        store._roll_days(conn, floor_to_day(first_hour), old_day)
        store._prune_hourly(conn, old_day + 86400)
        store._set_high_water_mark(conn, 'daily', old_day)
    conn.close()


def test_an_old_code_store_upgrades_in_place(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    _fill(path, {})
    old_now = NOW - 5 * 3600
    _as_the_old_code_left_it(path, old_now)
    old_hour = _marks(path)['hourly']
    with sqlite3.connect(path) as conn:
        schema = list(conn.execute('SELECT sql FROM sqlite_master ORDER BY name'))
        assert conn.execute('SELECT MAX(hour_utc) FROM hourly_rollup').fetchone()[0] == old_hour
    assert read_vlan_traffic_report('1m', path, now=NOW)['vlans'][0]['samples'] > 0
    run_rollups(path, now=NOW)
    marks = _marks(path)
    assert marks == {'hourly': DAY + 11 * 3600, 'daily': DAY - 86400}
    with sqlite3.connect(path) as conn:
        assert list(conn.execute('SELECT sql FROM sqlite_master ORDER BY name')) == schema
        hours = {r[0] for r in conn.execute('SELECT hour_utc FROM hourly_rollup')}
        days = {r[0] for r in conn.execute('SELECT day_utc FROM daily_rollup')}
    first_kept = floor_to_hour(NOW - store.HOURLY_RETENTION_SECONDS) + 3600  # first at cutoff
    assert set(range(first_kept, marks['hourly'] + 1, 3600)) <= hours  # no hour skipped
    newer = set(range(old_hour + 3600, marks['hourly'] + 1, 3600))
    assert {h for h in hours if h > old_hour} == newer
    assert set(range(floor_to_day(NOW - 70 * 86400), marks['daily'] + 1, 86400)) == days
    for period in ('1w', '1m', '1y'):
        assert read_vlan_traffic_report(period, path, now=NOW)['vlans'], period


def test_an_unwritable_store_is_one_error(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    end = _seed_hours(path, hours=2)  # a complete hour to roll, so the run must write
    path.chmod(0o444)
    try:
        with pytest.raises(ToolError) as caught:
            run_rollups(path, now=end + GRACE)
    finally:
        path.chmod(0o600)
    assert caught.value.error_code == ErrorCodes.API_ERROR
    assert 'writable' in (caught.value.suggestion or '')


# --- the MCP tools -------------------------------------------------------------------------


def test_the_handlers_are_coroutine_functions() -> None:
    # The WAN history tool's check lives in tests/diagnostics/test_wan_history.py (issue 076
    # item 15).
    for handler in (get_vlan_traffic_report, list_vlan_traffic_periods):
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
