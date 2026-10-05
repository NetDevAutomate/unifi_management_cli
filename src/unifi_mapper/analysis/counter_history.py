"""A capped JSON Lines history of switch port counters under the XDG state root.

``unifi-mapper analyze link-errors --record`` appends one line per switch per run
to ``$XDG_STATE_HOME/unifi_mapper/port-counter-history.jsonl``. The history is
kept separate from the comparison baselines (``--snapshot``), so recording never
moves the point a comparison is made against.

Writing happens only in :func:`append_history`, behind that explicit flag, through the
shared capped writer (``core/utils/jsonl.append_capped_jsonl``): an exclusive
``fcntl.flock`` on a sibling ``.lock`` file, an append, and a compaction through a
temporary file plus ``os.replace`` only when the age or size cap is exceeded (with
hysteresis, so a full file is not rewritten on every run), so a reader never sees a
half-written file.

:func:`read_port_history` and :func:`summarise_port_history` only read. They feed
the ``baselines.history`` section of ``ports counters``, ``ports diagnose``,
``get_port_counter_rates`` and ``diagnose_switch_port``, answering "when did this
counter start increasing?".
"""

import json
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Any, Iterable, Optional
from unifi_mapper.analysis.port_counter_baseline import SWITCH_DEVICE_TYPES, state_dir
from unifi_mapper.core.utils.jsonl import (
    COMPACT_LOW_WATER_RATIO as COMPACT_LOW_WATER_RATIO,  # re-exported: the cap's low water
)
from unifi_mapper.core.utils.jsonl import append_capped_jsonl, compact_jsonl_lines
from unifi_mapper.diagnostic_reads import crc_errors, int_or_none, normalise_mac, str_or_none


HISTORY_SCHEMA_VERSION = 1
HISTORY_FILENAME = 'port-counter-history.jsonl'
DEFAULT_RETENTION_DAYS = 14
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365
DEFAULT_MAX_HISTORY_BYTES = 64 * 1024 * 1024
HISTORY_POINTS_LIMIT = 48
SECONDS_PER_DAY = 86400
# Hysteresis, so a file at a cap is not rewritten on every append: compaction trims to
# COMPACT_LOW_WATER_RATIO (core/utils/jsonl) of max_bytes, and an age compaction waits until
# the oldest line is this far past the retention cutoff (then drops everything older).
AGE_COMPACTION_GRACE_SECONDS = SECONDS_PER_DAY

# Counters recorded per port, in output order.
HISTORY_COUNTERS = (
    'rx_errors',
    'tx_errors',
    'rx_dropped',
    'tx_dropped',
    'rx_crc_errors',
    'link_down_count',
    'rx_bytes',
    'tx_bytes',
)


class HistoryPoint(BaseModel):
    """One recorded sample of one port."""

    taken_at: Optional[str] = None
    epoch: float
    uptime: Optional[int] = None
    last_seen: Optional[int] = None
    up: Optional[bool] = None
    speed: Optional[int] = None
    full_duplex: Optional[bool] = None
    rx_errors: Optional[int] = None
    tx_errors: Optional[int] = None
    rx_dropped: Optional[int] = None
    tx_dropped: Optional[int] = None
    rx_crc_errors: Optional[int] = None
    link_down_count: Optional[int] = None
    rx_bytes: Optional[int] = None
    tx_bytes: Optional[int] = None


class FirstIncrease(BaseModel):
    """The first recorded sample in which a counter was higher than the one before."""

    taken_at: Optional[str] = None
    epoch: float
    previous: int
    value: int


class CounterReset(BaseModel):
    """A point where the device rebooted or its counters were cleared."""

    taken_at: Optional[str] = None
    epoch: float
    reason: str  # 'uptime' or the name of the counter that went down


class PortCounterHistoryView(BaseModel):
    """What the recorded history says about one port (read only)."""

    path: str
    found: bool = False
    records: int = 0
    earliest: Optional[str] = None
    latest: Optional[str] = None
    first_increase: dict[str, Optional[FirstIncrease]] = Field(default_factory=lambda: {})
    deltas: dict[str, Optional[int]] = Field(default_factory=lambda: {})
    resets: list[CounterReset] = Field(default_factory=lambda: [])
    points: list[HistoryPoint] = Field(default_factory=lambda: [])
    truncated: bool = False
    error: Optional[str] = None


class HistoryWriteResult(BaseModel):
    """What :func:`append_history` wrote and what compaction removed."""

    path: str
    records_written: int
    compacted: bool = False
    lines_kept: Optional[int] = None
    dropped_by_age: int = 0
    dropped_by_size: int = 0
    dropped_unparsable: int = 0
    bytes: int = 0
    retention_days: int
    max_bytes: int
    earliest_epoch: Optional[float] = None
    span_days: Optional[float] = None


def default_history_path() -> Path:
    """Return ``state_dir() / HISTORY_FILENAME`` (nothing is created)."""
    return state_dir() / HISTORY_FILENAME


def _bool_or_none(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def build_history_records(
    devices: Iterable[Any], *, taken_at: str, epoch: float
) -> list[dict[str, Any]]:
    """Return one history record per switch-type device with an ``_id``.

    Pure: no I/O. A device without ``_id`` (pending adoption) or of another type
    is skipped. Counters that are missing or not numeric are recorded as None.

    Args:
        devices: Raw ``stat/device`` rows.
        taken_at: ISO timestamp for the run.
        epoch: The same instant in Unix seconds.

    Returns:
        JSON-serialisable records, in device order.
    """
    records: list[dict[str, Any]] = []
    for device in devices:
        if not isinstance(device, dict) or device.get('type') not in SWITCH_DEVICE_TYPES:
            continue
        device_id = device.get('_id')
        if not device_id:
            continue
        ports: list[dict[str, Any]] = []
        for entry in device.get('port_table') or []:
            if not isinstance(entry, dict):
                continue
            port_idx = int_or_none(entry.get('port_idx'))
            if port_idx is None:
                continue
            port: dict[str, Any] = {
                'port_idx': port_idx,
                'up': _bool_or_none(entry.get('up')),
                'speed': int_or_none(entry.get('speed')),
                'full_duplex': _bool_or_none(entry.get('full_duplex')),
            }
            for key in HISTORY_COUNTERS:
                raw = crc_errors(entry)[0] if key == 'rx_crc_errors' else entry.get(key)
                port[key] = int_or_none(raw)
            ports.append(port)
        records.append(
            {
                'schema_version': HISTORY_SCHEMA_VERSION,
                'taken_at': taken_at,
                'epoch': epoch,
                'device_id': str(device_id),
                'device_mac': normalise_mac(device.get('mac')),
                'device_name': str_or_none(device.get('name')),
                'uptime': int_or_none(device.get('uptime')),
                'last_seen': int_or_none(device.get('last_seen')),
                'ports': ports,
            }
        )
    return records


def _parse_line(line: str) -> Optional[tuple[dict[str, Any], float]]:
    """Return ``(record, epoch)`` for a valid history line, or None."""
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    epoch = record.get('epoch')
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)):
        return None
    return record, float(epoch)


def _line_epoch(line: str) -> Optional[float]:
    """Return a history line's ``epoch``, or None when the line is not a valid record."""
    parsed = _parse_line(line)
    return parsed[1] if parsed else None


def compact_history_lines(lines: list[str], *, cutoff_epoch: float, max_bytes: int) -> list[str]:
    """Return the lines to keep: drop unparsable and too-old lines, then the oldest over the cap.

    Pure. Lines are in file (append) order, oldest first, and the result keeps that
    order. Every returned line ends with a newline.

    Args:
        lines: History file lines.
        cutoff_epoch: Lines with an ``epoch`` before this are dropped.
        max_bytes: Drop the oldest lines until the total UTF-8 size is at most this.
    """
    return compact_jsonl_lines(
        lines, epoch_of=_line_epoch, cutoff_epoch=cutoff_epoch, max_bytes=max_bytes
    )


def append_history(
    records: list[dict[str, Any]],
    *,
    path: Optional[Path] = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    max_bytes: int = DEFAULT_MAX_HISTORY_BYTES,
    now: float,
) -> HistoryWriteResult:
    """Append ``records`` to the history file, then enforce the age and size caps.

    Creates the directory, holds an exclusive ``flock`` on ``<file>.lock`` for the
    whole append-and-compact, and rewrites the file (temp file + ``os.replace``)
    only when it is larger than ``max_bytes``, its first line is unparsable, or
    its oldest line is more than :data:`AGE_COMPACTION_GRACE_SECONDS` older than
    the ``retention_days`` cutoff. A rewrite drops unparsable lines and every line
    older than the cutoff, then the oldest lines until the file is at most
    :data:`COMPACT_LOW_WATER_RATIO` of ``max_bytes``. So at steady state the file
    is rewritten once per grace period or per 20% of the cap, never on every
    append, and holds between ``retention_days`` and ``retention_days`` + 1 days
    unless the size cap binds first. ``earliest_epoch`` and ``span_days`` report
    the window the file actually holds.

    Args:
        records: Records from :func:`build_history_records`.
        path: History file; defaults to :func:`default_history_path`.
        retention_days: Keep lines newer than this many days (1-365).
        max_bytes: Size cap in bytes (at least 1).
        now: The current time in Unix seconds (the age cutoff is relative to it).

    Raises:
        ValueError: ``retention_days`` or ``max_bytes`` is out of range.
        OSError: The file or its directory cannot be written.
    """
    if not MIN_RETENTION_DAYS <= retention_days <= MAX_RETENTION_DAYS:
        raise ValueError(
            f'retention_days must be between {MIN_RETENTION_DAYS} and {MAX_RETENTION_DAYS}, '
            f'got {retention_days}'
        )
    if max_bytes < 1:
        raise ValueError(f'max_bytes must be at least 1, got {max_bytes}')
    target = path or default_history_path()
    lines = [json.dumps(r, sort_keys=True, separators=(',', ':')) + '\n' for r in records]
    cutoff = now - retention_days * SECONDS_PER_DAY
    written = append_capped_jsonl(
        target,
        lines,
        max_bytes=max_bytes,
        epoch_of=_line_epoch,
        cutoff_epoch=cutoff,
        age_grace_s=AGE_COMPACTION_GRACE_SECONDS,
    )
    result = HistoryWriteResult(
        path=str(target),
        records_written=len(lines),
        compacted=written.compacted,
        lines_kept=written.lines_kept,
        dropped_by_age=written.dropped_by_age,
        dropped_by_size=written.dropped_by_size,
        dropped_unparsable=written.dropped_invalid,
        bytes=written.bytes,
        retention_days=retention_days,
        max_bytes=max_bytes,
        earliest_epoch=written.earliest_epoch,
    )
    if result.earliest_epoch is not None:
        result.span_days = round(max(0.0, now - result.earliest_epoch) / SECONDS_PER_DAY, 1)
    return result


def read_port_history(
    device_id: str,
    port_idx: int,
    *,
    path: Optional[Path] = None,
    since_epoch: Optional[float] = None,
) -> list[HistoryPoint]:
    """Return the recorded points for one port, oldest first. Read only.

    A missing file gives an empty list. Unparsable lines and records for other
    devices or ports are skipped.

    Args:
        device_id: The switch ``_id``.
        port_idx: The port index.
        path: History file; defaults to :func:`default_history_path`.
        since_epoch: Only points at or after this Unix time.

    Raises:
        OSError: The file exists but cannot be read.
    """
    target = path or default_history_path()
    if not target.exists():
        return []
    points: list[HistoryPoint] = []
    with target.open('r', encoding='utf-8', errors='replace') as file:
        for line in file:
            parsed = _parse_line(line)
            if parsed is None:
                continue
            record, epoch = parsed
            if since_epoch is not None and epoch < since_epoch:
                continue
            if str(record.get('device_id')) != device_id:
                continue
            ports = record.get('ports')
            port = next(
                (
                    p
                    for p in (ports if isinstance(ports, list) else [])
                    if isinstance(p, dict) and int_or_none(p.get('port_idx')) == port_idx
                ),
                None,
            )
            if port is None:
                continue
            values = {key: int_or_none(port.get(key)) for key in HISTORY_COUNTERS}
            points.append(
                HistoryPoint(
                    taken_at=str_or_none(record.get('taken_at')),
                    epoch=epoch,
                    uptime=int_or_none(record.get('uptime')),
                    last_seen=int_or_none(record.get('last_seen')),
                    up=_bool_or_none(port.get('up')),
                    speed=int_or_none(port.get('speed')),
                    full_duplex=_bool_or_none(port.get('full_duplex')),
                    **values,
                )
            )
    points.sort(key=lambda point: point.epoch)
    return points


def _reset_reason(before: HistoryPoint, after: HistoryPoint) -> Optional[str]:
    if before.uptime is not None and after.uptime is not None and after.uptime < before.uptime:
        return 'uptime'
    for key in HISTORY_COUNTERS:
        a, b = getattr(before, key), getattr(after, key)
        if a is not None and b is not None and b < a:
            return key
    return None


def summarise_port_history(
    points: list[HistoryPoint],
    *,
    limit: int = HISTORY_POINTS_LIMIT,
    path: str = '',
    found: bool = True,
) -> PortCounterHistoryView:
    """Summarise one port's recorded points. Pure.

    * ``first_increase``: per counter, the first sample that was higher than the
      sample before it (pairs across a reset are skipped), or None.
    * ``deltas``: last minus first per counter, or None when a reset happened in
      the window or either value is missing.
    * ``resets``: every uptime drop or counter decrease between samples.
    * ``points``: the newest ``limit`` points, newest last; ``truncated`` says
      whether older ones were left out.

    Args:
        points: Points from :func:`read_port_history`.
        limit: Maximum points returned in the view.
        path: History file path, reported as-is.
        found: Whether the history file exists.
    """
    ordered = sorted(points, key=lambda point: point.epoch)
    view = PortCounterHistoryView(path=path, found=found, records=len(ordered))
    if not ordered:
        return view
    view.earliest, view.latest = ordered[0].taken_at, ordered[-1].taken_at
    first_increase: dict[str, Optional[FirstIncrease]] = dict.fromkeys(HISTORY_COUNTERS)
    for before, after in zip(ordered, ordered[1:]):
        reason = _reset_reason(before, after)
        if reason is not None:
            view.resets.append(
                CounterReset(taken_at=after.taken_at, epoch=after.epoch, reason=reason)
            )
            continue
        for key in HISTORY_COUNTERS:
            a, b = getattr(before, key), getattr(after, key)
            if first_increase[key] is None and a is not None and b is not None and b > a:
                first_increase[key] = FirstIncrease(
                    taken_at=after.taken_at, epoch=after.epoch, previous=a, value=b
                )
    view.first_increase = first_increase
    first, last = ordered[0], ordered[-1]
    view.deltas = {
        key: (
            getattr(last, key) - getattr(first, key)
            if not view.resets
            and getattr(first, key) is not None
            and getattr(last, key) is not None
            else None
        )
        for key in HISTORY_COUNTERS
    }
    keep = max(0, limit)
    view.points = ordered[-keep:] if keep else []
    view.truncated = len(ordered) > keep
    return view
