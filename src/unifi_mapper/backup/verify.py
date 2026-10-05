"""Verify a UniFi config backup (``.unf``) offline: structure only, never its contents.

``verify_backup_bytes`` runs the POC decryptor's stages (``backup/poc_decrypt.py``: decrypt,
extract ``db.gz``, decompress, walk the BSON documents) and reports whether each stage worked
and how many documents each collection holds. The extracted ``db.gz`` member and the
decompressed database are each capped at 1 GiB: an oversized member is refused by its
declared size before any of it is inflated, so a small crafted file can't exhaust memory.
The gzip stream is walked in bounded slices and at most :data:`MAX_GZIP_MEMBERS` members
are accepted, so a crafted stream of many empty members can't hold a CPU either.
The documents must parse cleanly: one that fails to decode, or bytes left after the last
whole document (a truncated download), make the backup invalid.
Documents are counted as they are decoded and none is kept, so the result never carries a
setting, a password hash or a document's contents. Two strings do come from the backup, and
each is checked first: the version only when it is a version number (``9.10.0``), else
``<unrecognised>``, and a collection name only when it is one of :data:`KNOWN_COLLECTIONS`;
every other document is counted under ``other``, so no name a document chose is echoed.
Expected failures (a foreign or corrupt file) are a result with ``valid: false`` and an
``errors`` list naming the stage and the exception class, never bytes or messages.

The backup is read from a local path only: no controller is contacted and this module
imports no client (``credentials: none``). The path is checked before the file is opened:
the ``.unf`` suffix first, so no other file can be probed, then that it is absolute; it is
then resolved (a symlink's target must end in ``.unf`` too) and must be a regular file of at
most 512 MiB. The file is opened once, without following a link or blocking, checked again
on the open descriptor, and never read past the size it reports (:func:`read_backup`).
"""

import asyncio
import os
import re
import stat
from pathlib import Path
from pydantic import Field
from typing import Annotated, Any
from unifi_mapper.backup import poc_decrypt
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


MAX_BACKUP_BYTES = 512 * 1024 * 1024  # the .unf file itself
MAX_DB_BYTES = 1024 * 1024 * 1024  # the decompressed database
MAX_GZIP_MEMBERS = 64  # gzip members in the database (a real backup's is one)
BACKUP_SUFFIX = '.unf'
# Collections whose presence shows the backup carries the network configuration.
KEY_SECTIONS = ('device', 'networkconf', 'wlanconf', 'setting')
# The UniFi Network application's collections that are reported by name; any other name a
# document carries (or none) is counted under OTHER_COLLECTION.
KNOWN_COLLECTIONS = frozenset(
    {
        *KEY_SECTIONS,
        'account',
        'admin',
        'alarm',
        'apgroup',
        'broadcastgroup',
        'channelplan',
        'dashboard',
        'dhcpoption',
        'dpiapp',
        'dpigroup',
        'dynamicdns',
        'event',
        'firewallgroup',
        'firewallrule',
        'heatmap',
        'heatmappoint',
        'hotspot2conf',
        'hotspotop',
        'hotspotpackage',
        'map',
        'mediafile',
        'payment',
        'portalfile',
        'portconf',
        'portforward',
        'privilege',
        'radiusprofile',
        'rogue',
        'rogueknown',
        'routing',
        'scheduletask',
        'site',
        'spatialrecord',
        'tag',
        'task',
        'user',
        'usergroup',
        'verification',
        'virtualdevice',
        'voucher',
        'wlangroup',
    }
)
OTHER_COLLECTION = 'other'
UNRECOGNISED_VERSION = '<unrecognised>'
_VERSION_NUMBER = re.compile(r'\d{1,5}(?:\.\d{1,5}){1,3}')


def _error(stage: str, error: BaseException | str) -> dict[str, str]:
    name = error if isinstance(error, str) else type(error).__name__
    return {'stage': stage, 'error': name}


def _version_of(doc: dict[str, Any]) -> str | None:
    """The setting's version when it is a version number, ``<unrecognised>`` when it isn't."""
    version = doc.get('version') or doc.get('mgmt_cfgVersion')
    if version is None or version == '':
        return None
    if isinstance(version, str) and _VERSION_NUMBER.fullmatch(version):
        return version
    return UNRECOGNISED_VERSION


def _reported_name(doc: dict[str, Any]) -> str:
    """A document's collection when it is a known one, else :data:`OTHER_COLLECTION`."""
    name = poc_decrypt.collection_name(doc)
    return name if isinstance(name, str) and name in KNOWN_COLLECTIONS else OTHER_COLLECTION


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
        ``valid`` (every stage worked, at least one document decoded and the stream parsed
        cleanly: no document failed to decode and no byte was left after the last one),
        ``format`` (``bson`` when valid), ``version`` (the version number a ``setting``
        document names, ``<unrecognised>`` when it names something else, or None),
        ``collections`` (each of :data:`KNOWN_COLLECTIONS` found, plus ``other``, to its
        document count),
        ``key_sections_present`` (each of :data:`KEY_SECTIONS` to bool),
        ``bson_parse_errors`` (0, or 1 when the walk stopped at a corrupt or truncated
        document: it stops at the first, so its cost stays linear) and ``errors``
        (``{stage, error}`` entries; a parse failure is ``corrupt_document`` or
        ``truncated``).
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
        payload = poc_decrypt.decompress_db(payload, max_db_bytes, MAX_GZIP_MEMBERS)
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
    version: str | None = None
    parse_errors: list[tuple[int, str]] = []
    for doc in poc_decrypt.iter_bson_documents(payload, parse_errors, strict=True):
        name = _reported_name(doc)
        counts[name] = counts.get(name, 0) + 1
        if name == 'setting' and version is None:
            version = _version_of(doc)
    del payload
    result['bson_parse_errors'] = len(parse_errors)
    if parse_errors:  # the strict walk stopped early: a backup that doesn't parse cleanly
        truncated = parse_errors[-1][1].startswith(poc_decrypt.BSON_TRUNCATED)
        result['errors'].append(_error('parse', 'truncated' if truncated else 'corrupt_document'))
        return result
    if not counts:
        result['errors'].append(_error('parse', 'no_documents'))
        return result
    result.update(
        valid=True,
        format='bson',
        version=version,
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
    """Check a backup path in the safe order and return it, resolved.

    The suffix is checked on the argument before any filesystem call, so the check can't be
    used to probe other paths; then the path must be absolute (when required). It is then
    resolved, and the resolved path (a symlink's target) must end in ``.unf`` too, exist, be
    a regular file (no FIFO or device) and be at most :data:`MAX_BACKUP_BYTES`.

    Args:
        path: The backup's path.
        require_absolute: Refuse a relative path (the MCP tool); the CLI resolves its
            argument first.

    Returns:
        The resolved path.

    Raises:
        ToolError: ``CONFIG_INVALID`` for the suffix, a relative path, a non-regular file or
            a file that is too large; ``BACKUP_NOT_FOUND`` for a missing ``.unf`` file.
    """
    candidate = Path(path)
    if candidate.suffix.lower() != BACKUP_SUFFIX:
        raise _invalid('the backup must be a .unf file')
    if require_absolute and not candidate.is_absolute():
        raise _invalid('the backup path must be absolute')
    candidate = candidate.resolve()  # a symlink names its target, which must be a .unf too
    if candidate.suffix.lower() != BACKUP_SUFFIX:
        raise _invalid('the backup must be a .unf file')
    try:
        info = candidate.stat()
    except FileNotFoundError:
        raise _not_found(candidate) from None
    except OSError as e:
        raise _invalid(f'cannot read {candidate}: {e.strerror or type(e).__name__}') from None
    _check_info(candidate, info)
    return candidate


def _not_found(path: Path) -> ToolError:
    return ToolError(
        message=f'backup not found: {path}',
        error_code=ErrorCodes.BACKUP_NOT_FOUND,
        suggestion='Check the path of the downloaded .unf backup.',
    )


def _check_info(path: Path, info: os.stat_result) -> None:
    """Refuse anything but a regular file of at most :data:`MAX_BACKUP_BYTES`."""
    if not stat.S_ISREG(info.st_mode):
        raise _invalid(f'{path} is not a regular file')
    if info.st_size > MAX_BACKUP_BYTES:
        raise _too_large(path)


def _too_large(path: Path) -> ToolError:
    return _invalid(f'{path} is larger than {MAX_BACKUP_BYTES // (1024 * 1024)} MiB')


def read_backup(path: Path) -> bytes:
    """Read a checked backup path through one descriptor, never past the size cap.

    The path is opened once, without following a symlink and without blocking (so a FIFO
    swapped in after :func:`check_backup_path` can't hang the read); the open file is
    checked again with ``fstat`` (a regular file of at most :data:`MAX_BACKUP_BYTES`), and
    at most one byte more than that size is read, so a file that grew after the check (a
    download still running) is refused rather than read past the cap.

    Raises:
        ToolError: ``CONFIG_INVALID`` for a link, a non-regular file, a file past the cap or
            one that changed while it was read; ``BACKUP_NOT_FOUND`` when the file is gone.
    """
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise _not_found(path) from None
    except OSError as e:
        raise _invalid(f'cannot read {path}: {e.strerror or type(e).__name__}') from None
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        _check_info(path, info)
        data = handle.read(info.st_size + 1)
    if len(data) > info.st_size:
        raise _invalid(f'{path} changed while it was read')
    return data


def verify_backup_file(path: Path) -> dict[str, Any]:
    """Read a checked backup path (:func:`read_backup`) and verify it.

    Adds ``path`` and ``size_bytes``. The file's bytes are handed over, not kept, so they are
    freed once decrypted.
    """
    buffer = [read_backup(path)]
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
    database (capped at 1 GiB and 64 gzip members) and counts the documents in each
    collection. Reports structure only, never a document's contents. Contacts no controller
    and needs no credentials. The path must be absolute, end in .unf and name a regular file
    of at most 512 MiB.

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
