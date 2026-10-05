"""Offline backup verification: the POC stages it runs, the path checks, the tool and the CLI.

Ported from the July work (a local archive, not in the repo) and adapted: every backup is
synthetic (``tests/backup/synthetic_unf.py``), the database is capped and decompressed by
``gzip.decompress``' rules, documents are counted, never kept, and the path is checked in a
safe order before the file is opened.
"""

import bson
import gzip
import inspect
import io
import json
import os
import pytest
import subprocess
import sys
import threading
import zipfile
import zlib
from collections.abc import Iterator
from loguru import logger
from pathlib import Path
from tests.backup.synthetic_unf import (
    COLLECTIONS,
    bson_stream,
    build_unf_bytes,
    encrypt_unf,
    zip_with,
)
from typer.testing import CliRunner
from typing import Any, cast
from unifi_mapper.backup import poc_decrypt, verify
from unifi_mapper.backup.poc_decrypt import (
    DatabaseTooLargeError,
    ExtractionError,
    decompress_db,
    extract_db_gz,
    parse_bson_documents,
)
from unifi_mapper.backup.verify import (
    check_backup_path,
    verify_backup_bytes,
    verify_config_backup,
)
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.typer_cli import app


runner = CliRunner()
MIB = 1024 * 1024


def _gz(payload: bytes) -> bytes:
    return gzip.compress(payload, mtime=0)


# --- verify_backup_bytes -------------------------------------------------------------------


def test_a_valid_backup_reports_counts_sections_and_version() -> None:
    result = verify_backup_bytes(build_unf_bytes())
    assert result['valid'] is True and result['format'] == 'bson'
    assert result['collections'] == {
        'device': 1,
        'networkconf': 1,
        'setting': 1,
        'usergroup': 1,
        'wlanconf': 1,
    }
    assert all(result['key_sections_present'].values())
    assert result['version'] == '9.10.0'
    assert (result['bson_parse_errors'], result['errors']) == (0, [])


def test_the_result_holds_no_document_content() -> None:
    dumped = json.dumps(verify_backup_bytes(build_unf_bytes()))
    for value in ('Switch A', '02:00:00:00:00:01', 'SSID A', 'VLAN 10', 'dev1'):
        assert value not in dumped


FAKE_SECRET = 'x_passphrase=FAKE-PASSPHRASE-MUST-NOT-APPEAR'  # pragma: allowlist secret


@pytest.mark.parametrize(
    ('value', 'reported'),
    [
        ('9.10.0', '9.10.0'),
        ('9.10.0.1234', '9.10.0.1234'),  # four parts, and not an IPv4 address
        (FAKE_SECRET, '<unrecognised>'),
        ('9.10.0 ' + FAKE_SECRET, '<unrecognised>'),
        ('123456.0', '<unrecognised>'),
        ('9', '<unrecognised>'),
    ],
    ids=['three parts', 'four parts', 'secret', 'secret after a version', 'long part', 'one part'],
)
def test_only_a_version_number_is_reported(value: str, reported: str) -> None:
    setting = [{'_id': 'set1', 'key': 'super', 'version': value}]
    result = verify_backup_bytes(build_unf_bytes({**COLLECTIONS, 'setting': setting}))
    assert result['valid'] is True and result['version'] == reported
    assert 'FAKE-PASSPHRASE' not in json.dumps(result)


def test_only_known_collection_names_are_reported() -> None:
    collections = {
        **COLLECTIONS,
        FAKE_SECRET: [{'_id': 'x1'}],
        'mystery': [{'_id': 'm1'}, {'_id': 'm2'}],
    }
    stream = bson_stream(collections) + bson.encode({'_id': 'no-type'})
    result = verify_backup_bytes(build_unf_bytes(db_gz=_gz(stream)))
    assert result['valid'] is True
    assert result['collections'] == {
        'device': 1,
        'networkconf': 1,
        'other': 4,  # the secret-looking name, 'mystery' twice and the untyped document
        'setting': 1,
        'usergroup': 1,
        'wlanconf': 1,
    }
    dumped = json.dumps(result)
    assert 'FAKE-PASSPHRASE' not in dumped and 'mystery' not in dumped
    assert {'device', 'networkconf', 'setting', 'wlanconf'} <= verify.KNOWN_COLLECTIONS


def test_a_missing_section_is_flagged_but_still_valid() -> None:
    collections = {k: v for k, v in COLLECTIONS.items() if k != 'wlanconf'}
    result = verify_backup_bytes(build_unf_bytes(collections))
    assert result['valid'] is True
    assert result['key_sections_present']['wlanconf'] is False
    assert 'wlanconf' not in result['collections']


@pytest.mark.parametrize(
    ('data', 'stage'),
    [
        (b'not a valid backup at all', 'decrypt'),  # not a multiple of the block size
        (b'\x01' * 32, 'extract'),  # decrypts to something that isn't a zip
        (encrypt_unf(zip_with('unrelated.txt', b'hello')), 'extract'),
        (b'', 'extract'),  # decrypts to nothing, which isn't a zip
    ],
)
def test_a_foreign_file_is_a_result_naming_the_stage(data: bytes, stage: str) -> None:
    result = verify_backup_bytes(data)
    assert result['valid'] is False and result['collections'] == {}
    [error] = result['errors']
    assert error['stage'] == stage
    assert set(error) == {'stage', 'error'}  # a class name, never a message or bytes


@pytest.mark.parametrize('cut', ['truncated', 'flipped'])
def test_a_damaged_database_fails_at_decompress(cut: str) -> None:
    db_gz = bytearray(_gz(bson_stream(COLLECTIONS)))
    if cut == 'truncated':
        db_gz = db_gz[:-5]
    else:
        db_gz[len(db_gz) // 2] ^= 0xFF
    result = verify_backup_bytes(build_unf_bytes(db_gz=bytes(db_gz)))
    assert result['valid'] is False
    assert result['errors'] == [{'stage': 'decompress', 'error': 'ExtractionError'}]


def test_a_database_over_the_cap_is_too_large() -> None:
    db_gz = _gz(b'\x00' * (2 * MIB))  # small on disk, 2 MiB inflated
    result = verify_backup_bytes(build_unf_bytes(db_gz=db_gz), max_db_bytes=MIB)
    assert result['errors'] == [{'stage': 'decompress', 'error': 'too_large'}]
    assert verify.MAX_DB_BYTES == 1024 * MIB


def _deflated_zip(name: str, payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, payload)
    return buffer.getvalue()


def test_a_deflated_member_over_the_cap_is_refused_before_it_is_inflated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 4 MiB of zeros deflates to a few KiB: the member, not the file, is what is large.
    zip_data = _deflated_zip('db.gz', b'\x00' * (4 * MIB))
    assert len(zip_data) < 64 * 1024
    inflated: list[int] = []
    real_read = zipfile.ZipExtFile.read

    def _counting_read(self: zipfile.ZipExtFile, n: int | None = -1) -> bytes:
        data = real_read(self, n)
        inflated.append(len(data))
        return data

    monkeypatch.setattr(zipfile.ZipExtFile, 'read', _counting_read)
    result = verify_backup_bytes(encrypt_unf(zip_data), max_db_bytes=MIB)
    assert result['valid'] is False
    assert result['errors'] == [{'stage': 'extract', 'error': 'too_large'}]
    assert sum(inflated) == 0  # refused by the member's declared size, nothing inflated
    with pytest.raises(DatabaseTooLargeError):
        extract_db_gz(zip_data, max_bytes=MIB)
    assert len(extract_db_gz(zip_data)) == 4 * MIB  # no cap given: the POC is unchanged


def test_a_member_that_inflates_past_its_declared_size_is_refused() -> None:
    class _LyingZip:
        """A member whose header claims 1 byte but whose stream yields 2 MiB."""

        def getinfo(self, name: str) -> zipfile.ZipInfo:
            info = zipfile.ZipInfo(name)
            info.file_size = 1
            return info

        def open(self, info: zipfile.ZipInfo) -> io.BytesIO:
            return io.BytesIO(b'\x00' * (2 * MIB))

    lying = cast(zipfile.ZipFile, _LyingZip())
    with pytest.raises(DatabaseTooLargeError):
        poc_decrypt._read_member(lying, 'db.gz', MIB)
    assert poc_decrypt._read_member(lying, 'db.gz', None) == b'\x00' * (2 * MIB)


def test_an_empty_database_is_not_valid() -> None:
    result = verify_backup_bytes(build_unf_bytes(db_gz=_gz(b'')))
    assert result['errors'] == [{'stage': 'decompress', 'error': 'empty'}]


CORRUPT = b'\x05\x00\x00\x00\x7f'  # a 5-byte document whose terminator is not NUL
LAST = bson.encode({'_type': 'device', 'name': 'Switch B'})  # one more whole document


def test_a_corrupt_document_makes_the_backup_invalid() -> None:
    stream = bson_stream(COLLECTIONS) + CORRUPT + LAST
    result = verify_backup_bytes(build_unf_bytes(db_gz=_gz(stream)))
    assert result['valid'] is False and result['collections'] == {}
    assert result['bson_parse_errors'] == 1
    assert result['errors'] == [{'stage': 'parse', 'error': 'corrupt_document'}]


def test_only_corrupt_documents_is_not_valid() -> None:
    result = verify_backup_bytes(build_unf_bytes(db_gz=_gz(CORRUPT)))
    assert result['valid'] is False
    assert result['errors'] == [{'stage': 'parse', 'error': 'corrupt_document'}]


@pytest.mark.parametrize(
    'tail',
    [
        pytest.param(LAST[:-3], id='a document cut short'),
        pytest.param(b'\x01\x02', id='a fragment shorter than a size'),
        pytest.param(b'\x00' * 8, id='NUL bytes after the last document'),
    ],
)
def test_a_whole_document_followed_by_a_truncated_one_is_invalid(tail: bytes) -> None:
    result = verify_backup_bytes(build_unf_bytes(db_gz=_gz(bson_stream(COLLECTIONS) + tail)))
    assert result['valid'] is False and result['format'] is None
    assert result['bson_parse_errors'] == 1
    assert result['errors'] == [{'stage': 'parse', 'error': 'truncated'}]


def test_the_strict_walk_stops_at_the_first_failure_and_copies_no_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # At the bad byte the size reads 1285, which fails; one byte on, a valid empty document
    # starts. The POC's skip-one-byte recovery finds it; the verifier's strict walk stops.
    padded = bson.encode({'_type': 'device', 'note': 'x' * 1400})
    stream = bson_stream(COLLECTIONS) + b'\x05' + bson.encode({}) + padded
    decoded: list[object] = []
    real_decode = poc_decrypt.bson.decode

    def _spy(data: object) -> object:
        decoded.append(data)
        return real_decode(data)  # type: ignore[arg-type]

    monkeypatch.setattr(poc_decrypt.bson, 'decode', _spy)
    errors: list[tuple[int, str]] = []
    docs = list(poc_decrypt.iter_bson_documents(stream, errors, strict=True))
    assert len(docs) == len(COLLECTIONS) and len(decoded) == len(COLLECTIONS) + 1
    assert [offset for offset, _ in errors] == [len(bson_stream(COLLECTIONS))]
    assert all(isinstance(data, memoryview) for data in decoded)  # slices, never copies
    decoded.clear()
    recovered = list(poc_decrypt.iter_bson_documents(stream))  # the POC: recovery kept
    assert len(recovered) == len(COLLECTIONS) + 2 and len(decoded) == len(COLLECTIONS) + 3
    assert all(isinstance(data, memoryview) for data in decoded)


def test_the_strict_walk_names_leftover_bytes_as_truncated() -> None:
    errors: list[tuple[int, str]] = []
    good = bson_stream(COLLECTIONS)
    assert len(list(poc_decrypt.iter_bson_documents(good + b'\x01', errors, strict=True))) == 5
    [(offset, message)] = errors
    assert offset == len(good) and message.startswith(poc_decrypt.BSON_TRUNCATED)
    errors.clear()
    list(poc_decrypt.iter_bson_documents(good + b'\x01', errors))  # the POC: silent, as before
    assert errors == []


@pytest.fixture
def server_logging() -> Iterator[None]:
    """Log at WARNING to stderr, as the MCP server does by default; restore DEBUG after."""
    logger.remove()
    logger.add(lambda message: sys.stderr.write(message), level='WARNING', diagnose=False)
    yield
    logger.remove()
    logger.add(lambda message: sys.stderr.write(message), level='DEBUG', diagnose=False)


@pytest.mark.usefixtures('server_logging')
def test_verification_prints_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    verify_backup_bytes(build_unf_bytes())
    verify_backup_bytes(b'\x01' * 32)
    extract_db_gz(zip_with('db.gz', _gz(b'x')))
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ('', '')


# --- decompress_db by gzip.decompress' rules -------------------------------------------------


def _both(data: bytes) -> tuple[object, object]:
    """Return what gzip.decompress and decompress_db make of ``data`` (bytes or 'raises')."""
    try:
        expected: object = gzip.decompress(data)
    except (gzip.BadGzipFile, EOFError, zlib.error):
        expected = 'raises'
    try:
        got: object = decompress_db(data)
    except ExtractionError:
        got = 'raises'
    return expected, got


@pytest.mark.parametrize(
    'data',
    [
        pytest.param(b'', id='empty'),
        pytest.param(_gz(b'one') + _gz(b'two'), id='two members'),
        pytest.param(_gz(b'one') + b'\x00' * 7, id='trailing NULs'),
        pytest.param(_gz(b'one') + b'junk', id='trailing junk'),
        pytest.param(_gz(b'one')[:-3], id='truncated'),
        pytest.param(b'\x00\x00\x00', id='NUL only'),
        pytest.param(b'plain text', id='not gzip'),
        pytest.param(_gz(b'one') + b'\x00\x00' + _gz(b'two'), id='NULs between members'),
    ],
)
def test_decompress_db_matches_gzip_decompress(data: bytes) -> None:
    expected, got = _both(data)
    assert got == expected


def test_the_cap_counts_every_member() -> None:
    data = _gz(b'a' * (MIB // 2 + 1)) + _gz(b'b' * (MIB // 2 + 1))
    assert len(decompress_db(data)) == MIB + 2
    with pytest.raises(DatabaseTooLargeError):
        decompress_db(data, max_bytes=MIB)


EMPTY_MEMBER = _gz(b'')  # 20 bytes that inflate to nothing


class _SpyInflater:
    """A zlib decompressor that records the size of every input it is given."""

    def __init__(self, real: Any, sizes: list[int]) -> None:
        self._real, self._sizes = real, sizes

    def decompress(self, data: Any, max_length: int = 0) -> bytes:
        self._sizes.append(len(data))
        return self._real.decompress(data, max_length)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def test_many_members_feed_the_decompressor_bounded_slices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crafted stream of empty members costs linear work, never a copy of the rest."""
    sizes: list[int] = []
    real = zlib.decompressobj
    monkeypatch.setattr(zlib, 'decompressobj', lambda *args: _SpyInflater(real(*args), sizes))
    stream = EMPTY_MEMBER * 200_000
    assert decompress_db(stream) == b''
    assert len(sizes) >= 200_000
    assert max(sizes) <= poc_decrypt.FEED_STEP < len(stream)


def test_a_member_spanning_many_slices_inflates_whole() -> None:
    payload = os.urandom(3 * poc_decrypt.FEED_STEP)  # incompressible: a stored member
    data = _gz(payload) + b'\x00' * (2 * poc_decrypt.FEED_STEP) + _gz(b'tail')
    assert decompress_db(data) == payload + b'tail'


def test_the_verifier_refuses_more_gzip_members_than_its_cap() -> None:
    cap = verify.MAX_GZIP_MEMBERS
    first = _gz(bson_stream(COLLECTIONS))
    at_cap = verify_backup_bytes(build_unf_bytes(db_gz=first + EMPTY_MEMBER * (cap - 1)))
    assert at_cap['valid'] is True
    over = verify_backup_bytes(build_unf_bytes(db_gz=first + EMPTY_MEMBER * cap))
    assert over['valid'] is False
    assert over['errors'] == [{'stage': 'decompress', 'error': 'TooManyMembersError'}]
    with pytest.raises(poc_decrypt.TooManyMembersError):
        decompress_db(EMPTY_MEMBER * 3, max_members=2)
    assert decompress_db(EMPTY_MEMBER * 2, max_members=2) == b''


# --- the BSON walk ------------------------------------------------------------------------


def test_parse_bson_documents_keeps_today_s_result_and_reports_errors() -> None:
    good = bson_stream({'device': [{'_id': 'dev1'}], 'setting': [{'_id': 's1'}]})
    errors: list[tuple[int, str]] = []
    collections = parse_bson_documents(good + CORRUPT, errors)
    assert collections == {
        'device': [{'_id': 'dev1', '_type': 'device'}],
        'setting': [{'_id': 's1', '_type': 'setting'}],
    }
    assert [offset for offset, _ in errors] == [len(good)]  # the corrupt document's offset
    assert parse_bson_documents(good) == parse_bson_documents(good, [])


def test_the_poc_cli_still_prints_its_warnings_and_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = bson_stream(COLLECTIONS) + CORRUPT
    backup = tmp_path / 'synthetic.unf'
    backup.write_bytes(build_unf_bytes(db_gz=_gz(stream)))
    monkeypatch.setattr(sys, 'argv', ['poc_decrypt', str(backup), '--list-only'])
    poc_decrypt.main()
    out = capsys.readouterr().out
    assert f'Warning: BSON parse error at offset {len(bson_stream(COLLECTIONS))}' in out
    assert 'Parsed 5 BSON documents across 5 collections' in out
    assert 'ZIP contents' not in out  # a debug log line now


def test_the_poc_cli_redacts_an_unexpected_error_and_its_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = 'password=' + 'FAKE-POC-PASSWORD-MUST-NOT-APPEAR'  # pragma: allowlist secret

    def _boom(_data: bytes) -> bytes:
        raise RuntimeError(f'decrypt failed with {fake}')

    backup = tmp_path / 'synthetic.unf'
    backup.write_bytes(build_unf_bytes())
    monkeypatch.setattr(poc_decrypt, 'decrypt_backup', _boom)
    monkeypatch.setattr(sys, 'argv', ['poc_decrypt', str(backup)])
    with pytest.raises(SystemExit):
        poc_decrypt.main()
    captured = capsys.readouterr()
    assert 'UNEXPECTED ERROR' in captured.out and 'Traceback' in captured.err
    assert 'FAKE-POC-PASSWORD' not in captured.out + captured.err


def test_importing_without_a_dependency_raises_instead_of_exiting() -> None:
    code = (
        'import sys\n'
        "sys.modules['Crypto.Cipher'] = None\n"
        'try:\n'
        '    import unifi_mapper.backup.poc_decrypt\n'
        'except ImportError as e:\n'
        "    print('ImportError:', e)\n"
    )
    out = subprocess.run(
        [sys.executable, '-c', code], capture_output=True, text=True, timeout=60, check=True
    )
    assert out.stdout.startswith('ImportError:') and 'uv sync' in out.stdout


# --- the path checks ------------------------------------------------------------------------


@pytest.fixture
def backup(tmp_path: Path) -> Path:
    path = tmp_path / 'synthetic.unf'
    path.write_bytes(build_unf_bytes())
    return path


def test_the_suffix_is_checked_before_any_filesystem_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _no_stat(*_args: object, **_kwargs: object) -> None:
        raise AssertionError('stat was called before the suffix check')

    monkeypatch.setattr(Path, 'stat', _no_stat)
    for probe in ('/etc/passwd', '/dev/zero', 'relative.txt'):
        with pytest.raises(ToolError) as exc:
            check_backup_path(probe)
        assert exc.value.error_code == ErrorCodes.CONFIG_INVALID


def test_a_relative_path_is_refused_when_absolute_is_required() -> None:
    with pytest.raises(ToolError) as exc:
        check_backup_path('backups/synthetic.unf')
    assert exc.value.error_code == ErrorCodes.CONFIG_INVALID


def test_a_missing_backup_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(ToolError) as exc:
        check_backup_path(tmp_path / 'missing.unf')
    assert exc.value.error_code == ErrorCodes.BACKUP_NOT_FOUND


def test_a_fifo_or_a_directory_is_refused(tmp_path: Path) -> None:
    fifo = tmp_path / 'pipe.unf'
    os.mkfifo(fifo)
    folder = tmp_path / 'folder.unf'
    folder.mkdir()
    for path in (fifo, folder):
        with pytest.raises(ToolError) as exc:
            check_backup_path(path)
        assert exc.value.error_code == ErrorCodes.CONFIG_INVALID


def test_a_file_over_the_size_cap_is_refused(
    monkeypatch: pytest.MonkeyPatch, backup: Path
) -> None:
    monkeypatch.setattr(verify, 'MAX_BACKUP_BYTES', 10)
    with pytest.raises(ToolError) as exc:
        check_backup_path(backup)
    assert exc.value.error_code == ErrorCodes.CONFIG_INVALID


def test_a_symlink_is_resolved_and_its_target_s_suffix_checked(
    tmp_path: Path, backup: Path
) -> None:
    other = tmp_path / 'notes.txt'
    other.write_bytes(b'not a backup')
    to_other = tmp_path / 'to-notes.unf'
    to_other.symlink_to(other)
    with pytest.raises(ToolError) as exc:
        check_backup_path(to_other)
    assert exc.value.error_code == ErrorCodes.CONFIG_INVALID
    to_backup = tmp_path / 'to-backup.unf'
    to_backup.symlink_to(backup)
    assert check_backup_path(to_backup) == backup.resolve()


def _verify_or_error(path: Path) -> object:
    try:
        return verify.verify_backup_file(path)
    except ToolError as e:
        return e


def test_the_size_is_checked_again_on_the_open_file(
    monkeypatch: pytest.MonkeyPatch, backup: Path
) -> None:
    checked = check_backup_path(backup)
    monkeypatch.setattr(verify, 'MAX_BACKUP_BYTES', 10)  # the file grew after the check
    outcome = _verify_or_error(checked)
    assert isinstance(outcome, ToolError) and outcome.error_code == ErrorCodes.CONFIG_INVALID


def test_a_file_that_grows_after_fstat_is_refused(
    monkeypatch: pytest.MonkeyPatch, backup: Path
) -> None:
    checked = check_backup_path(backup)
    real_fstat = os.fstat
    sizes: list[int] = []

    class _Small:  # what fstat saw, before the download grew the file
        def __init__(self, info: os.stat_result) -> None:
            self.st_mode, self.st_size = info.st_mode, 0

    monkeypatch.setattr(verify.os, 'fstat', lambda fd: _Small(real_fstat(fd)))
    real_fdopen = os.fdopen

    class _SpyHandle:  # records how much each read asks for
        def __init__(self, real: Any) -> None:
            self._real = real

        def __enter__(self) -> '_SpyHandle':
            return self

        def __exit__(self, *exc: object) -> None:
            self._real.close()

        def fileno(self) -> int:
            return self._real.fileno()

        def read(self, size: int = -1) -> bytes:
            sizes.append(size)
            return self._real.read(size)

    monkeypatch.setattr(verify.os, 'fdopen', lambda fd, mode: _SpyHandle(real_fdopen(fd, mode)))
    outcome = _verify_or_error(checked)
    assert isinstance(outcome, ToolError) and outcome.error_code == ErrorCodes.CONFIG_INVALID
    assert sizes == [1]  # one byte past what fstat saw, never the whole file


def test_a_link_swapped_in_after_the_check_is_not_followed(tmp_path: Path, backup: Path) -> None:
    checked = check_backup_path(backup)
    elsewhere = tmp_path / 'elsewhere.bin'
    elsewhere.write_bytes(backup.read_bytes())
    backup.unlink()
    backup.symlink_to(elsewhere)
    outcome = _verify_or_error(checked)
    assert isinstance(outcome, ToolError) and outcome.error_code == ErrorCodes.CONFIG_INVALID


def test_a_fifo_swapped_in_after_the_check_is_refused_without_blocking(backup: Path) -> None:
    checked = check_backup_path(backup)
    backup.unlink()
    os.mkfifo(backup)
    outcome: list[object] = []
    worker = threading.Thread(target=lambda: outcome.append(_verify_or_error(checked)))
    worker.daemon = True
    worker.start()
    worker.join(5)
    if worker.is_alive():  # the read blocked on the FIFO: give it EOF, then fail
        os.close(os.open(backup, os.O_WRONLY | os.O_NONBLOCK))
        worker.join(5)
        pytest.fail('reading the backup blocked on a FIFO')
    assert isinstance(outcome[0], ToolError)
    assert outcome[0].error_code == ErrorCodes.CONFIG_INVALID


# --- the MCP tool -------------------------------------------------------------------------


async def test_the_tool_verifies_an_absolute_path(backup: Path) -> None:
    result = await verify_config_backup(str(backup))
    assert result['valid'] is True
    assert result['size_bytes'] == backup.stat().st_size and result['path'] == str(backup)
    assert inspect.iscoroutinefunction(verify_config_backup)


async def test_the_tool_refuses_a_relative_path(backup: Path) -> None:
    with pytest.raises(ToolError) as exc:
        await verify_config_backup(backup.name)  # the cwd is tmp_path, so it would exist
    assert exc.value.error_code == ErrorCodes.CONFIG_INVALID


def test_the_verifier_imports_no_controller_client() -> None:
    source = Path(verify.__file__).read_text(encoding='utf-8')
    for name in ('UniFiClient', 'UnifiApiClient', 'get_credentials', 'httpx'):
        assert name not in source


# --- backup verify ------------------------------------------------------------------------


def test_the_cli_resolves_a_relative_path_and_prints_json(backup: Path) -> None:
    result = runner.invoke(app, ['backup', 'verify', backup.name, '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data['valid'] is True and data['path'] == str(backup.resolve())


def test_the_cli_table_and_an_invalid_backup_exit_1(tmp_path: Path, backup: Path) -> None:
    table = runner.invoke(app, ['backup', 'verify', str(backup)])
    assert table.exit_code == 0, table.output
    assert 'valid' in table.stdout and 'networkconf' in table.stdout
    broken = tmp_path / 'broken.unf'
    broken.write_bytes(b'\x01' * 32)
    result = runner.invoke(app, ['backup', 'verify', str(broken)])
    assert result.exit_code == 1
    assert 'extract' in result.stderr


@pytest.mark.parametrize(
    ('name', 'code'), [('notes.txt', 2), ('missing.unf', 1)], ids=['not .unf', 'missing']
)
def test_cli_path_errors(name: str, code: int) -> None:
    result = runner.invoke(app, ['backup', 'verify', name])
    assert result.exit_code == code, result.output
    assert result.stdout == '' and result.stderr


def test_backup_verify_has_help() -> None:
    result = runner.invoke(app, ['backup', 'verify', '--help'])
    assert result.exit_code == 0
    assert 'Read-only' in ' '.join(result.output.split())


def test_bson_round_trips_the_synthetic_stream() -> None:
    # A guard on the helper itself: what it encodes is what the walk decodes.
    decoded = list(poc_decrypt.iter_bson_documents(bson_stream(COLLECTIONS)))
    assert [doc['_type'] for doc in decoded] == list(COLLECTIONS)
    assert bson.decode(bson.encode({'a': 1})) == {'a': 1}
