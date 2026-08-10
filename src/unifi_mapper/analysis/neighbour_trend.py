"""Neighbour AP trend tracking — baseline snapshot and diff.

Snapshots the current passive neighbour AP data (stat/rogueap) and compares
against a baseline to detect new/disappeared neighbours, channel moves, and
significant signal changes. Mirrors the baseline/delta pattern used by
link_error_tracking and config_drift.

Residential neighbour landscapes change slowly but meaningfully. New APs
appearing on the same channel as your own APs are a signal that today's
optimal channel assignment may be suboptimal tomorrow.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unifi_mapper.analysis.neighbour_scan import filter_live_rogue_entries
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


DEFAULT_BASELINE_PATH = 'reports/neighbour-baseline.json'

# Signal change threshold (dB) — below this, treat as noise
DEFAULT_SIGNAL_DELTA_DB = 10


async def snapshot_neighbours(
    output_path: str = DEFAULT_BASELINE_PATH,
) -> dict[str, Any]:
    """Capture the current neighbour AP landscape as a baseline.

    Stores one entry per (ap_mac, bssid) pair so the same external network
    seen by two different own-APs counts twice — we care about what each
    of our APs sees, not just the unique neighbour set.
    """
    async with UniFiClient() as client:
        rogue_entries = await client.get_rogue_aps()

    live = filter_live_rogue_entries(rogue_entries)

    # Keep only the fields we need for trend analysis
    entries = [
        {
            'bssid': e.get('bssid', ''),
            'essid': e.get('essid', ''),
            'channel': e.get('channel', 0),
            'signal': e.get('signal', -100),
            'band': e.get('band', ''),
            'ap_mac': e.get('ap_mac', ''),
        }
        for e in live
    ]

    snapshot = {
        'timestamp': datetime.now().isoformat(),
        'entry_count': len(entries),
        'entries': entries,
    }

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2))
    return snapshot


def _key(entry: dict[str, Any]) -> tuple[str, str]:
    """Index entries by (detecting AP MAC, neighbour BSSID) pair."""
    return (entry.get('ap_mac', ''), entry.get('bssid', ''))


def _compare_snapshots(
    baseline: dict[str, Any],
    current: dict[str, Any],
    signal_delta_threshold: int,
) -> dict[str, Any]:
    """Pure diff function — testable without hitting the network."""
    baseline_map = {_key(e): e for e in baseline.get('entries', [])}
    current_map = {_key(e): e for e in current.get('entries', [])}

    baseline_keys = set(baseline_map.keys())
    current_keys = set(current_map.keys())

    new_entries = [current_map[k] for k in current_keys - baseline_keys]
    disappeared = [baseline_map[k] for k in baseline_keys - current_keys]

    moved: list[dict[str, Any]] = []
    signal_changes: list[dict[str, Any]] = []

    for k in baseline_keys & current_keys:
        prev = baseline_map[k]
        curr = current_map[k]

        if prev.get('channel') != curr.get('channel'):
            moved.append(
                {
                    'ap_mac': curr.get('ap_mac', ''),
                    'bssid': curr.get('bssid', ''),
                    'essid': curr.get('essid', ''),
                    'from_channel': prev.get('channel'),
                    'to_channel': curr.get('channel'),
                    'signal': curr.get('signal'),
                }
            )

        prev_signal = prev.get('signal', -100)
        curr_signal = curr.get('signal', -100)
        delta = curr_signal - prev_signal
        if abs(delta) >= signal_delta_threshold:
            signal_changes.append(
                {
                    'ap_mac': curr.get('ap_mac', ''),
                    'bssid': curr.get('bssid', ''),
                    'essid': curr.get('essid', ''),
                    'channel': curr.get('channel'),
                    'signal_before': prev_signal,
                    'signal_after': curr_signal,
                    'delta_db': delta,
                }
            )

    # Sort for deterministic output
    new_entries.sort(key=lambda e: e.get('signal', -100), reverse=True)
    disappeared.sort(key=lambda e: e.get('signal', -100), reverse=True)
    moved.sort(key=lambda e: e.get('signal', -100), reverse=True)
    signal_changes.sort(key=lambda e: abs(e.get('delta_db', 0)), reverse=True)

    return {
        'baseline_timestamp': baseline.get('timestamp', ''),
        'current_timestamp': current.get('timestamp', ''),
        'signal_delta_threshold_db': signal_delta_threshold,
        'new_count': len(new_entries),
        'disappeared_count': len(disappeared),
        'moved_count': len(moved),
        'signal_changed_count': len(signal_changes),
        'new': new_entries,
        'disappeared': disappeared,
        'moved': moved,
        'signal_changes': signal_changes,
    }


async def detect_neighbour_trend(
    baseline_path: str = DEFAULT_BASELINE_PATH,
    signal_delta_threshold: int = DEFAULT_SIGNAL_DELTA_DB,
) -> dict[str, Any]:
    """Compare current neighbour landscape against baseline snapshot.

    Args:
        baseline_path: Path to baseline JSON (produced by snapshot_neighbours)
        signal_delta_threshold: Absolute dB change to flag as significant

    Returns:
        Dict with counts and per-category lists of changes.
    """
    path = Path(baseline_path)
    if not path.exists():
        raise ToolError(
            message=f'No neighbour baseline found at {baseline_path}. Run snapshot first.',
            error_code=ErrorCodes.NO_DATA,
            suggestion='Run: unifi-mapper analyze neighbours --snapshot',
        )

    baseline = json.loads(path.read_text())

    # Build a fresh current snapshot in-memory (not written to disk)
    async with UniFiClient() as client:
        rogue_entries = await client.get_rogue_aps()

    live = filter_live_rogue_entries(rogue_entries)
    current = {
        'timestamp': datetime.now().isoformat(),
        'entry_count': len(live),
        'entries': [
            {
                'bssid': e.get('bssid', ''),
                'essid': e.get('essid', ''),
                'channel': e.get('channel', 0),
                'signal': e.get('signal', -100),
                'band': e.get('band', ''),
                'ap_mac': e.get('ap_mac', ''),
            }
            for e in live
        ],
    }

    return _compare_snapshots(baseline, current, signal_delta_threshold)
