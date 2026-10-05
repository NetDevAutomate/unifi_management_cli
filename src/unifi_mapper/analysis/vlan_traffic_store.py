"""The per-VLAN traffic store: SQLite under the XDG state directory, rollups and reports.

The store is written only by ``unifi-mapper vlan-traffic sample`` (one SSH read of the
gateway's bridge byte counters, ``analysis/vlan_traffic.py``) and ``vlan-traffic rollup``.
Reading it contacts nothing, so the two MCP tools here, ``get_vlan_traffic_report`` and
``list_vlan_traffic_periods``, need no credentials (``credentials: none``, ``open_world:
false``): this module imports no client. They read the default store only, in a worker
thread, so a read waiting on the busy timeout never stalls the event loop.

The store is ``state_dir() / 'vlan-traffic.sqlite3'`` (``$XDG_STATE_HOME/unifi_mapper/``,
never a path relative to the working directory); the CLI's ``--db`` names another. A read
opens it ``mode=ro`` through a file URI built with ``Path.resolve().as_uri()`` (so a ``?``,
``#`` or ``%`` in the path can't break it) and never creates the file or its schema. SQLite's
errors are mapped by name (:func:`_store_error`): a missing store is ``NO_DATA`` (run
``vlan-traffic sample``), a hot journal a crashed sampler left (``SQLITE_READONLY_ROLLBACK``,
which a read-only handle can't roll back) asks for ``vlan-traffic rollup`` (a writable open
rolls it back), a lock held past the 5 s busy timeout is "store busy", anything else "store
unreadable". The journal mode is SQLite's default (``DELETE``), so a read-only open needs no
``-shm`` file. A new store is ``0o600``, and a missing directory is created ``0o700`` (an
existing one keeps its mode).

Ported from the July work (a local archive, not in the repo): the schema, ``compute_rates``,
the rollups (a high-water mark per tier, complete buckets only, the per-VLAN boundary carry)
and the report and coverage queries are July's, unchanged in logic. Adapted: WAL dropped, the
``UNIFI_VLAN_TRAFFIC_DB`` override replaced by an explicit path, ``run_rollups`` made
synchronous (it never awaited), and the reads split from the MCP handlers.
"""

import asyncio
import os
import sqlite3
import time
from collections.abc import Iterable
from loguru import logger
from pathlib import Path
from pydantic import Field
from typing import Annotated, Any, Literal
from unifi_mapper.analysis.port_counter_baseline import state_dir
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


DB_FILENAME = 'vlan-traffic.sqlite3'
BUSY_TIMEOUT_SECONDS = 5.0
# Raw samples older than this are rolled into hourly_rollup and pruned.
RAW_RETENTION_SECONDS = 8 * 24 * 3600
# Hourly rollups older than this are rolled into daily_rollup and pruned.
HOURLY_RETENTION_SECONDS = 60 * 24 * 3600
# A gap between consecutive rows wider than the tier's spacing plus this is a coverage gap.
GAP_THRESHOLD_SECONDS = 300
# The spacing the coverage report expects between raw samples (sizes the gap check only).
DEFAULT_SAMPLE_INTERVAL_SECONDS = 60
SAMPLE_HINT = 'Run `unifi-mapper vlan-traffic sample` to take a sample'
RECOVERY_MESSAGE = 'store needs recovery: run unifi-mapper vlan-traffic rollup'

Period = Literal['now', '1d', '1w', '1m', '1y']
_PERIOD_TIERS = {'now': 'raw', '1d': 'raw', '1w': 'hourly', '1m': 'hourly', '1y': 'daily'}
_PERIOD_SECONDS = {
    'now': 300,
    '1d': 24 * 3600,
    '1w': 7 * 24 * 3600,
    '1m': 30 * 24 * 3600,
    '1y': 365 * 24 * 3600,
}
_TIER_METHODOLOGY: dict[str, dict[str, Any]] = {
    'raw': {
        'interval_s': None,
        'caveats': [
            'Raw sampling-interval data; averages and peaks are exact within the sampled window.'
        ],
    },
    'hourly': {
        'interval_s': 3600,
        'caveats': [
            'Hourly-rollup data: averages are the mean of per-sample rates within each hour, '
            'and peaks are the max sample rate seen in that hour; bursts shorter than the '
            'sampling interval may be under-represented.'
        ],
    },
    'daily': {
        'interval_s': 86400,
        'caveats': [
            'Daily-rollup data: a rollup of a rollup. A 1y peak is the max of hourly peaks, so '
            'it smooths out short bursts more than a raw or hourly view would.'
        ],
    },
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_samples (
    ts_utc INTEGER NOT NULL,
    vlan_id INTEGER NOT NULL,
    network_name TEXT NOT NULL,
    iface TEXT NOT NULL,
    rx_bytes INTEGER NOT NULL,
    tx_bytes INTEGER NOT NULL,
    PRIMARY KEY (ts_utc, vlan_id)
);

CREATE TABLE IF NOT EXISTS hourly_rollup (
    hour_utc INTEGER NOT NULL,
    vlan_id INTEGER NOT NULL,
    network_name TEXT NOT NULL,
    avg_rx_bps REAL NOT NULL,
    avg_tx_bps REAL NOT NULL,
    peak_rx_bps REAL NOT NULL,
    peak_tx_bps REAL NOT NULL,
    sample_count INTEGER NOT NULL,
    PRIMARY KEY (hour_utc, vlan_id)
);

CREATE TABLE IF NOT EXISTS daily_rollup (
    day_utc INTEGER NOT NULL,
    vlan_id INTEGER NOT NULL,
    network_name TEXT NOT NULL,
    avg_rx_bps REAL NOT NULL,
    avg_tx_bps REAL NOT NULL,
    peak_rx_bps REAL NOT NULL,
    peak_tx_bps REAL NOT NULL,
    sample_count INTEGER NOT NULL,
    PRIMARY KEY (day_utc, vlan_id)
);

CREATE TABLE IF NOT EXISTS rollup_state (
    tier TEXT PRIMARY KEY,
    last_rolled_bucket INTEGER NOT NULL
);
"""


def default_db_path() -> Path:
    """Return ``state_dir() / DB_FILENAME`` (read at call time; nothing is created)."""
    return state_dir() / DB_FILENAME


# --- opening the store ---------------------------------------------------------------------


def _store_error(error: sqlite3.Error, path: Path, *, writing: bool) -> ToolError:
    """Map an SQLite error to the tool error a caller shows, by SQLite's error name."""
    name = getattr(error, 'sqlite_errorname', None) or type(error).__name__
    logger.warning('VLAN traffic store {}: {}', path.name, name)
    if name == 'SQLITE_READONLY_ROLLBACK':
        return ToolError(message=RECOVERY_MESSAGE, error_code=ErrorCodes.API_ERROR)
    if name.startswith('SQLITE_BUSY'):
        return ToolError(
            message=f'store busy: locked for more than {BUSY_TIMEOUT_SECONDS:g} s',
            error_code=ErrorCodes.API_ERROR,
            suggestion='A sample or a rollup is running; try again in a moment',
        )
    if writing:
        return ToolError(
            message=f'cannot write the VLAN traffic store {path}: {name}',
            error_code=ErrorCodes.API_ERROR,
            suggestion='Check the store path is writable (--db names another)',
        )
    return ToolError(message=f'store unreadable: {name}', error_code=ErrorCodes.API_ERROR)


def _create_private(path: Path) -> None:
    """Create the directory (0o700) and an empty store file (0o600) when they are missing."""
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.exists():
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        pass  # another sampler created it first
    except OSError as e:
        reason = e.strerror or type(e).__name__
        raise ToolError(
            message=f'cannot write the VLAN traffic store {path}: {reason}',
            error_code=ErrorCodes.API_ERROR,
            suggestion='Check the store path is writable (--db names another)',
        ) from None


def open_store(path: Path, *, writable: bool) -> sqlite3.Connection:
    """Open the store: writable (creating it and its schema) or read-only (never creating).

    Args:
        path: The store's path.
        writable: Open for ``sample`` and ``rollup``; otherwise ``mode=ro`` through a file URI.

    Returns:
        An open connection with the busy timeout set.

    Raises:
        ToolError: ``NO_DATA`` for a missing store on a read, ``API_ERROR`` from
            :func:`_store_error`.
    """
    path = Path(path)
    if writable:
        _create_private(path)
        try:
            conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
            conn.executescript(_SCHEMA)
        except sqlite3.Error as e:
            raise _store_error(e, path, writing=True) from None
        return conn
    if not path.exists():
        raise ToolError(
            message=f'No VLAN traffic store at {path}',
            error_code=ErrorCodes.NO_DATA,
            suggestion=SAMPLE_HINT,
        )
    uri = path.resolve().as_uri() + '?mode=ro'
    try:
        return sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_SECONDS)
    except sqlite3.Error as e:
        raise _store_error(e, path, writing=False) from None


def insert_samples(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write one sample's rows (``ts_utc, vlan_id, network_name, iface, rx/tx_bytes``) at once."""
    conn = open_store(path, writable=True)
    try:
        with conn:
            conn.executemany(
                'INSERT OR REPLACE INTO raw_samples '
                '(ts_utc, vlan_id, network_name, iface, rx_bytes, tx_bytes) '
                'VALUES (:ts_utc, :vlan_id, :network_name, :iface, :rx_bytes, :tx_bytes)',
                rows,
            )
    except sqlite3.Error as e:
        raise _store_error(e, path, writing=True) from None
    finally:
        conn.close()


# --- pure functions: rates and rollups (July's) --------------------------------------------


def compute_rates(
    prev_sample: dict[str, Any] | None, cur_sample: dict[str, Any]
) -> dict[str, float] | None:
    """Return the interval's ``{rx_bps, tx_bps}``, reset-aware. Pure.

    Cumulative interface byte counters reset on an interface flap or a gateway reboot, so a
    negative delta on either counter means the interval has no honest rate (as
    ``core/utils/counters.retry_delta`` treats a reset).

    Args:
        prev_sample: The previous ``{ts_utc, rx_bytes, tx_bytes}``, or None for the first.
        cur_sample: The current one.

    Returns:
        The rates, or None with no previous sample, a non-positive interval or a reset.
    """
    if prev_sample is None:
        return None
    dt = cur_sample['ts_utc'] - prev_sample['ts_utc']
    if dt <= 0:
        return None
    d_rx = cur_sample['rx_bytes'] - prev_sample['rx_bytes']
    d_tx = cur_sample['tx_bytes'] - prev_sample['tx_bytes']
    if d_rx < 0 or d_tx < 0:
        return None
    return {'rx_bps': (d_rx * 8) / dt, 'tx_bps': (d_tx * 8) / dt}


def _rollup(rows: list[dict[str, Any]], bucket_key: str) -> list[dict[str, Any]]:
    """Average and peak rate rows per ``(bucket, vlan_id)``. Pure."""
    buckets: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        agg = buckets.setdefault(
            (row['bucket'], row['vlan_id']),
            {
                bucket_key: row['bucket'],
                'vlan_id': row['vlan_id'],
                'network_name': row['network_name'],
                '_rx_sum': 0.0,
                '_tx_sum': 0.0,
                'peak_rx_bps': 0.0,
                'peak_tx_bps': 0.0,
                'sample_count': 0,
            },
        )
        agg['_rx_sum'] += row['rx_bps']
        agg['_tx_sum'] += row['tx_bps']
        agg['peak_rx_bps'] = max(agg['peak_rx_bps'], row['rx_bps'])
        agg['peak_tx_bps'] = max(agg['peak_tx_bps'], row['tx_bps'])
        agg['sample_count'] += 1
    return [
        {
            bucket_key: agg[bucket_key],
            'vlan_id': agg['vlan_id'],
            'network_name': agg['network_name'],
            'avg_rx_bps': agg['_rx_sum'] / agg['sample_count'],
            'avg_tx_bps': agg['_tx_sum'] / agg['sample_count'],
            'peak_rx_bps': agg['peak_rx_bps'],
            'peak_tx_bps': agg['peak_tx_bps'],
            'sample_count': agg['sample_count'],
        }
        for agg in buckets.values()
    ]


def rollup_hour(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold interval rate rows (``bucket`` floored to the hour) into per-hour rows. Pure."""
    return _rollup(rows, 'hour_utc')


def rollup_day(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold hourly rows (``bucket`` floored to the day) into per-day rows. Pure."""
    return _rollup(rows, 'day_utc')


def floor_to_hour(ts_utc: int) -> int:
    """Floor a UTC epoch time to the start of its hour."""
    return (ts_utc // 3600) * 3600


def floor_to_day(ts_utc: int) -> int:
    """Floor a UTC epoch time to the start of its day."""
    return (ts_utc // 86400) * 86400


# --- run_rollups (July's cadence-safe logic) -----------------------------------------------


def _get_high_water_mark(conn: sqlite3.Connection, tier: str) -> int | None:
    row = conn.execute(
        'SELECT last_rolled_bucket FROM rollup_state WHERE tier = ?', (tier,)
    ).fetchone()
    return int(row[0]) if row is not None else None


def _set_high_water_mark(conn: sqlite3.Connection, tier: str, bucket: int) -> None:
    conn.execute(
        'INSERT OR REPLACE INTO rollup_state (tier, last_rolled_bucket) VALUES (?, ?)',
        (tier, bucket),
    )


def _roll_raw(conn: sqlite3.Connection, now: int) -> tuple[int, int]:
    """Roll complete aged hours of raw samples into hourly rows; return (read, written)."""
    max_rollable_hour = floor_to_hour(now - RAW_RETENTION_SECONDS - 3600)
    hwm = _get_high_water_mark(conn, 'hourly')
    if hwm is not None and max_rollable_hour <= hwm:
        return 0, 0
    rollable_end = max_rollable_hour + 3600
    raw = conn.execute(
        'SELECT ts_utc, vlan_id, network_name, rx_bytes, tx_bytes '
        'FROM raw_samples WHERE ts_utc < ? ORDER BY vlan_id, ts_utc',
        (rollable_end,),
    ).fetchall()
    rate_rows: list[dict[str, Any]] = []
    prev_by_vlan: dict[int, dict[str, Any]] = {}
    for row in raw:
        cur = {'ts_utc': row['ts_utc'], 'rx_bytes': row['rx_bytes'], 'tx_bytes': row['tx_bytes']}
        rates = compute_rates(prev_by_vlan.get(row['vlan_id']), cur)
        prev_by_vlan[row['vlan_id']] = cur
        if rates is None:
            continue
        bucket = floor_to_hour(row['ts_utc'])
        if hwm is not None and bucket <= hwm:  # rolled already: only a boundary carry
            continue
        rate_rows.append(
            {
                'bucket': bucket,
                'vlan_id': row['vlan_id'],
                'network_name': row['network_name'],
                **rates,
            }
        )
    hourly = rollup_hour(rate_rows)
    conn.executemany(
        'INSERT OR REPLACE INTO hourly_rollup (hour_utc, vlan_id, network_name, avg_rx_bps, '
        'avg_tx_bps, peak_rx_bps, peak_tx_bps, sample_count) VALUES (:hour_utc, :vlan_id, '
        ':network_name, :avg_rx_bps, :avg_tx_bps, :peak_rx_bps, :peak_tx_bps, :sample_count)',
        hourly,
    )
    # Keep the newest rolled row per VLAN, to pair with the next hour's first sample.
    conn.execute(
        'DELETE FROM raw_samples WHERE ts_utc < ? AND ts_utc NOT IN '
        '(SELECT MAX(ts_utc) FROM raw_samples WHERE ts_utc < ? GROUP BY vlan_id)',
        (rollable_end, rollable_end),
    )
    _set_high_water_mark(conn, 'hourly', max_rollable_hour)
    return len(raw), len(hourly)


def _roll_hourly(conn: sqlite3.Connection, now: int) -> tuple[int, int]:
    """Roll complete aged days of hourly rows into daily rows; return (read, written)."""
    max_rollable_day = floor_to_day(now - HOURLY_RETENTION_SECONDS - 86400)
    hwm = _get_high_water_mark(conn, 'daily')
    if hwm is not None and max_rollable_day <= hwm:
        return 0, 0
    source = conn.execute(
        'SELECT hour_utc, vlan_id, network_name, avg_rx_bps, avg_tx_bps, peak_rx_bps, '
        'peak_tx_bps FROM hourly_rollup WHERE (hour_utc / 86400) * 86400 > ? AND hour_utc < ? '
        'ORDER BY vlan_id, hour_utc',
        (-1 if hwm is None else hwm, max_rollable_day + 86400),
    ).fetchall()
    daily = rollup_day(
        [
            {
                'bucket': floor_to_day(row['hour_utc']),
                'vlan_id': row['vlan_id'],
                'network_name': row['network_name'],
                'rx_bps': row['avg_rx_bps'],
                'tx_bps': row['avg_tx_bps'],
            }
            for row in source
        ]
    )
    # The daily peak is the max of the hourly peaks, not of the hourly averages fed above.
    peaks: dict[tuple[int, int], tuple[float, float]] = {}
    for row in source:
        key = (floor_to_day(row['hour_utc']), row['vlan_id'])
        rx, tx = peaks.get(key, (0.0, 0.0))
        peaks[key] = (max(rx, row['peak_rx_bps']), max(tx, row['peak_tx_bps']))
    for row in daily:
        row['peak_rx_bps'], row['peak_tx_bps'] = peaks.get(
            (row['day_utc'], row['vlan_id']), (0.0, 0.0)
        )
    conn.executemany(
        'INSERT OR REPLACE INTO daily_rollup (day_utc, vlan_id, network_name, avg_rx_bps, '
        'avg_tx_bps, peak_rx_bps, peak_tx_bps, sample_count) VALUES (:day_utc, :vlan_id, '
        ':network_name, :avg_rx_bps, :avg_tx_bps, :peak_rx_bps, :peak_tx_bps, :sample_count)',
        daily,
    )
    conn.execute(
        'DELETE FROM hourly_rollup WHERE (hour_utc / 86400) * 86400 <= ?', (max_rollable_day,)
    )
    _set_high_water_mark(conn, 'daily', max_rollable_day)
    return len(source), len(daily)


def run_rollups(path: Path | None = None) -> dict[str, int]:
    """Roll aged raw samples into hourly rows, and aged hourly rows into daily rows.

    Correct under any cadence (hourly, every five minutes, two runs at once): each tier keeps
    a high-water mark in ``rollup_state`` and rolls only complete buckets, each exactly once,
    and the newest rolled raw row per VLAN is kept so the next run pairs it with the next
    hour's first sample. Opening the store writable also rolls back a hot journal a crashed
    sampler left, so this recovers a store a read reported as needing recovery.

    Args:
        path: The store (default :func:`default_db_path`).

    Returns:
        ``raw_rows_rolled``, ``hourly_rows_written``, ``hourly_rows_rolled`` and
        ``daily_rows_written``.
    """
    store = default_db_path() if path is None else Path(path)
    conn = open_store(store, writable=True)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            now = int(time.time())
            raw_read, hourly_written = _roll_raw(conn, now)
            hourly_read, daily_written = _roll_hourly(conn, now)
    except sqlite3.Error as e:
        raise _store_error(e, store, writing=True) from None
    finally:
        conn.close()
    return {
        'raw_rows_rolled': raw_read,
        'hourly_rows_written': hourly_written,
        'hourly_rows_rolled': hourly_read,
        'daily_rows_written': daily_written,
    }


# --- the report and the coverage (July's queries) ------------------------------------------


def _tier_for_period(period: str) -> str:
    tier = _PERIOD_TIERS.get(period)
    if tier is None:
        raise ToolError(
            message=f'Unknown period {period!r}',
            error_code=ErrorCodes.CONFIG_INVALID,
            suggestion="Use one of: 'now', '1d', '1w', '1m', '1y'.",
        )
    return tier


def _empty_aggregate(name: str) -> dict[str, Any]:
    return {
        'network_name': name,
        'rx_sum': 0.0,
        'tx_sum': 0.0,
        'peak_rx_bps': 0.0,
        'peak_tx_bps': 0.0,
        'valid_intervals': 0,
        'samples': 0,
    }


def _raw_rates(conn: sqlite3.Connection, since: int) -> dict[int, dict[str, Any]]:
    """Aggregate raw samples in ``[since, now]`` into per-VLAN averages and peaks."""
    prev_by_vlan: dict[int, dict[str, Any]] = {}
    result: dict[int, dict[str, Any]] = {}
    for row in conn.execute(
        'SELECT ts_utc, vlan_id, network_name, rx_bytes, tx_bytes '
        'FROM raw_samples WHERE ts_utc >= ? ORDER BY vlan_id, ts_utc',
        (since,),
    ):
        cur = {'ts_utc': row['ts_utc'], 'rx_bytes': row['rx_bytes'], 'tx_bytes': row['tx_bytes']}
        rates = compute_rates(prev_by_vlan.get(row['vlan_id']), cur)
        prev_by_vlan[row['vlan_id']] = cur
        agg = result.setdefault(row['vlan_id'], _empty_aggregate(row['network_name']))
        agg['samples'] += 1
        if rates is not None:
            agg['rx_sum'] += rates['rx_bps']
            agg['tx_sum'] += rates['tx_bps']
            agg['peak_rx_bps'] = max(agg['peak_rx_bps'], rates['rx_bps'])
            agg['peak_tx_bps'] = max(agg['peak_tx_bps'], rates['tx_bps'])
            agg['valid_intervals'] += 1
    return result


def _rollup_rates(conn: sqlite3.Connection, tier: str, since: int) -> dict[int, dict[str, Any]]:
    """Aggregate the hourly or daily rows since ``since`` per VLAN."""
    table, column = (
        ('hourly_rollup', 'hour_utc') if tier == 'hourly' else ('daily_rollup', 'day_utc')
    )
    result: dict[int, dict[str, Any]] = {}
    for row in conn.execute(
        f'SELECT vlan_id, network_name, avg_rx_bps, avg_tx_bps, peak_rx_bps, peak_tx_bps '
        f'FROM {table} WHERE {column} >= ? ORDER BY vlan_id, {column}',
        (since,),
    ):
        agg = result.setdefault(row['vlan_id'], _empty_aggregate(row['network_name']))
        agg['samples'] += 1
        agg['rx_sum'] += row['avg_rx_bps']
        agg['tx_sum'] += row['avg_tx_bps']
        agg['peak_rx_bps'] = max(agg['peak_rx_bps'], row['peak_rx_bps'])
        agg['peak_tx_bps'] = max(agg['peak_tx_bps'], row['peak_tx_bps'])
        agg['valid_intervals'] += 1
    return result


def _read(path: Path | None, query: Any) -> Any:
    """Run ``query(conn)`` on a read-only handle, mapping SQLite's errors by name."""
    store = default_db_path() if path is None else Path(path)
    conn = open_store(store, writable=False)
    conn.row_factory = sqlite3.Row
    try:
        return query(conn)
    except sqlite3.Error as e:
        raise _store_error(e, store, writing=False) from None
    finally:
        conn.close()


def read_vlan_traffic_report(period: str, path: Path | None = None) -> dict[str, Any]:
    """Per-VLAN average and peak throughput over a period, from the store's matching tier.

    ``now`` and ``1d`` read raw samples, ``1w`` and ``1m`` hourly rollups, ``1y`` daily
    rollups; ``methodology`` names the tier and its smoothing caveats.

    Args:
        period: ``now``, ``1d``, ``1w``, ``1m`` or ``1y``.
        path: The store (default :func:`default_db_path`).

    Returns:
        ``period``, ``vlans`` (``network_name``, ``vlan_id``, the averages and peaks in bits
        per second, ``samples``, ``coverage_pct``) and ``methodology``.

    Raises:
        ToolError: ``CONFIG_INVALID`` for an unknown period, ``NO_DATA`` for a missing
            store, ``API_ERROR`` for a store that can't be read.
    """
    tier = _tier_for_period(period)
    since = int(time.time()) - _PERIOD_SECONDS[period]
    aggregates = _read(
        path,
        lambda conn: _raw_rates(conn, since)
        if tier == 'raw'
        else _rollup_rates(conn, tier, since),
    )
    vlans = []
    for vlan_id, agg in sorted(aggregates.items()):
        valid = agg['valid_intervals']
        vlans.append(
            {
                'network_name': agg['network_name'],
                'vlan_id': vlan_id,
                'avg_rx_bps': round(agg['rx_sum'] / valid if valid else 0.0, 1),
                'avg_tx_bps': round(agg['tx_sum'] / valid if valid else 0.0, 1),
                'peak_rx_bps': round(agg['peak_rx_bps'], 1),
                'peak_tx_bps': round(agg['peak_tx_bps'], 1),
                'samples': agg['samples'],
                'coverage_pct': round(100.0 * valid / agg['samples'], 1)
                if agg['samples']
                else 0.0,
            }
        )
    meta = _TIER_METHODOLOGY[tier]
    return {
        'period': period,
        'vlans': vlans,
        'methodology': {
            'tier_used': tier,
            'interval_s': meta['interval_s'],
            'caveats': list(meta['caveats']),
        },
    }


def _coverage(timestamps: Iterable[int], expected_spacing: int) -> dict[str, Any]:
    """Earliest, latest, count and gaps (spacing plus 5 min exceeded) of one tier's rows."""
    ts = sorted(timestamps)
    if not ts:
        return {'earliest': None, 'latest': None, 'count': 0, 'gaps_over_5min': 0}
    cutoff = expected_spacing + GAP_THRESHOLD_SECONDS
    gaps = sum(1 for prev, cur in zip(ts, ts[1:], strict=False) if cur - prev > cutoff)
    return {'earliest': ts[0], 'latest': ts[-1], 'count': len(ts), 'gaps_over_5min': gaps}


def read_vlan_traffic_periods(path: Path | None = None) -> dict[str, Any]:
    """What each tier of the store holds, so a 0 average can be told from no data.

    Args:
        path: The store (default :func:`default_db_path`).

    Returns:
        ``raw``, ``hourly`` and ``daily``, each ``{earliest, latest, count,
        gaps_over_5min}`` (None and 0 for an empty tier).

    Raises:
        ToolError: ``NO_DATA`` for a missing store, ``API_ERROR`` for one that can't be read.
    """

    def query(conn: sqlite3.Connection) -> dict[str, Any]:
        def stamps(sql: str) -> list[int]:
            return [row[0] for row in conn.execute(sql)]

        return {
            'raw': _coverage(
                stamps('SELECT DISTINCT ts_utc FROM raw_samples'), DEFAULT_SAMPLE_INTERVAL_SECONDS
            ),
            'hourly': _coverage(stamps('SELECT DISTINCT hour_utc FROM hourly_rollup'), 3600),
            'daily': _coverage(stamps('SELECT DISTINCT day_utc FROM daily_rollup'), 86400),
        }

    return _read(path, query)


# --- the MCP tools (the default store, read in a thread) -----------------------------------


async def get_vlan_traffic_report(
    period: Annotated[Period, Field(description='now, 1d, 1w, 1m or 1y')],
) -> dict[str, Any]:
    """Per-VLAN throughput over a period, from the local VLAN traffic store. Read-only.

    When to use this tool:
    - Which VLAN carries the traffic now, today, this week, month or year?
    - Average against peak receive and transmit rates per VLAN

    The store is filled by `unifi-mapper vlan-traffic sample` (the gateway's bridge byte
    counters, read over SSH by a person or a schedule; none is published until issue 038 is
    decided). now and 1d read raw samples, 1w and 1m hourly rollups and 1y daily rollups;
    methodology names the tier and how much it smooths peaks. Needs no credentials and
    sends no request. Run list_vlan_traffic_periods first to tell an idle VLAN (0 bps) from
    a window with no samples.

    Args:
        period: now, 1d, 1w, 1m or 1y.

    Returns:
        period, vlans and methodology.

    Raises:
        ToolError: NO_DATA when there is no store yet; API_ERROR when it is busy, needs
            recovery or can't be read.
    """
    return await asyncio.to_thread(read_vlan_traffic_report, period)


async def list_vlan_traffic_periods() -> dict[str, Any]:
    """What the local VLAN traffic store holds per tier, and its gaps. Read-only.

    When to use this tool:
    - Before get_vlan_traffic_report, to tell an idle VLAN (0 bps) from no samples
    - To see whether sampling has been running (latest sample time, gaps over 5 minutes)

    Needs no credentials and sends no request.

    Returns:
        raw, hourly and daily, each earliest, latest, count and gaps_over_5min.

    Raises:
        ToolError: NO_DATA when there is no store yet; API_ERROR when it is busy, needs
            recovery or can't be read.
    """
    return await asyncio.to_thread(read_vlan_traffic_periods)
