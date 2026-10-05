"""Recorded WAN speedtest results under the XDG state directory (no controller access).

``unifi-mapper diagnose wan --record`` appends the controller's last scheduled speedtest to
``state_dir() / 'wan-speedtest-history.jsonl'`` through the shared capped writer: one JSON
line per run, deduplicated by the run's time under the writer's lock, at most 1 MiB, the
file ``0o600`` in a ``0o700`` directory. Reading never writes. This module imports no
controller client, so the MCP tool over it (``credentials: none``) can run with no
credentials at all; it only reads what was recorded.
"""

import asyncio
import json
import math
from pathlib import Path
from pydantic import Field
from typing import Annotated, Any
from unifi_mapper.analysis.port_counter_baseline import state_dir
from unifi_mapper.core.utils.jsonl import CappedWriteResult, append_capped_jsonl, epoch_field


HISTORY_FILENAME = 'wan-speedtest-history.jsonl'
SPEEDTEST_HISTORY_MAX_BYTES = 1024 * 1024  # several thousand runs
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
RECORD_HINT = 'run `unifi-mapper diagnose wan --record` (or schedule it) to record results'
_FIELDS = ('up_mbps', 'down_mbps', 'ping_ms', 'status')
# The last second a date can be shown for (9999-12-31T23:59:59Z). A larger run time is not a
# Unix time in seconds (a millisecond value, or a foreign line), so it is never recorded or read.
MAX_RUN_EPOCH = 253_402_300_799


def plausible_run_epoch(value: object) -> bool:
    """True for a run time in Unix seconds that a date can be shown for (1..MAX_RUN_EPOCH)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and 0 < value <= MAX_RUN_EPOCH


def default_speedtest_history_path() -> Path:
    """Return ``state_dir() / HISTORY_FILENAME`` (read at call time; nothing is created)."""
    return state_dir() / HISTORY_FILENAME


def speedtest_line(last_speedtest: dict[str, Any]) -> str | None:
    """Return the history line for a ``build_wan_health`` speedtest, or None without a time.

    Args:
        last_speedtest: The ``last_speedtest`` block of a WAN health summary.

    Returns:
        One JSON object with ``epoch`` (the run time, the line's identity) and the results,
        or None when the controller gave no run time to date it by, or one that is not a
        Unix time in seconds (:func:`plausible_run_epoch`).
    """
    epoch = last_speedtest.get('run_epoch')
    if not isinstance(epoch, int) or not plausible_run_epoch(epoch):
        return None
    entry = {'epoch': epoch, **{key: last_speedtest.get(key) for key in _FIELDS}}
    return json.dumps(entry, sort_keys=True)


def _run_time(line: str) -> str | None:
    epoch = epoch_field('epoch')(line)
    return None if epoch is None else str(int(epoch))


def append_speedtest(
    last_speedtest: dict[str, Any], path: Path | None = None
) -> CappedWriteResult | None:
    """Append one speedtest result to the history, unless that run is already recorded.

    Args:
        last_speedtest: The ``last_speedtest`` block of a WAN health summary.
        path: The history file (default :func:`default_speedtest_history_path`).

    Returns:
        What was written (``lines_written`` 0 for an already recorded run), or None when the
        result has no run time and nothing was written.

    Raises:
        OSError: The history cannot be written.
    """
    line = speedtest_line(last_speedtest)
    if line is None:
        return None
    return append_capped_jsonl(
        path or default_speedtest_history_path(),
        [line],
        max_bytes=SPEEDTEST_HISTORY_MAX_BYTES,
        epoch_of=epoch_field('epoch'),
        dedup_key=_run_time,
        file_mode=0o600,
        dir_mode=0o700,
    )


def read_speedtest_history(path: Path | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Return the newest recorded speedtest results, newest first. Never writes.

    A line that does not parse, or whose run time is not a Unix time in seconds
    (:func:`plausible_run_epoch`), is skipped, so every entry's time can be shown as a date.

    Args:
        path: The history file (default :func:`default_speedtest_history_path`).
        limit: At most this many entries (1-1000).

    Returns:
        ``path``, ``found``, ``total``, ``returned``, ``entries`` (newest first) and, when
        nothing is recorded, a ``note`` saying how to record.

    Raises:
        ValueError: ``limit`` is out of range.
    """
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f'limit must be between 1 and {MAX_LIMIT}, got {limit}')
    target = path or default_speedtest_history_path()
    result: dict[str, Any] = {'path': str(target), 'found': target.exists()}
    entries: list[dict[str, Any]] = []
    if target.exists():
        for raw in target.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                entry = json.loads(raw)
            except ValueError:
                continue  # a torn or foreign line: skip it, as the writer does
            if isinstance(entry, dict) and plausible_run_epoch(entry.get('epoch')):
                entries.append(entry)  # an out-of-range run time is a foreign line too
    entries.sort(key=lambda e: e['epoch'], reverse=True)
    result.update(total=len(entries), returned=min(len(entries), limit), entries=entries[:limit])
    if not entries:
        result['note'] = f'no history: {RECORD_HINT}'
    return result


async def get_wan_speedtest_history(
    limit: Annotated[
        int, Field(description='At most this many results, newest first, 1-1000', ge=1, le=1000)
    ] = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """The WAN speedtest results recorded so far, newest first. Read-only.

    Reads the history file that ``unifi-mapper diagnose wan --record`` (hourly when
    scheduled) appends to, under the XDG state directory. Needs no credentials and sends no
    request. An empty history returns no entries and a note saying how to record, not an
    error. For the controller's current status and last result, use get_wan_health.

    Args:
        limit: Cap on returned results.

    Returns:
        path, found, total, returned, entries and, when empty, note.
    """
    return await asyncio.to_thread(read_speedtest_history, None, limit)
