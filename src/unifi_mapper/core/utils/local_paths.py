"""Checks for local file arguments the MCP tools accept (issue 078).

The snapshot-and-compare tools read a JSON baseline or history the CLI wrote. The path is
checked the way :func:`unifi_mapper.backup.verify.check_backup_path` checks a backup: the
suffix on the argument before any filesystem call (so the check cannot probe other paths),
then absolute, then resolved (a symlink names its target, which must be ``.json`` too), and
an existing file must be a regular file under :data:`MAX_SNAPSHOT_BYTES`. A missing file is
returned resolved, so the caller reports it with its own hint on how to create one.
"""

from __future__ import annotations

import os
from pathlib import Path
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


SNAPSHOT_SUFFIX = '.json'
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024  # the baselines are kilobytes; this bounds a wrong path


def _invalid(what: str, message: str) -> ToolError:
    return ToolError(
        message=message,
        error_code=ErrorCodes.CONFIG_INVALID,
        suggestion=f'Give the absolute path of the {what} .json file the CLI wrote.',
    )


def check_snapshot_path(path: str | os.PathLike[str], *, what: str) -> Path:
    """Check a baseline or history path in the safe order and return it, resolved.

    Args:
        path: The argument as given.
        what: What the file is, for messages (``baseline``, ``history``).

    Returns:
        The resolved path; it may not exist yet (the caller reports that).

    Raises:
        ToolError: ``CONFIG_INVALID`` for a wrong suffix, a relative path, a non-regular file
            or a file over the size cap.
    """
    candidate = Path(path)
    if candidate.suffix.lower() != SNAPSHOT_SUFFIX:
        raise _invalid(what, f'the {what} must be a {SNAPSHOT_SUFFIX} file')
    if not candidate.is_absolute():
        raise _invalid(what, f'the {what} path must be absolute')
    resolved = candidate.resolve()
    if resolved.suffix.lower() != SNAPSHOT_SUFFIX:
        raise _invalid(what, f'the {what} must be a {SNAPSHOT_SUFFIX} file')
    try:
        info = resolved.stat()
    except FileNotFoundError:
        return resolved
    except OSError as e:
        raise _invalid(what, f'cannot read {resolved}: {e.strerror or type(e).__name__}') from None
    if not os.path.isfile(resolved):
        raise _invalid(what, f'{resolved} is not a regular file')
    if info.st_size > MAX_SNAPSHOT_BYTES:
        raise _invalid(
            what, f'{resolved} is larger than {MAX_SNAPSHOT_BYTES // (1024 * 1024)} MiB'
        )
    return resolved
