"""UniFi Backup Decrypt Proof-of-Concept.

This script decrypts UniFi backup files (.unf) and dumps their BSON contents
to help understand the backup structure before building the full feature.

Usage:
    python -m unifi_mapper.backup.poc_decrypt /path/to/backup.unf

Requirements:
    pycryptodome and pymongo (for ``bson``), both project dependencies: run ``uv sync``.

Its pure stages (``decrypt_backup``, ``extract_db_gz``, ``decompress_db``,
``iter_bson_documents``) are also what ``backup/verify.py`` runs, so importing this module
never prints or exits: a missing dependency raises ``ImportError``.

Based on: https://github.com/zhangyoufu/unifi-backup-decrypt
"""

import argparse
import io
import json
import sys
import zipfile
import zlib
from collections.abc import Iterator
from datetime import datetime
from loguru import logger
from pathlib import Path
from typing import Any, Dict, List, Optional


try:
    from Crypto.Cipher import AES
except ImportError as e:  # pragma: no cover - a project dependency
    raise ImportError('pycryptodome is not installed: run uv sync') from e

try:
    import bson
except ImportError as e:  # pragma: no cover - a project dependency
    raise ImportError('bson (from pymongo) is not installed: run uv sync') from e

GZIP_MAGIC = b'\x1f\x8b'
_INFLATE_STEP = 1024 * 1024  # bytes of output per decompress call


# UniFi backup encryption constants (well-known, hardcoded in UniFi controller)
UNIFI_AES_KEY = b'bcyangkmluohmars'  # 16 bytes for AES-128
UNIFI_AES_IV = b'ubntenterpriseap'  # 16 bytes IV


class BackupDecryptError(Exception):
    """Base exception for backup decryption errors."""

    pass


class DecryptionError(BackupDecryptError):
    """Failed to decrypt backup file."""

    pass


class ExtractionError(BackupDecryptError):
    """Failed to extract backup contents."""

    pass


class BSONParseError(BackupDecryptError):
    """Failed to parse BSON data."""

    pass


class DatabaseTooLargeError(ExtractionError):
    """The database member, or the decompressed database, passed the size cap it was given."""

    pass


def decrypt_backup(encrypted_data: bytes) -> bytes:
    """Decrypt UniFi backup data using AES-128-CBC.

    Args:
        encrypted_data: Raw encrypted bytes from .unf file

    Returns:
        Decrypted ZIP file bytes

    Raises:
        DecryptionError: If decryption fails
    """
    try:
        cipher = AES.new(UNIFI_AES_KEY, AES.MODE_CBC, UNIFI_AES_IV)
        decrypted = cipher.decrypt(encrypted_data)

        # Remove PKCS7 padding if present
        # Note: UniFi uses NoPadding, but some versions may have padding
        if decrypted and decrypted[-1] < 16:
            pad_len = decrypted[-1]
            if all(b == pad_len for b in decrypted[-pad_len:]):
                decrypted = decrypted[:-pad_len]

        return decrypted
    except Exception as e:
        raise DecryptionError(f'AES decryption failed: {e}')


def _read_member(zf: zipfile.ZipFile, name: str, max_bytes: Optional[int]) -> bytes:
    """Read one ZIP member, refusing it once it passes ``max_bytes`` (None: no cap).

    The member's declared size is checked first, so an oversized member is refused without
    inflating any of it; the read then runs in ``_INFLATE_STEP`` pieces and stops as soon as
    the output passes the cap, in case a reader yields more than its header declares.
    """
    info = zf.getinfo(name)
    if max_bytes is not None and info.file_size > max_bytes:
        raise DatabaseTooLargeError(f'ZIP member {name!r} is larger than {max_bytes} bytes')
    chunks: list[bytes] = []
    size = 0
    with zf.open(info) as member:
        while chunk := member.read(_INFLATE_STEP):
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise DatabaseTooLargeError(
                    f'ZIP member {name!r} is larger than {max_bytes} bytes'
                )
            chunks.append(chunk)
    return b''.join(chunks)


def extract_db_gz(zip_data: bytes, max_bytes: Optional[int] = None) -> bytes:
    """Extract db.gz from decrypted ZIP archive.

    Args:
        zip_data: Decrypted ZIP file bytes
        max_bytes: Refuse a database member larger than this many bytes, before it is
            inflated (None: no cap, as before).

    Returns:
        Contents of db.gz (still gzipped)

    Raises:
        DatabaseTooLargeError: The member passed ``max_bytes``.
        ExtractionError: If extraction fails
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data), 'r') as zf:
            # List contents for debugging (a log line, so --json output stays clean)
            file_list = zf.namelist()
            logger.debug('ZIP contents: {}', file_list)

            # Look for db.gz
            if 'db.gz' in file_list:
                return _read_member(zf, 'db.gz', max_bytes)

            # Try alternative names
            for name in file_list:
                if name.endswith('.gz') or name == 'db':
                    logger.debug('Using alternative: {}', name)
                    return _read_member(zf, name, max_bytes)

            raise ExtractionError(f'No database file found. Contents: {file_list}')

    except DatabaseTooLargeError:
        raise
    except zipfile.BadZipFile as e:
        raise ExtractionError(f'Invalid ZIP file: {e}')
    except Exception as e:
        raise ExtractionError(f'ZIP extraction failed: {e}')


def _inflate_member(data: bytes, out: bytearray, max_bytes: Optional[int]) -> bytes:
    """Inflate one gzip member onto ``out``; return the bytes after its trailer.

    ``zlib``'s gzip mode checks the member's CRC and length. Output is produced in
    ``_INFLATE_STEP`` pieces, so the cap is enforced before the whole member is in memory.
    """
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    pending = data
    try:
        while not inflater.eof:
            piece = inflater.decompress(pending, _INFLATE_STEP)
            out += piece
            if max_bytes is not None and len(out) > max_bytes:
                raise DatabaseTooLargeError(
                    f'Decompressed database is larger than {max_bytes} bytes'
                )
            pending = inflater.unconsumed_tail
            if not pending and len(piece) < _INFLATE_STEP:
                break  # input used up
    except zlib.error as e:
        raise ExtractionError(f'Invalid gzip data: {e}') from None
    if not inflater.eof:
        raise ExtractionError('Invalid gzip data: ended before the end-of-stream marker')
    return inflater.unused_data


def decompress_db(db_gz_data: bytes, max_bytes: Optional[int] = None) -> bytes:
    """Decompress the gzipped database, member by member, by ``gzip.decompress``' rules.

    Empty input is zero members (``b''``); input that doesn't start with the gzip magic is
    refused; after each member, NUL padding is skipped, and the rest must be another member.

    Args:
        db_gz_data: Gzipped BSON data.
        max_bytes: Stop once the output passes this many bytes (None: no cap, as before).

    Returns:
        Raw BSON data.

    Raises:
        DatabaseTooLargeError: The output passed ``max_bytes``.
        ExtractionError: Not gzip data, a truncated or corrupt member (``EOFError`` or
            ``zlib.error`` territory), or trailing bytes that aren't a member.
    """
    out = bytearray()
    data = bytes(db_gz_data)
    if not data:
        return b''
    if not data.startswith(GZIP_MAGIC):
        raise ExtractionError('Invalid gzip data: not a gzipped file')
    while True:
        rest = _inflate_member(data, out, max_bytes).lstrip(b'\x00')
        if not rest:
            return bytes(out)
        if not rest.startswith(GZIP_MAGIC):
            raise ExtractionError('Invalid gzip data: trailing bytes')
        data = rest


def iter_bson_documents(
    bson_data: bytes, errors: Optional[list[tuple[int, str]]] = None
) -> Iterator[Dict[str, Any]]:
    """Yield the documents of a stream of concatenated BSON documents, in order.

    Walks the stream by each document's 4-byte little-endian size. A document that fails to
    decode is skipped by one byte, as before, and recorded in ``errors`` (when given) as
    ``(offset, message)``; nothing is printed. The walk stops at a size that is too small or
    runs past the end.

    Args:
        bson_data: Raw BSON bytes.
        errors: A list to append each parse error to.

    Yields:
        Each decoded document.
    """
    offset = 0
    while offset + 4 <= len(bson_data):
        doc_size = int.from_bytes(bson_data[offset : offset + 4], 'little')
        if doc_size < 5 or offset + doc_size > len(bson_data):
            break
        try:
            doc = bson.decode(bson_data[offset : offset + doc_size])
        except Exception as e:  # noqa: BLE001 - one corrupt document must not end the walk
            if errors is not None:
                errors.append((offset, str(e)))
            offset += 1  # try to continue by searching for the next valid document
            continue
        yield doc
        offset += doc_size


def collection_name(doc: Dict[str, Any]) -> Any:
    """Return a document's collection: its ``_type`` (``'unknown'`` when absent)."""
    collection = doc.get('_type', 'unknown')
    try:
        hash(collection)
    except TypeError:
        collection = str(collection)
    return collection


def parse_bson_documents(
    bson_data: bytes, errors: Optional[list[tuple[int, str]]] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """Parse concatenated BSON documents into collections.

    UniFi backups contain multiple BSON documents concatenated together.
    Each document typically has a '_type' field indicating the collection.

    Args:
        bson_data: Raw BSON bytes
        errors: A list to append each parse error to, as ``(offset, message)``.

    Returns:
        Dictionary mapping collection names to lists of documents
    """
    collections: Dict[str, List[Dict[str, Any]]] = {}
    for doc in iter_bson_documents(bson_data, errors):
        collections.setdefault(collection_name(doc), []).append(doc)
    return collections


def json_serializer(obj: Any) -> Any:
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return f'<bytes:{len(obj)}>'
    if hasattr(obj, '__dict__'):
        return str(obj)
    return str(obj)


def dump_collections_summary(collections: Dict[str, List[Dict[str, Any]]]) -> None:
    """Print summary of all collections found."""
    print('\n' + '=' * 60)
    print('COLLECTIONS SUMMARY')
    print('=' * 60)

    # Sort by document count (most important first)
    sorted_collections = sorted(collections.items(), key=lambda x: len(x[1]), reverse=True)

    for name, docs in sorted_collections:
        print(f'\n  {name}: {len(docs)} document(s)')

        # Show sample fields from first document
        if docs:
            sample = docs[0]
            fields = list(sample.keys())[:10]
            print(f'    Fields: {", ".join(fields)}')
            if len(sample.keys()) > 10:
                print(f'    ... and {len(sample.keys()) - 10} more fields')


def dump_collection_detail(
    collections: Dict[str, List[Dict[str, Any]]],
    collection_name: str,
    max_docs: int = 3,
    output_file: Optional[Path] = None,
) -> None:
    """Dump detailed contents of a specific collection."""
    if collection_name not in collections:
        print(f"Collection '{collection_name}' not found")
        return

    docs = collections[collection_name]
    print(f'\n{"=" * 60}')
    print(f'COLLECTION: {collection_name} ({len(docs)} documents)')
    print('=' * 60)

    output_docs = docs[:max_docs]

    for i, doc in enumerate(output_docs):
        print(f'\n--- Document {i + 1}/{len(docs)} ---')
        try:
            formatted = json.dumps(doc, indent=2, default=json_serializer)
            # Truncate very long output
            if len(formatted) > 5000:
                formatted = formatted[:5000] + '\n... (truncated)'
            print(formatted)
        except Exception as e:
            print(f'Error formatting document: {e}')

    if output_file:
        with open(output_file, 'w') as f:
            json.dump(docs, f, indent=2, default=json_serializer)
        print(f'\nFull collection written to: {output_file}')


def main():
    """Run the backup decrypt proof-of-concept CLI."""
    parser = argparse.ArgumentParser(
        description='Decrypt and analyze UniFi backup files (.unf)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic decrypt and show summary
  python -m unifi_mapper.backup.poc_decrypt backup.unf

  # Show specific collection details
  python -m unifi_mapper.backup.poc_decrypt backup.unf -c setting

  # Export collection to JSON
  python -m unifi_mapper.backup.poc_decrypt backup.unf -c networkconf -o networks.json

  # Show all collections with full docs
  python -m unifi_mapper.backup.poc_decrypt backup.unf --all --max-docs 10
        """,
    )
    parser.add_argument('backup_file', type=Path, help='Path to .unf backup file')
    parser.add_argument(
        '-c',
        '--collection',
        type=str,
        action='append',
        help='Show details for specific collection(s). Can be repeated.',
    )
    parser.add_argument('--all', action='store_true', help='Show details for all collections')
    parser.add_argument(
        '--max-docs',
        type=int,
        default=3,
        help='Maximum documents to show per collection (default: 3)',
    )
    parser.add_argument('-o', '--output', type=Path, help='Output JSON file for collection export')
    parser.add_argument(
        '--list-only', action='store_true', help="Only list collections, don't show contents"
    )

    args = parser.parse_args()

    # Validate input file
    if not args.backup_file.exists():
        print(f'ERROR: File not found: {args.backup_file}')
        sys.exit(1)

    print(f'\n{"=" * 60}')
    print('UNIFI BACKUP DECRYPT POC')
    print('=' * 60)
    print(f'Input: {args.backup_file}')
    print(f'Size: {args.backup_file.stat().st_size:,} bytes')

    try:
        # Step 1: Read encrypted backup
        print('\n[1/4] Reading encrypted backup...')
        encrypted_data = args.backup_file.read_bytes()
        print(f'  Read {len(encrypted_data):,} bytes')

        # Step 2: Decrypt
        print('\n[2/4] Decrypting (AES-128-CBC)...')
        decrypted_data = decrypt_backup(encrypted_data)
        print(f'  Decrypted to {len(decrypted_data):,} bytes')

        # Quick validation - ZIP files start with PK
        if decrypted_data[:2] != b'PK':
            print("  WARNING: Decrypted data doesn't look like ZIP (no PK header)")
            print(f'  First bytes: {decrypted_data[:20].hex()}')
        else:
            print('  ✓ Valid ZIP header detected')

        # Step 3: Extract db.gz
        print('\n[3/4] Extracting database from ZIP...')
        db_gz_data = extract_db_gz(decrypted_data)
        print(f'  Extracted {len(db_gz_data):,} bytes (compressed)')

        # Decompress
        print('  Decompressing gzip...')
        bson_data = decompress_db(db_gz_data)
        print(f'  Decompressed to {len(bson_data):,} bytes')

        # Step 4: Parse BSON
        print('\n[4/4] Parsing BSON documents...')
        parse_errors: list[tuple[int, str]] = []
        collections = parse_bson_documents(bson_data, parse_errors)
        for offset, message in parse_errors:
            print(f'  Warning: BSON parse error at offset {offset}: {message}')
        doc_count = sum(len(docs) for docs in collections.values())
        print(f'  Parsed {doc_count} BSON documents across {len(collections)} collections')

        # Show results
        dump_collections_summary(collections)

        if args.list_only:
            print('\n✓ Decrypt successful! Use -c <collection> to see details.')
            return

        # Important collections for network config comparison
        important_collections = [
            'setting',
            'networkconf',
            'device',
            'usergroup',
            'firewallrule',
            'firewallgroup',
            'wlanconf',
            'portconf',
            'routing',
            'dhcpd',
        ]

        # Show requested collections
        collections_to_show = []

        if args.all:
            collections_to_show = list(collections.keys())
        elif args.collection:
            collections_to_show = args.collection
        else:
            # Default: show important collections that exist
            collections_to_show = [c for c in important_collections if c in collections]
            if not collections_to_show:
                # Fall back to first few collections
                collections_to_show = list(collections.keys())[:5]

        for coll_name in collections_to_show:
            output_file = args.output if len(collections_to_show) == 1 else None
            dump_collection_detail(
                collections, coll_name, max_docs=args.max_docs, output_file=output_file
            )

        print('\n' + '=' * 60)
        print('✓ DECRYPT SUCCESSFUL')
        print('=' * 60)
        print(f'Collections found: {len(collections)}')
        print(f'Total documents: {sum(len(d) for d in collections.values())}')

        # Suggestions
        print('\nKey collections for config comparison:')
        for coll in important_collections:
            if coll in collections:
                print(f'  ✓ {coll}: {len(collections[coll])} docs')
            else:
                print(f'  ✗ {coll}: not found')

    except BackupDecryptError as e:
        print(f'\n❌ ERROR: {e}')
        sys.exit(1)
    except Exception as e:
        print(f'\n❌ UNEXPECTED ERROR: {e}')
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
