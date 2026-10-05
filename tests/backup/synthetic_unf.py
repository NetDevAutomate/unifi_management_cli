"""Build synthetic UniFi ``.unf`` backups for tests (never a real backup).

``build_unf_bytes`` reproduces the controller's format: BSON documents, gzipped as
``db.gz``, zipped, then AES-128-CBC encrypted with the controller's fixed, public backup key
and IV. Every value in the documents is a documentation value.
"""

import bson
import gzip
import io
import zipfile
from Crypto.Cipher import AES
from unifi_mapper.backup.poc_decrypt import UNIFI_AES_IV, UNIFI_AES_KEY


COLLECTIONS: dict[str, list[dict]] = {
    'device': [{'_id': 'dev1', 'name': 'Switch A', 'mac': '02:00:00:00:00:01'}],
    'networkconf': [{'_id': 'net1', 'name': 'VLAN 10', 'vlan': 10}],
    'wlanconf': [{'_id': 'wlan1', 'name': 'SSID A'}],
    'setting': [{'_id': 'set1', 'key': 'super', 'version': '9.10.0'}],
    'usergroup': [{'_id': 'grp1', 'name': 'Default'}],
}


def _pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    """Pad with 1-15 bytes: the decryptor strips a pad only when its last byte is below 16."""
    if len(data) % block == 0:
        data += b'\x00'
    pad = block - len(data) % block
    return data + bytes([pad]) * pad


def encrypt_unf(zip_bytes: bytes) -> bytes:
    """Encrypt a zip with the controller's fixed backup key and IV."""
    return AES.new(UNIFI_AES_KEY, AES.MODE_CBC, UNIFI_AES_IV).encrypt(_pkcs7_pad(zip_bytes))


def bson_stream(collections: dict[str, list[dict]]) -> bytes:
    """Concatenate one BSON document per entry, each tagged with its ``_type``."""
    return b''.join(
        bson.encode({**doc, '_type': name}) for name, docs in collections.items() for doc in docs
    )


def zip_with(name: str, payload: bytes) -> bytes:
    """A zip holding one member."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr(name, payload)
    return buffer.getvalue()


def build_unf_bytes(
    collections: dict[str, list[dict]] | None = None, *, db_gz: bytes | None = None
) -> bytes:
    """A synthetic ``.unf``: ``collections`` (default :data:`COLLECTIONS`) or a raw ``db.gz``."""
    if db_gz is None:
        db_gz = gzip.compress(bson_stream(COLLECTIONS if collections is None else collections))
    return encrypt_unf(zip_with('db.gz', db_gz))
