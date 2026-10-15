"""`read_vlan_traffic_periods` and `read_vlan_traffic_report` agree on what a gap is (issue 089).

``report`` rates a pair of samples unless they are further apart than
``max_measured_interval(_measured_grace(conn))``: the gap threshold plus twice the measured
sampling interval. ``coverage`` sized its gap check with the fixed default interval instead,
so at a 5-minute cadence an 800 s interval was rated by ``report`` and counted as a gap by
``coverage``. Both now use the measured grace.
"""

from __future__ import annotations

import pytest
import sqlite3
from pathlib import Path
from unifi_mapper.analysis.vlan_traffic_store import (
    open_store,
    read_vlan_traffic_periods,
    read_vlan_traffic_report,
)


FAR_FUTURE = 2_000_000_000  # so the '1d' window includes the rows
CADENCE = 300  # a 5-minute sampler: grace 600 s, so a pair up to 900 s apart is measured


def _insert_raw(conn: sqlite3.Connection, ts: int, rx: int) -> None:
    conn.execute(
        'INSERT INTO raw_samples (ts_utc, vlan_id, network_name, iface, rx_bytes, tx_bytes) '
        'VALUES (?, 10, ?, ?, ?, 0)',
        (ts, 'LAN', 'br10', rx),
    )


def _store_with_one_wide_interval(path: Path, wide: int) -> int:
    """Nine samples every 5 minutes, then one ``wide`` seconds later; returns the last time."""
    stamps = [FAR_FUTURE - 86_000 + i * CADENCE for i in range(9)]
    stamps.append(stamps[-1] + wide)
    with open_store(path, writable=True) as conn:
        for i, ts in enumerate(stamps):
            _insert_raw(conn, ts, i * 37_500_000)
    return stamps[-1]


@pytest.mark.parametrize(
    ('wide', 'valid_pct', 'gaps'),
    [
        (800, 90.0, 0),  # within the measured bound: rated, and no gap
        (1000, 80.0, 1),  # past it: not rated, and one gap
    ],
    ids=['a missed sample or two', 'a sampler outage'],
)
def test_coverage_and_report_judge_an_interval_the_same_way(
    tmp_path: Path, wide: int, valid_pct: float, gaps: int
) -> None:
    path = tmp_path / 'store.sqlite3'
    last = _store_with_one_wide_interval(path, wide)

    (vlan,) = read_vlan_traffic_report('1d', path, now=last + 60)['vlans']
    raw = read_vlan_traffic_periods(path)['raw']

    # Ten samples; the first has nothing before it, so at most nine are rated.
    assert (vlan['samples'], vlan['valid_sample_pct']) == (10, valid_pct)
    assert (raw['count'], raw['gaps_over_5min']) == (10, gaps)
