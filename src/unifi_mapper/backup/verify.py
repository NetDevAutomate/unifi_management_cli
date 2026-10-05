"""Verify a UniFi config backup (``.unf``) offline: structure only, never its contents.

``verify_backup_bytes`` runs the POC decryptor's stages (``backup/poc_decrypt.py``: decrypt,
extract ``db.gz``, decompress, walk the BSON documents) and reports whether each stage worked
and how many documents each collection holds. The extracted ``db.gz`` member and the
decompressed database are each capped at 1 GiB: an oversized member is refused by its
declared size before any of it is inflated, so a small crafted file can't exhaust memory.
Documents are counted as they are decoded and none is kept, so the result never carries a
setting, a password hash or any other value from the backup. Expected failures (a foreign
or corrupt file) are a result with ``valid: false`` and an ``errors`` list naming the stage
and the exception class, never bytes or messages.

The backup is read from a local path only: no controller is contacted and this module
imports no client (``credentials: none``). The path is checked before the file is opened:
the ``.unf`` suffix first, so no other file can be probed, then that it is absolute, a
regular file and at most 512 MiB.
"""

import asyncio
import os
import stat
from pathlib import Path
from pydantic import Field
from typing import Annotated, Any
from unifi_mapper.backup import poc_decrypt
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


MAX_BACKUP_BYTES = 512 * 1024 * 1024  # the .unf file itself
MAX_DB_BYTES = 1024 * 1024 * 1024  # the decompressed database
BACKUP_SUFFIX = '.unf'
# Collections whose presence shows the backup carries the network configuration.
KEY_SECTIONS = ('device', 'networkconf', 'wlanconf', 'setting')


def _error(stage: str, error: BaseException | str) -> dict[str, str]:
    name = error if isinstance(error, str) else type(error).__name__
    return {'stage': stage, 'error': name}


def _version_of(doc: dict[str, Any]) -> str | None:
    version = doc.get('version') or doc.get('mgmt_cfgVersion')
    return version if isinstance(version, str) and version else None


def verify_backup_bytes(data: bytes, *, max_db_bytes: int = MAX_DB_BYTES) -> dict[str, Any]:
    """Report whether a backup's bytes decrypt, extract, decompress and parse.

    Pure: no I/O and no printing. Each stage's input is released before the next runs
    (the caller's own reference to ``data`` excepted; :func:`verify_backup_file` keeps
    none).

    Args:
        data: The ``.unf`` file's bytes.
        max_db_bytes: Cap on the extracted ``db.gz`` member and on the decompressed
            database; past it the result is ``too_large`` at that stage.

    Returns:
        ``valid`` (every stage worked and at least one document decoded), ``format``
        (``bson`` when valid), ``version`` (the controller version a ``setting`` document
        names, or None), ``collections`` (name to document count), ``key_sections_present``
        (each of :data:`KEY_SECTIONS` to bool), ``bson_parse_errors`` (a count) and
        ``errors`` (``{stage, error}`` entries).
    """
    return _verify([data], max_db_bytes)


def _verify(buffer: list[bytes], max_db_bytes: int) -> dict[str, Any]:
    """Run the stages over the one item of ``buffer``, which it removes (see above)."""
    data = buffer.pop()
    result: dict[str, Any] = {
        'valid': False,
        'format': None,
        'version': None,
        'collections': {},
        'key_sections_present': dict.fromkeys(KEY_SECTIONS, False),
        'bson_parse_errors': 0,
        'errors': [],
    }
    stage = 'decrypt'
    try:
        payload = poc_decrypt.decrypt_backup(data)
        del data
        stage = 'extract'
        payload = poc_decrypt.extract_db_gz(payload, max_db_bytes)
        stage = 'decompress'
        payload = poc_decrypt.decompress_db(payload, max_db_bytes)
    except poc_decrypt.DatabaseTooLargeError:
        result['errors'].append(_error(stage, 'too_large'))
        return result
    except poc_decrypt.BackupDecryptError as e:
        result['errors'].append(_error(stage, e))
        return result
    if not payload:
        result['errors'].append(_error('decompress', 'empty'))
        return result

    counts: dict[str, int] = {}
    parse_errors: list[tuple[int, str]] = []
    for doc in poc_decrypt.iter_bson_documents(payload, parse_errors):
        name = str(poc_decrypt.collection_name(doc))
        counts[name] = counts.get(name, 0) + 1
        if name == 'setting' and result['version'] is None:
            result['version'] = _version_of(doc)
    result['bson_parse_errors'] = len(parse_errors)
    if not counts:
        result['errors'].append(_error('parse', 'no_documents'))
        return result
    result.update(
        valid=True,
        format='bson',
        collections=dict(sorted(counts.items())),
        key_sections_present={name: counts.get(name, 0) > 0 for name in KEY_SECTIONS},
    )
    return result


def _invalid(message: str) -> ToolError:
    return ToolError(
        message=message,
        error_code=ErrorCodes.CONFIG_INVALID,
        suggestion='Give the absolute path of a .unf backup downloaded from UniFi Network.',
    )


def check_backup_path(path: str | os.PathLike[str], *, require_absolute: bool = True) -> Path:
    """Check a backup path in the safe order and return it.

    The suffix is checked on the argument before any filesystem call, so the check can't be
    used to probe other paths; then the path must be absolute (when required), exist, be a
    regular file (no FIFO or device) and be at most :data:`MAX_BACKUP_BYTES`.

    Args:
        path: The backup's path.
        require_absolute: Refuse a relative path (the MCP tool); the CLI resolves its
            argument first.

    Returns:
        The path.

    Raises:
        ToolError: ``CONFIG_INVALID`` for the suffix, a relative path, a non-regular file or
            a file that is too large; ``BACKUP_NOT_FOUND`` for a missing ``.unf`` file.
    """
    candidate = Path(path)
    if candidate.suffix.lower() != BACKUP_SUFFIX:
        raise _invalid('the backup must be a .unf file')
    if require_absolute and not candidate.is_absolute():
        raise _invalid('the backup path must be absolute')
    try:
        info = candidate.stat()
    except FileNotFoundError:
        raise ToolError(
            message=f'backup not found: {candidate}',
            error_code=ErrorCodes.BACKUP_NOT_FOUND,
            suggestion='Check the path of the downloaded .unf backup.',
        ) from None
    except OSError as e:
        raise _invalid(f'cannot read {candidate}: {e.strerror or type(e).__name__}') from None
    if not stat.S_ISREG(info.st_mode):
        raise _invalid(f'{candidate} is not a regular file')
    if info.st_size > MAX_BACKUP_BYTES:
        raise _invalid(f'{candidate} is larger than {MAX_BACKUP_BYTES // (1024 * 1024)} MiB')
    return candidate


def verify_backup_file(path: Path) -> dict[str, Any]:
    """Read a checked backup path and verify it; adds ``path`` and ``size_bytes``.

    The file's bytes are handed over, not kept, so they are freed once decrypted.
    """
    buffer = [path.read_bytes()]
    size = len(buffer[0])
    result = _verify(buffer, MAX_DB_BYTES)
    result.update(path=str(path), size_bytes=size)
    return result


async def verify_config_backup(
    path: Annotated[
        str,
        Field(
            description='Absolute path of a .unf backup file on this machine',
            min_length=1,
            max_length=4096,
        ),
    ],
) -> dict[str, Any]:
    """Check a downloaded UniFi config backup (.unf) offline. Read-only.

    When to use this tool:
    - Before relying on a backup for a restore: does it decrypt and hold the network,
      WLAN, device and setting collections?
    - After downloading a backup from UniFi Network, to confirm it is not truncated

    Decrypts the file with the controller's fixed backup key, extracts and decompresses the
    database (capped at 1 GiB) and counts the documents in each collection. Reports
    structure only, never a document's contents. Contacts no controller and needs no
    credentials. The path must be absolute, end in .unf and name a regular file of at most
    512 MiB.

    Args:
        path: The backup's absolute path.

    Returns:
        valid, format, version, collections, key_sections_present, bson_parse_errors,
        errors, path and size_bytes.

    Raises:
        ToolError: CONFIG_INVALID for a bad path, BACKUP_NOT_FOUND for a missing file.
    """
    checked = check_backup_path(path, require_absolute=True)
    return await asyncio.to_thread(verify_backup_file, checked)
