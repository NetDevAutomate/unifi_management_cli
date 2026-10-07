"""A capped, locked JSON Lines file: append, deduplicate, and compact by atomic replace.

Every capped history the tools keep under the XDG state root goes through
:func:`append_capped_jsonl`: the port counter history (``analysis/counter_history``), and
the files the July port adds on top of it. One append holds an exclusive ``fcntl.flock`` on
a sibling ``<file>.lock`` for the whole append-and-compact; repairs a torn last line (an
interrupted writer) before appending; optionally drops incoming lines whose key is already
in the file; and compacts through a temporary file plus ``os.replace`` only when the file is
over its size cap, its first line is invalid, or its oldest line is past an age cutoff (with
hysteresis, so a full file is not rewritten on every append).

Only compaction is atomic: ``os.replace`` swaps in the whole new file, so a reader never sees
a half-compacted one. An append writes to the live file, and readers take no lock, so while
an append is in progress a reader can see the file's last line incomplete. Every reader must
skip a line that does not parse; ``read_port_history`` and ``read_speedtest_history`` do.

A line is valid when the caller's ``epoch_of(line)`` returns a number; :func:`epoch_field`
builds that function for a top-level numeric field.

With ``enforce_modes`` (the MCP call log), the file and directory modes that are given hold
on every append, not only on creation: a file, lock file or directory of the current user's
with any group or other bit is changed to the mode, and one owned by another user raises
:class:`NotOwnedError`. The file and its lock are then also opened without following a
symbolic link, so a link in the place of either is refused.

The lock file is created with the file's mode when one is given. ``lock_timeout_s`` bounds
the wait for the lock: an append that cannot take it in time raises
:class:`LockTimeoutError` and appends nothing, so a descriptor that holds the lock (any
account that can read the lock file can hold it) never keeps the caller waiting for the lock
for longer. The append and any compaction after the lock is taken are outside that limit.
"""

import fcntl
import json
import math
import os
import stat
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


# Compaction trims the file to this fraction of max_bytes, so a file at the cap is not
# rewritten on every append.
COMPACT_LOW_WATER_RATIO = 0.8

EpochOf = Callable[[str], float | None]
# The permission bits a private file or directory must not have.
_GROUP_OTHER_BITS = 0o077
# How often a bounded wait tries a held lock again (seconds).
_LOCK_RETRY_S = 0.02


class NotOwnedError(PermissionError):
    """A file or directory that must stay private is owned by another user."""


class LockTimeoutError(OSError):
    """The lock beside a capped file stayed held past ``lock_timeout_s``; nothing was appended."""


@dataclass
class CappedWriteResult:
    """What :func:`append_capped_jsonl` wrote and what compaction removed.

    Attributes:
        path: The file written.
        lines_written: Lines appended (after deduplication).
        skipped_duplicates: Incoming lines dropped because their key was already present.
        bytes: The file's size afterwards.
        compacted: Whether the file was rewritten.
        dropped_invalid: Lines compaction dropped because ``epoch_of`` gave None.
        dropped_by_age: Valid lines compaction dropped as older than the cutoff.
        dropped_by_size: Lines compaction dropped, oldest first, to fit the cap.
        lines_kept: Lines left after a compaction check, or None when none was due.
        earliest_epoch: The first line's epoch afterwards, or None for an empty file.
    """

    path: str
    lines_written: int
    skipped_duplicates: int = 0
    bytes: int = 0
    compacted: bool = False
    dropped_invalid: int = 0
    dropped_by_age: int = 0
    dropped_by_size: int = 0
    lines_kept: int | None = None
    earliest_epoch: float | None = None


def epoch_field(name: str) -> EpochOf:
    """Return an ``epoch_of`` that reads the numeric top-level field ``name``.

    The function returns ``float(obj[name])`` when the line is a JSON object holding a
    finite number (not a ``bool``) under ``name``, else None.

    Args:
        name: The field holding the line's time in Unix seconds.

    Returns:
        A function from one line to its epoch or None.
    """

    def _epoch_of(line: str) -> float | None:
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            return None
        if not isinstance(obj, dict):
            return None
        value = obj.get(name)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        epoch = float(value)
        return epoch if math.isfinite(epoch) else None

    return _epoch_of


def _with_newline(line: str) -> str:
    return line if line.endswith('\n') else line + '\n'


def compact_jsonl_lines(
    lines: Sequence[str],
    *,
    epoch_of: EpochOf,
    cutoff_epoch: float | None,
    max_bytes: int,
) -> list[str]:
    """Return the lines to keep: drop invalid and too-old lines, then the oldest over the cap.

    Pure. Lines are in file (append) order, oldest first, and the result keeps that order.
    Every returned line ends with a newline.

    Args:
        lines: File lines.
        epoch_of: A line's epoch, or None for an invalid line.
        cutoff_epoch: Lines with an epoch before this are dropped; None keeps every age.
        max_bytes: Drop the oldest lines until the total UTF-8 size is at most this.

    Returns:
        The kept lines.
    """
    kept = [
        _with_newline(line)
        for line in lines
        if (epoch := epoch_of(line)) is not None
        and (cutoff_epoch is None or epoch >= cutoff_epoch)
    ]
    sizes = [len(line.encode('utf-8')) for line in kept]
    total, start = sum(sizes), 0
    while total > max_bytes and start < len(kept):
        total -= sizes[start]
        start += 1
    return kept[start:]


def _write_atomically(path: Path, lines: list[str], file_mode: int | None = None) -> None:
    """Replace ``path`` with ``lines`` through a temporary file (``mkstemp``: 0o600)."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp')
    try:
        if file_mode is not None:
            os.fchmod(fd, file_mode)
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
            tmp.writelines(lines)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _first_line(path: Path) -> str:
    with path.open('r', encoding='utf-8', errors='replace') as file:
        return file.readline()


def _ends_with_newline(path: Path) -> bool:
    """True when ``path`` is missing, empty or ends with a newline.

    A torn last line (an interrupted writer) would otherwise swallow the next line
    appended after it.
    """
    if not path.exists() or path.stat().st_size == 0:
        return True
    with path.open('rb') as file:
        file.seek(-1, os.SEEK_END)
        return file.read(1) == b'\n'


def _loosened(st: os.stat_result, kind: str) -> bool:
    """Whether a private ``kind`` needs its mode set again: it has group or other bits.

    Raises:
        NotOwnedError: When another user owns it, so its mode is not this process's to set.
    """
    if st.st_uid != os.geteuid():
        raise NotOwnedError(f'the {kind} is owned by another user')
    return bool(stat.S_IMODE(st.st_mode) & _GROUP_OTHER_BITS)


def _ensure_parent(parent: Path, dir_mode: int | None, enforce: bool = False) -> None:
    if dir_mode is not None and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True, mode=dir_mode)
        os.chmod(parent, dir_mode)  # mkdir's mode is masked by the umask
    else:
        parent.mkdir(parents=True, exist_ok=True)
    if enforce and dir_mode is not None and _loosened(os.stat(parent), 'directory'):
        os.chmod(parent, dir_mode)


def _open_for_append(
    path: Path, file_mode: int | None, enforce: bool = False, kind: str = 'file'
) -> int:
    existed = path.exists()
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if enforce:
        flags |= os.O_NOFOLLOW  # a symbolic link in the file's place fails (ELOOP)
    fd = os.open(path, flags, 0o666 if file_mode is None else file_mode)
    try:
        if file_mode is not None and not existed:
            os.fchmod(fd, file_mode)  # the umask masks os.open's mode too
        # The open file itself is checked (fstat), so a swap after the check can't escape it.
        if enforce and file_mode is not None and _loosened(os.fstat(fd), kind):
            os.fchmod(fd, file_mode)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _lock_exclusively(fd: int, timeout_s: float | None) -> None:
    """Take ``LOCK_EX`` on ``fd``: wait as long as it takes, or at most ``timeout_s``.

    Raises:
        LockTimeoutError: The lock was still held when ``timeout_s`` ran out.
    """
    if timeout_s is None:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if not remaining > 0:
                raise LockTimeoutError(
                    f'the lock was held for more than {timeout_s:g} s'
                ) from None
            time.sleep(min(_LOCK_RETRY_S, remaining))


def append_capped_jsonl(
    path: Path,
    lines: Sequence[str],
    *,
    max_bytes: int,
    epoch_of: EpochOf,
    cutoff_epoch: float | None = None,
    age_grace_s: float = 0.0,
    dedup_key: Callable[[str], str | None] | None = None,
    file_mode: int | None = None,
    dir_mode: int | None = None,
    enforce_modes: bool = False,
    lock_timeout_s: float | None = None,
) -> CappedWriteResult:
    """Append ``lines`` to ``path`` under its lock, then enforce the size and age caps.

    Creates the directory (with ``dir_mode`` when it is missing and a mode is given; an
    existing directory keeps its mode), holds an exclusive ``flock`` on ``<file>.lock`` (a
    new lock file gets ``file_mode`` when it is given) for the whole append-and-compact,
    waiting at most ``lock_timeout_s`` for it when that is given, prefixes a newline when
    the last line is torn, drops incoming lines whose ``dedup_key`` is already in the file
    (the file is read only when a ``dedup_key`` is given), and appends (creating the file
    with ``file_mode`` when given). It then rewrites the file (temporary file plus
    ``os.replace``) only when the file is larger than ``max_bytes``, its first line is
    invalid, or, with ``cutoff_epoch``, its oldest line is more than ``age_grace_s`` older
    than the cutoff. A rewrite keeps the valid lines at or after the cutoff, then drops the
    oldest down to :data:`COMPACT_LOW_WATER_RATIO` of ``max_bytes``; its temporary file is
    0o600, or the stricter of ``file_mode`` and the file's current mode when a mode is
    given, so compaction never loosens a file. With ``enforce_modes``, the modes also hold
    for an existing directory, file and lock file, on every append, and neither the file nor
    its lock is opened through a symbolic link.

    Args:
        path: The JSON Lines file.
        lines: The lines to append, oldest first (a missing newline is added).
        max_bytes: Size cap in bytes (at least 1).
        epoch_of: A line's epoch, or None for an invalid line.
        cutoff_epoch: Drop lines older than this when compacting; None keeps every age.
        age_grace_s: How far past the cutoff the oldest line may be before an age rewrite.
        dedup_key: A line's identity, or None for a line that is never a duplicate.
        file_mode: Mode for a newly created file and lock file; a compacted file keeps the
            stricter of this and its current mode.
        dir_mode: Mode for a newly created directory.
        enforce_modes: Also on every append, before a line is written: an existing
            directory, lock file or file of the current user's with any group or other bit
            is set to ``dir_mode`` or ``file_mode``, and one owned by another user is
            refused; each only when its mode is given (the MCP call log gives none for an
            existing directory the user named). The lock file and the file are opened
            without following a symbolic link (``O_NOFOLLOW``), so a link in the place of
            either is refused.
        lock_timeout_s: None waits for the lock as long as it takes (the histories); a
            number of seconds is the longest wait, after which nothing is appended.

    Returns:
        What was written and what compaction removed.

    Raises:
        ValueError: ``max_bytes`` is below 1.
        LockTimeoutError: With ``lock_timeout_s``, another descriptor held the lock for
            longer; nothing is appended.
        NotOwnedError: With ``enforce_modes``, the file or its lock file, or the directory
            when ``dir_mode`` is given, is owned by another user; nothing is appended.
        OSError: The file or its directory cannot be written, or, with ``enforce_modes``,
            the file or its lock file is a symbolic link (``ELOOP``).
    """
    if max_bytes < 1:
        raise ValueError(f'max_bytes must be at least 1, got {max_bytes}')
    _ensure_parent(path.parent, dir_mode, enforce_modes)
    incoming = [_with_newline(line) for line in lines]
    result = CappedWriteResult(path=str(path), lines_written=0)
    lock_path = path.with_name(path.name + '.lock')
    lock_fd = _open_for_append(lock_path, file_mode, enforce_modes, 'lock file')
    with os.fdopen(lock_fd, 'ab') as lock:
        _lock_exclusively(lock.fileno(), lock_timeout_s)
        try:
            if dedup_key is not None:
                seen: set[str] = set()
                if path.exists():
                    with path.open('r', encoding='utf-8', errors='replace') as file:
                        seen = {key for line in file if (key := dedup_key(line)) is not None}
                fresh: list[str] = []
                for line in incoming:
                    key = dedup_key(line)
                    if key is not None and key in seen:
                        result.skipped_duplicates += 1
                        continue
                    if key is not None:
                        seen.add(key)
                    fresh.append(line)
                incoming = fresh
            prefix = '' if _ends_with_newline(path) else '\n'
            fd = _open_for_append(path, file_mode, enforce_modes)
            with os.fdopen(fd, 'a', encoding='utf-8') as out:
                out.write(prefix)
                out.writelines(incoming)
            result.lines_written = len(incoming)
            stat_result = path.stat()
            size, size_mode = stat_result.st_size, stat_result.st_mode
            oldest = epoch_of(_first_line(path))
            age_due = (
                cutoff_epoch is not None
                and oldest is not None
                and oldest < cutoff_epoch - age_grace_s
            )
            if size > max_bytes or oldest is None or age_due:
                existing = path.read_text(encoding='utf-8', errors='replace').splitlines(True)
                parsed = [(line, epoch_of(line)) for line in existing]
                valid = [line for line, epoch in parsed if epoch is not None]
                in_age = [
                    line
                    for line, epoch in parsed
                    if epoch is not None and (cutoff_epoch is None or epoch >= cutoff_epoch)
                ]
                low_water = max(1, int(max_bytes * COMPACT_LOW_WATER_RATIO))
                kept = compact_jsonl_lines(
                    existing, epoch_of=epoch_of, cutoff_epoch=cutoff_epoch, max_bytes=low_water
                )
                result.dropped_invalid = len(existing) - len(valid)
                result.dropped_by_age = len(valid) - len(in_age)
                result.dropped_by_size = len(in_age) - len(kept)
                if len(kept) != len(existing):
                    # The stricter of the file's current mode and file_mode: never looser.
                    mode = None if file_mode is None else file_mode & stat.S_IMODE(size_mode)
                    _write_atomically(path, kept, mode)
                    result.compacted = True
                result.lines_kept = len(kept)
            result.bytes = path.stat().st_size
            result.earliest_epoch = epoch_of(_first_line(path)) if result.bytes else None
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return result
