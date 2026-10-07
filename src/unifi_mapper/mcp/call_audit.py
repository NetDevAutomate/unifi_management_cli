"""The MCP server's call log: one capped JSON line per catalog tool call (issue 013 D5).

On by default. Each call through the runner (``execute_tool`` or the direct surface) writes
one line to ``$XDG_STATE_HOME/unifi_mapper/mcp-audit.jsonl`` (``state_dir()``, resolved at
each write, never relative to the working directory): the time, the registered tool's name,
the surface, the argument **keys** that are the tool's own parameter names (any other key is
only counted), the duration and the outcome code (``ok``, the error code, or ``CANCELLED``).
Argument values, results and messages are never written, and a tool name the registry
doesn't hold is client text, so it is written as ``<unregistered>`` with its length only.
The meta-tools (``search_tools``, ``get_tool_info``, ``list_categories``) aren't logged.

``UNIFI_MCP_CALL_AUDIT`` (read with the other ``UNIFI_MCP_*`` settings, never from the env
file): unset, empty, ``on``/``true``/``1``/``default`` is the default path; ``off``/
``false``/``0``/``none`` turns the log off; an absolute path (``~`` expanded) writes there;
anything else (a relative path) turns it off with one warning. With
``UNIFI_MCP_REQUEST_AUDIT=on``, the controller requests the read-only guards let through
(method and path) are written to the same file as ``request`` lines just before the call
line that follows them; they are buffered in memory (at most :data:`MAX_PENDING_REQUESTS`,
then one ``request_overflow`` line with the count), so the async transport never writes a
file. Request lines carry no call id: with concurrent calls they belong to a time window.

Writes go through ``core/utils/jsonl.append_capped_jsonl`` (a lock file, torn-line repair,
compaction to 80% of :data:`DEFAULT_MAX_BYTES`) with ``enforce_modes``: on every write the
file and its lock file (``<file>.lock``) are kept ``0o600``, so one of the user's with group
or other bits (made before, or by another tool) is set private again, and one owned by
another user, or a symbolic link in the place of either, is never written (the log turns
off, fail closed). The default directory, the tool's own, is kept ``0o700`` the same way. A
given path's directory is the user's and is never changed: one the log creates is made
``0o700``, and an existing one owned by another user, or with a group or other write bit,
turns the log off before anything (the file or its lock) is written.
The runner records in a worker thread inside a shielded cancel scope, so a contended lock
never blocks the event loop and a cancelled call is still logged. A write waits at most
:data:`LOCK_TIMEOUT_S` (5 s) for the lock, so a lock held elsewhere delays a tool's result
by at most that: the write's lines are dropped with one warning per process, and the log
stays on. Any other failure to write (an unwritable path, a read-only home, no ``HOME``,
another user's file, lock or directory, a symbolic link, a given directory others can write
to) logs one warning and turns the log off for the process; a tool's result is never
affected.
"""

import errno
import json
import os
import stat
import threading
import time
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from loguru import logger
from pathlib import Path
from typing import Literal
from unifi_mapper.core.utils.jsonl import (
    LockTimeoutError,
    NotOwnedError,
    append_capped_jsonl,
    epoch_field,
)


CALL_AUDIT_ENV = 'UNIFI_MCP_CALL_AUDIT'
CALL_AUDIT_FILENAME = 'mcp-audit.jsonl'
DEFAULT_MAX_BYTES = 16 * 1024 * 1024
MAX_PENDING_REQUESTS = 1000
# The longest one write waits for the lock (seconds): well past what another writer's
# compaction of a full file takes. A write still locked out then drops its lines.
LOCK_TIMEOUT_S = 5.0
UNREGISTERED = '<unregistered>'
CANCELLED = 'CANCELLED'
# Backstops: keys are the tool's own parameter names, so these never bind in practice.
MAX_LOGGED_KEYS = 64
MAX_KEY_LENGTH = 64

_ON = frozenset({'on', 'true', '1'})
_OFF = frozenset({'off', 'false', '0', 'none'})
_EPOCH_OF = epoch_field('epoch')
# A given path's directory with either bit lets another user swap the file or its lock.
_GROUP_OTHER_WRITE = 0o022


class SharedDirectoryError(PermissionError):
    """A given call-log path's directory has a group or other write bit, so it isn't written."""


def default_call_audit_path() -> Path:
    """``state_dir() / CALL_AUDIT_FILENAME``, read at call time; nothing is created.

    Returns:
        The call log's default path under the XDG state directory.

    Raises:
        RuntimeError: When ``XDG_STATE_HOME`` is unset and there is no home directory.
    """
    # Imported here: the server's settings load before any tool, and the analysis package
    # is heavy to import.
    from unifi_mapper.analysis.port_counter_baseline import state_dir

    return state_dir() / CALL_AUDIT_FILENAME


def env_switch(raw: str | None) -> Literal['on', 'off'] | None:
    """Read an on/off environment value, any case, surrounding whitespace ignored.

    Shared by ``UNIFI_MCP_CALL_AUDIT`` and ``UNIFI_MCP_REQUEST_AUDIT`` so their families
    can't drift apart.

    Args:
        raw: The variable's value, or None when it is unset.

    Returns:
        ``'on'`` for ``on``/``true``/``1``, ``'off'`` for ``off``/``false``/``0``/``none``,
        else None (unset, empty or anything else).
    """
    if raw is None:
        return None
    value = raw.strip().casefold()
    if value in _ON:
        return 'on'
    if value in _OFF:
        return 'off'
    return None


@dataclass(frozen=True)
class CallAuditSetting:
    """Where the call log goes: the default path, nowhere, or a given absolute path."""

    mode: Literal['default', 'off', 'path']
    path: Path | None = None

    def describe(self) -> str:
        """The path written (the default resolved now) as a string, or ``'off'``."""
        if self.mode == 'off':
            return 'off'
        return str(self.path if self.mode == 'path' else default_call_audit_path())


def parse_call_audit(raw: str | None, warn: Callable[[str], None]) -> CallAuditSetting:
    """Parse ``UNIFI_MCP_CALL_AUDIT``.

    Args:
        raw: The variable's value, or None when it is unset.
        warn: Receives one message when the value is refused.

    Returns:
        The setting: unset, empty, the ``on`` family or ``default`` is the default path; the
        ``off`` family is off; an absolute path (``~`` expanded) is that path; anything else
        is off, warned.
    """
    if raw is None or not raw.strip() or raw.strip().casefold() == 'default':
        return CallAuditSetting('default')
    switch = env_switch(raw)
    if switch is not None:
        return CallAuditSetting('default' if switch == 'on' else 'off')
    try:
        path = Path(raw.strip()).expanduser()
    except RuntimeError:  # ~ with no home directory
        path = None
    if path is not None and path.is_absolute():
        return CallAuditSetting('path', path)
    warn(f'{CALL_AUDIT_ENV} must be on, off or an absolute path; the MCP call log is off')
    return CallAuditSetting('off')


def _now() -> tuple[str, float]:
    """The UTC time in ISO form (milliseconds) and as Unix seconds."""
    epoch = time.time()
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec='milliseconds'), epoch


def _error_name(error: BaseException) -> str:
    """The exception class, with the errno name when it has one."""
    code = getattr(error, 'errno', None)
    name = errno.errorcode.get(code, '') if isinstance(code, int) else ''
    return f'{type(error).__name__} ({name})' if name else type(error).__name__


def _given_directory_exists(directory: Path) -> bool:
    """Check the directory of a path ``UNIFI_MCP_CALL_AUDIT`` gives; its mode is never changed.

    Args:
        directory: The given path's directory.

    Returns:
        Whether it exists; when it doesn't, the writer creates it ``0o700``.

    Raises:
        NotOwnedError: Another user owns it.
        SharedDirectoryError: It has a group or other write bit.
    """
    try:
        st = os.stat(directory)
    except FileNotFoundError:
        return False
    if st.st_uid != os.geteuid():
        raise NotOwnedError('the directory is owned by another user')
    if stat.S_IMODE(st.st_mode) & _GROUP_OTHER_WRITE:
        raise SharedDirectoryError('the directory has group or other write permission')
    return True


class CallAuditLog:
    """The process's call log: request lines buffered, call lines written at each call."""

    def __init__(self, setting: CallAuditSetting, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        """Create the log for ``setting``, capped at ``max_bytes``.

        Args:
            setting: Where to write (:func:`parse_call_audit`).
            max_bytes: The file's size cap; compaction trims it to 80% of this.
        """
        self.setting = setting
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._pending: list[str] = []
        self._dropped = 0
        self._disabled = setting.mode == 'off'
        self._lock_timeout_warned = False

    @property
    def enabled(self) -> bool:
        """Whether lines are still written (False when off, or after a failed write)."""
        return not self._disabled

    def target(self) -> Path | None:
        """The file to write now: the default resolved at call time, the given path, or None.

        Returns:
            The path the next line goes to, or None once the log is off or disabled.

        Raises:
            RuntimeError: For the default path when there is no home directory.
        """
        if self._disabled:
            return None
        if self.setting.mode == 'path':
            return self.setting.path
        return default_call_audit_path()

    def note_request(self, method: str, path: str) -> None:
        """Buffer one request line (the read-only guards' sink): no I/O, never raises."""
        if self._disabled:
            return
        stamp, epoch = _now()
        line = json.dumps(
            {'t': stamp, 'epoch': epoch, 'kind': 'request', 'method': method, 'path': path}
        )
        with self._lock:
            if len(self._pending) < MAX_PENDING_REQUESTS:
                self._pending.append(line)
            else:
                self._dropped += 1

    def _take_pending(self) -> list[str]:
        """The buffered request lines, plus one overflow line when some were dropped."""
        with self._lock:
            lines, self._pending = self._pending, []
            dropped, self._dropped = self._dropped, 0
        if dropped:
            stamp, epoch = _now()
            lines.append(
                json.dumps(
                    {'t': stamp, 'epoch': epoch, 'kind': 'request_overflow', 'dropped': dropped}
                )
            )
        return lines

    def record(
        self,
        *,
        tool: str,
        registered: bool,
        surface: str,
        arg_keys: Iterable[object],
        known_keys: Collection[str],
        duration_ms: float,
        outcome: str,
    ) -> None:
        """Write the buffered request lines, then one call line. Never raises.

        Args:
            tool: The name the client asked for.
            registered: Whether the registry holds that name; if not, the name is client
                text and is written as :data:`UNREGISTERED` with its length only.
            surface: ``execute_tool`` or ``direct``.
            arg_keys: The argument keys the client sent.
            known_keys: The registered tool's parameter names; only these keys are named,
                every other key is counted in ``unknown_keys``.
            duration_ms: How long the call took.
            outcome: ``ok``, the error code, or :data:`CANCELLED`.
        """
        if self._disabled:
            return
        keys = list(arg_keys)
        known = sorted(
            {
                k
                for k in keys
                if isinstance(k, str) and k in known_keys and len(k) <= MAX_KEY_LENGTH
            }
        )
        named = known[:MAX_LOGGED_KEYS]  # the cap bounds the line, not what counts as unknown
        stamp, epoch = _now()
        line: dict[str, object] = {
            't': stamp,
            'epoch': epoch,
            'kind': 'call',
            'pid': os.getpid(),
            'tool': tool if registered else UNREGISTERED,
        }
        if not registered:
            line['tool_name_length'] = len(tool)
        line |= {
            'surface': surface,
            'arg_keys': named,
            'unknown_keys': len(keys) - len(known),
            'duration_ms': round(duration_ms, 1),
            'outcome': outcome,
        }
        self._write([*self._take_pending(), json.dumps(line)])

    def flush(self) -> None:
        """Write any buffered request lines (the lifespan's exit). Never raises."""
        if self._disabled:
            return
        self._write(self._take_pending())

    def _write(self, lines: list[str]) -> None:
        if not lines or self._disabled:
            return
        target: Path | None = None
        try:
            target = self.target()
            if target is None:
                return
            # The default directory is the tool's own: kept 0o700 on every write. A given
            # path's existing directory is the user's: checked first, never changed.
            keep_dir = self.setting.mode == 'path' and _given_directory_exists(target.parent)
            append_capped_jsonl(
                target,
                lines,
                max_bytes=self.max_bytes,
                epoch_of=_EPOCH_OF,
                file_mode=0o600,
                dir_mode=None if keep_dir else 0o700,
                enforce_modes=True,
                lock_timeout_s=LOCK_TIMEOUT_S,
            )
        except LockTimeoutError:
            # Another descriptor holds the lock: these lines are dropped, the log stays on.
            with self._lock:
                first, self._lock_timeout_warned = not self._lock_timeout_warned, True
            if first:
                logger.warning(
                    'MCP call log: lines not written to {}: its lock was held for over {:g} s; '
                    'the log stays on (this warning is shown once)',
                    target,
                    LOCK_TIMEOUT_S,
                )
        except Exception as e:  # noqa: BLE001 - the call log must never affect a tool call
            self._disabled = True
            where = str(target) if target is not None else 'the default path'
            logger.warning(
                'MCP call log disabled for this process: cannot write {}: {}',
                where,
                str(e) if isinstance(e, NotOwnedError | SharedDirectoryError) else _error_name(e),
            )
