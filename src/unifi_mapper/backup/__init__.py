"""UniFi backup management - decrypt, compare, and analyze backup files."""

from .poc_decrypt import (
    BackupDecryptError,
    DecryptionError,
    ExtractionError,
    BSONParseError,
    DatabaseTooLargeError,
    decrypt_backup,
    extract_db_gz,
    decompress_db,
    iter_bson_documents,
    parse_bson_documents,
)

__all__ = [
    'BackupDecryptError',
    'DecryptionError',
    'ExtractionError',
    'BSONParseError',
    'DatabaseTooLargeError',
    'decrypt_backup',
    'extract_db_gz',
    'decompress_db',
    'iter_bson_documents',
    'parse_bson_documents',
]
