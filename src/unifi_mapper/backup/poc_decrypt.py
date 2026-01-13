#!/usr/bin/env python3
"""
UniFi Backup Decrypt Proof-of-Concept

This script decrypts UniFi backup files (.unf) and dumps their BSON contents
to help understand the backup structure before building the full feature.

Usage:
    python -m unifi_mapper.backup.poc_decrypt /path/to/backup.unf

Requirements:
    pip install pycryptodome bson

Based on: https://github.com/zhangyoufu/unifi-backup-decrypt
"""
import argparse
import gzip
import io
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from Crypto.Cipher import AES
except ImportError:
    print("ERROR: pycryptodome not installed. Run: pip install pycryptodome")
    sys.exit(1)

try:
    import bson
except ImportError:
    print("ERROR: bson not installed. Run: pip install pymongo")
    sys.exit(1)


# UniFi backup encryption constants (well-known, hardcoded in UniFi controller)
UNIFI_AES_KEY = b"bcyangkmluohmars"  # 16 bytes for AES-128
UNIFI_AES_IV = b"ubntenterpriseap"   # 16 bytes IV


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


def decrypt_backup(encrypted_data: bytes) -> bytes:
    """
    Decrypt UniFi backup data using AES-128-CBC.

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
        raise DecryptionError(f"AES decryption failed: {e}")


def extract_db_gz(zip_data: bytes) -> bytes:
    """
    Extract db.gz from decrypted ZIP archive.

    Args:
        zip_data: Decrypted ZIP file bytes

    Returns:
        Contents of db.gz (still gzipped)

    Raises:
        ExtractionError: If extraction fails
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data), 'r') as zf:
            # List contents for debugging
            file_list = zf.namelist()
            print(f"  ZIP contents: {file_list}")

            # Look for db.gz
            if 'db.gz' in file_list:
                return zf.read('db.gz')

            # Try alternative names
            for name in file_list:
                if name.endswith('.gz') or name == 'db':
                    print(f"  Using alternative: {name}")
                    return zf.read(name)

            raise ExtractionError(f"No database file found. Contents: {file_list}")

    except zipfile.BadZipFile as e:
        raise ExtractionError(f"Invalid ZIP file: {e}")
    except Exception as e:
        raise ExtractionError(f"ZIP extraction failed: {e}")


def decompress_db(db_gz_data: bytes) -> bytes:
    """
    Decompress gzipped database.

    Args:
        db_gz_data: Gzipped BSON data

    Returns:
        Raw BSON data
    """
    try:
        return gzip.decompress(db_gz_data)
    except gzip.BadGzipFile as e:
        raise ExtractionError(f"Invalid gzip data: {e}")


def parse_bson_documents(bson_data: bytes) -> Dict[str, List[Dict[str, Any]]]:
    """
    Parse concatenated BSON documents into collections.

    UniFi backups contain multiple BSON documents concatenated together.
    Each document typically has a '_type' field indicating the collection.

    Args:
        bson_data: Raw BSON bytes

    Returns:
        Dictionary mapping collection names to lists of documents
    """
    collections: Dict[str, List[Dict[str, Any]]] = {}
    offset = 0
    doc_count = 0

    while offset < len(bson_data):
        try:
            # BSON documents start with 4-byte little-endian size
            if offset + 4 > len(bson_data):
                break

            doc_size = int.from_bytes(bson_data[offset:offset+4], 'little')

            if doc_size < 5 or offset + doc_size > len(bson_data):
                # Invalid size or not enough data
                break

            doc_bytes = bson_data[offset:offset + doc_size]
            doc = bson.decode(doc_bytes)
            doc_count += 1

            # Determine collection name
            collection = doc.get('_type', 'unknown')
            if collection not in collections:
                collections[collection] = []
            collections[collection].append(doc)

            offset += doc_size

        except Exception as e:
            print(f"  Warning: BSON parse error at offset {offset}: {e}")
            # Try to continue by searching for next valid document
            offset += 1

    print(f"  Parsed {doc_count} BSON documents across {len(collections)} collections")
    return collections


def json_serializer(obj: Any) -> Any:
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return f"<bytes:{len(obj)}>"
    if hasattr(obj, '__dict__'):
        return str(obj)
    return str(obj)


def dump_collections_summary(collections: Dict[str, List[Dict[str, Any]]]) -> None:
    """Print summary of all collections found."""
    print("\n" + "=" * 60)
    print("COLLECTIONS SUMMARY")
    print("=" * 60)

    # Sort by document count (most important first)
    sorted_collections = sorted(
        collections.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )

    for name, docs in sorted_collections:
        print(f"\n  {name}: {len(docs)} document(s)")

        # Show sample fields from first document
        if docs:
            sample = docs[0]
            fields = list(sample.keys())[:10]
            print(f"    Fields: {', '.join(fields)}")
            if len(sample.keys()) > 10:
                print(f"    ... and {len(sample.keys()) - 10} more fields")


def dump_collection_detail(
    collections: Dict[str, List[Dict[str, Any]]],
    collection_name: str,
    max_docs: int = 3,
    output_file: Optional[Path] = None
) -> None:
    """Dump detailed contents of a specific collection."""
    if collection_name not in collections:
        print(f"Collection '{collection_name}' not found")
        return

    docs = collections[collection_name]
    print(f"\n{'=' * 60}")
    print(f"COLLECTION: {collection_name} ({len(docs)} documents)")
    print("=" * 60)

    output_docs = docs[:max_docs]

    for i, doc in enumerate(output_docs):
        print(f"\n--- Document {i + 1}/{len(docs)} ---")
        try:
            formatted = json.dumps(doc, indent=2, default=json_serializer)
            # Truncate very long output
            if len(formatted) > 5000:
                formatted = formatted[:5000] + "\n... (truncated)"
            print(formatted)
        except Exception as e:
            print(f"Error formatting document: {e}")

    if output_file:
        with open(output_file, 'w') as f:
            json.dump(docs, f, indent=2, default=json_serializer)
        print(f"\nFull collection written to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Decrypt and analyze UniFi backup files (.unf)",
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
        """
    )
    parser.add_argument(
        "backup_file",
        type=Path,
        help="Path to .unf backup file"
    )
    parser.add_argument(
        "-c", "--collection",
        type=str,
        action="append",
        help="Show details for specific collection(s). Can be repeated."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Show details for all collections"
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=3,
        help="Maximum documents to show per collection (default: 3)"
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output JSON file for collection export"
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list collections, don't show contents"
    )

    args = parser.parse_args()

    # Validate input file
    if not args.backup_file.exists():
        print(f"ERROR: File not found: {args.backup_file}")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print("UNIFI BACKUP DECRYPT POC")
    print("=" * 60)
    print(f"Input: {args.backup_file}")
    print(f"Size: {args.backup_file.stat().st_size:,} bytes")

    try:
        # Step 1: Read encrypted backup
        print("\n[1/4] Reading encrypted backup...")
        encrypted_data = args.backup_file.read_bytes()
        print(f"  Read {len(encrypted_data):,} bytes")

        # Step 2: Decrypt
        print("\n[2/4] Decrypting (AES-128-CBC)...")
        decrypted_data = decrypt_backup(encrypted_data)
        print(f"  Decrypted to {len(decrypted_data):,} bytes")

        # Quick validation - ZIP files start with PK
        if decrypted_data[:2] != b'PK':
            print("  WARNING: Decrypted data doesn't look like ZIP (no PK header)")
            print(f"  First bytes: {decrypted_data[:20].hex()}")
        else:
            print("  ✓ Valid ZIP header detected")

        # Step 3: Extract db.gz
        print("\n[3/4] Extracting database from ZIP...")
        db_gz_data = extract_db_gz(decrypted_data)
        print(f"  Extracted {len(db_gz_data):,} bytes (compressed)")

        # Decompress
        print("  Decompressing gzip...")
        bson_data = decompress_db(db_gz_data)
        print(f"  Decompressed to {len(bson_data):,} bytes")

        # Step 4: Parse BSON
        print("\n[4/4] Parsing BSON documents...")
        collections = parse_bson_documents(bson_data)

        # Show results
        dump_collections_summary(collections)

        if args.list_only:
            print("\n✓ Decrypt successful! Use -c <collection> to see details.")
            return

        # Important collections for network config comparison
        important_collections = [
            "setting",
            "networkconf",
            "device",
            "usergroup",
            "firewallrule",
            "firewallgroup",
            "wlanconf",
            "portconf",
            "routing",
            "dhcpd",
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
                collections,
                coll_name,
                max_docs=args.max_docs,
                output_file=output_file
            )

        print("\n" + "=" * 60)
        print("✓ DECRYPT SUCCESSFUL")
        print("=" * 60)
        print(f"Collections found: {len(collections)}")
        print(f"Total documents: {sum(len(d) for d in collections.values())}")

        # Suggestions
        print("\nKey collections for config comparison:")
        for coll in important_collections:
            if coll in collections:
                print(f"  ✓ {coll}: {len(collections[coll])} docs")
            else:
                print(f"  ✗ {coll}: not found")

    except BackupDecryptError as e:
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
