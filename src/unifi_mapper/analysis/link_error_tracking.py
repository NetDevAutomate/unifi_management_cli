"""Link error rate tracking with baseline snapshots and delta comparison.

Takes periodic snapshots of port error/drop counters and compares deltas
to distinguish active degradation from cumulative historical errors.

The comparison baseline lives at ``$XDG_STATE_HOME/unifi_mapper/link-error-baseline.json``
(see :func:`default_link_error_baseline_path`) and is written only by
``analyze link-errors --snapshot``, which also writes the port-counter baseline store.
A baseline left at the old working-directory path ``reports/link-error-baseline.json``
is still read when the XDG file does not exist, and is reported as legacy.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from unifi_mapper.analysis.port_counter_baseline import (
    SWITCH_DEVICE_TYPES,
    PortCounterBaselineStore,
    snapshots_from_devices,
    state_dir,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


LINK_ERROR_BASELINE_FILENAME = 'link-error-baseline.json'
# The pre-XDG default, relative to the working directory. Still read when the XDG
# baseline does not exist; never written by default.
LEGACY_LINK_ERROR_BASELINE = 'reports/link-error-baseline.json'
# Kept importable for callers of the old constant; it names the legacy path.
DEFAULT_BASELINE_PATH = LEGACY_LINK_ERROR_BASELINE


def default_link_error_baseline_path() -> Path:
    """Return ``state_dir() / 'link-error-baseline.json'`` (nothing is created)."""
    return state_dir() / LINK_ERROR_BASELINE_FILENAME


def resolve_link_error_baseline(explicit: Optional[str | Path] = None) -> tuple[Path, bool]:
    """Return ``(path, is_legacy)`` for the link-error baseline to read.

    An explicit path always wins. Otherwise the XDG baseline is used when it
    exists, then a legacy ``reports/link-error-baseline.json`` in the working
    directory (flagged as legacy). With neither, the XDG path is returned, so a
    missing baseline is reported where ``--snapshot`` would write it.
    """
    if explicit:
        return Path(explicit), False
    xdg = default_link_error_baseline_path()
    if xdg.exists():
        return xdg, False
    legacy = Path.cwd() / LEGACY_LINK_ERROR_BASELINE
    if legacy.exists():
        return legacy, True
    return xdg, False


async def fetch_devices() -> list[dict[str, Any]]:
    """Read every device once (``stat/device``) for a snapshot or a history record."""
    async with UniFiClient() as client:
        return await client.get_devices()


def build_link_error_snapshot(devices: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Return the link-error baseline document for ``devices``. Pure."""
    snapshot: dict[str, Any] = {'timestamp': now.isoformat(), 'devices': []}

    for d in devices:
        if d.get('type') not in SWITCH_DEVICE_TYPES:
            continue
        # A factory-reset / pending-adoption device has no '_id'. There is no stable key
        # to anchor a baseline to, so it is skipped rather than crashing the snapshot.
        if not d.get('_id'):
            continue
        dev_entry: dict[str, Any] = {
            'device_id': d['_id'],
            'name': d.get('name', 'Unknown'),
            'uptime': d.get('uptime', 0),
            'ports': [],
        }
        for p in d.get('port_table', []):
            dev_entry['ports'].append(
                {
                    'port_idx': p.get('port_idx'),
                    'name': p.get('name', ''),
                    'rx_errors': p.get('rx_errors', 0) or 0,
                    'tx_errors': p.get('tx_errors', 0) or 0,
                    'rx_dropped': p.get('rx_dropped', 0) or 0,
                    'tx_dropped': p.get('tx_dropped', 0) or 0,
                    'rx_bytes': p.get('rx_bytes', 0) or 0,
                    'tx_bytes': p.get('tx_bytes', 0) or 0,
                }
            )
        snapshot['devices'].append(dev_entry)
    return snapshot


async def snapshot_link_errors(
    output_path: Optional[str | Path] = None,
    *,
    store_path: Optional[Path] = None,
    devices: Optional[list[dict[str, Any]]] = None,
) -> dict:
    """Set the comparison baselines: the link-error baseline and the port-counter store.

    Args:
        output_path: Link-error baseline file; defaults to
            :func:`default_link_error_baseline_path`.
        store_path: Port-counter baseline store; defaults to its XDG path.
        devices: Already-fetched ``stat/device`` rows; fetched when None.

    Returns:
        The link-error baseline document that was written.
    """
    if devices is None:
        devices = await fetch_devices()
    now = datetime.now()
    snapshot = build_link_error_snapshot(devices, now)

    path = Path(output_path) if output_path else default_link_error_baseline_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2))
    PortCounterBaselineStore(store_path).save(
        snapshots_from_devices(devices, timestamp=now.isoformat())
    )
    return snapshot


async def compare_link_errors(
    baseline_path: Optional[str | Path] = None,
    threshold_errors_per_min: float = 10.0,
) -> dict:
    """Compare current error counters against baseline to find active degradation.

    Read only: never writes a baseline or the history.

    Args:
        baseline_path: Path to baseline snapshot JSON; None resolves the default
            with :func:`resolve_link_error_baseline`.
        threshold_errors_per_min: Flag ports exceeding this error rate

    Returns:
        Report with deltas and flagged ports, plus ``baseline_path`` and
        ``legacy_baseline``.
    """
    path, legacy = resolve_link_error_baseline(baseline_path)
    if not path.exists():
        raise ToolError(
            message=f'No baseline found at {path}. Run snapshot first.',
            error_code=ErrorCodes.NO_DATA,
            suggestion='Run: unifi-mapper analyze link-errors --snapshot',
        )

    baseline = json.loads(path.read_text())
    baseline_time = datetime.fromisoformat(baseline['timestamp'])

    async with UniFiClient() as client:
        devices = await client.get_devices()

    now = datetime.now()
    elapsed_minutes = max((now - baseline_time).total_seconds() / 60, 1)

    # Build baseline lookup: (device_id, port_idx) -> counters
    # Also track baseline uptime per device for reboot detection
    baseline_lookup = {}
    baseline_uptime = {}
    for dev in baseline['devices']:
        baseline_uptime[dev['device_id']] = dev.get('uptime', 0)
        for port in dev['ports']:
            key = (dev['device_id'], port['port_idx'])
            baseline_lookup[key] = port

    # Detect devices that rebooted between snapshots
    # A reboot is: current uptime < baseline uptime (counter reset to 0 on boot)
    rebooted_devices: dict[str, dict] = {}
    for d in devices:
        if d.get('type') not in SWITCH_DEVICE_TYPES:
            continue
        dev_id = d.get('_id')
        if not dev_id:
            continue
        prev_uptime = baseline_uptime.get(dev_id)
        curr_uptime = d.get('uptime', 0)
        if prev_uptime is not None and curr_uptime < prev_uptime:
            rebooted_devices[dev_id] = {
                'name': d.get('name', 'Unknown'),
                'previous_uptime_s': prev_uptime,
                'current_uptime_s': curr_uptime,
            }

    flagged = []
    all_deltas = []

    for d in devices:
        if d.get('type') not in SWITCH_DEVICE_TYPES:
            continue
        dev_id = d.get('_id')
        if not dev_id:
            continue
        dev_name = d.get('name', 'Unknown')

        for p in d.get('port_table', []):
            port_idx = p.get('port_idx')
            key = (dev_id, port_idx)
            prev = baseline_lookup.get(key)
            if not prev:
                continue

            rx_err_delta = max(0, (p.get('rx_errors', 0) or 0) - prev['rx_errors'])
            tx_err_delta = max(0, (p.get('tx_errors', 0) or 0) - prev['tx_errors'])
            rx_drop_delta = max(0, (p.get('rx_dropped', 0) or 0) - prev['rx_dropped'])
            tx_drop_delta = max(0, (p.get('tx_dropped', 0) or 0) - prev['tx_dropped'])
            total_delta = rx_err_delta + tx_err_delta + rx_drop_delta + tx_drop_delta

            if total_delta == 0:
                continue

            rate_per_min = total_delta / elapsed_minutes
            entry = {
                'device': dev_name,
                'port_idx': port_idx,
                'port_name': p.get('name', f'Port {port_idx}'),
                'rx_errors_delta': rx_err_delta,
                'tx_errors_delta': tx_err_delta,
                'rx_dropped_delta': rx_drop_delta,
                'tx_dropped_delta': tx_drop_delta,
                'total_delta': total_delta,
                'rate_per_min': round(rate_per_min, 1),
                'elapsed_minutes': round(elapsed_minutes, 1),
                'reboot_detected': dev_id in rebooted_devices,
            }
            all_deltas.append(entry)

            # Skip flagging on rebooted devices: counter resets make deltas
            # meaningless (the "new" counters started at 0 after boot).
            if rate_per_min >= threshold_errors_per_min and dev_id not in rebooted_devices:
                entry['severity'] = 'CRITICAL' if rate_per_min > 100 else 'WARNING'
                flagged.append(entry)

    # Sort by rate descending
    all_deltas.sort(key=lambda x: -x['rate_per_min'])
    flagged.sort(key=lambda x: -x['rate_per_min'])

    return {
        'timestamp': now.isoformat(),
        'baseline_path': str(path),
        'legacy_baseline': legacy,
        'baseline_timestamp': baseline['timestamp'],
        'elapsed_minutes': round(elapsed_minutes, 1),
        'threshold_errors_per_min': threshold_errors_per_min,
        'ports_with_new_errors': len(all_deltas),
        'ports_flagged': len(flagged),
        'flagged': flagged,
        'all_deltas': all_deltas[:20],  # Top 20
        'rebooted_devices': list(rebooted_devices.values()),
    }
