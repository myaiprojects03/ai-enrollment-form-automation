"""Field-level encryption for applicant data at rest, and keyed fingerprints for lookups.

Values are sealed with AES-256-GCM: each one gets a random 96-bit nonce, and the record id is bound in as
associated data, so a ciphertext copied onto another row fails to open. A short key id is stored in front, so
keys can be rotated: the first key encrypts, every configured key can decrypt.

Fingerprints (HMAC-SHA256 with a separate key) let the system find duplicates of an email or phone number
without storing it in clear.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = b"\x01"


class CryptoError(Exception):
    """A value could not be decrypted (wrong key, tampered or moved to another record)."""


def _decode_key(text: str) -> bytes:
    try:
        key = base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("encryption key must be base64") from exc
    if len(key) != 32:
        raise ValueError("encryption key must be 32 bytes (base64 of 32 random bytes)")
    return key


def new_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


class FieldCipher:
    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("at least one encryption key is required")
        self._keys = [_decode_key(k) for k in keys]
        self._by_id = {self._key_id(k): k for k in self._keys}

    @classmethod
    def from_setting(cls, value: str) -> FieldCipher:
        return cls([k for k in value.split(",") if k.strip()])

    @staticmethod
    def _key_id(key: bytes) -> bytes:
        return hashlib.sha256(b"key-id" + key).digest()[:4]

    def seal(self, value: Any, record_id: str) -> bytes:
        """JSON-serialisable value -> version | key id | nonce | ciphertext+tag."""
        key = self._keys[0]
        nonce = os.urandom(12)
        data = json.dumps(value, separators=(",", ":"), default=str).encode()
        return VERSION + self._key_id(key) + nonce + AESGCM(key).encrypt(nonce, data, record_id.encode())

    def open(self, blob: bytes, record_id: str) -> Any:
        if len(blob) < 1 + 4 + 12 + 16 or blob[:1] != VERSION:
            raise CryptoError("not an encrypted value")
        key = self._by_id.get(bytes(blob[1:5]))
        if key is None:
            raise CryptoError("encrypted with a key that is not configured")
        try:
            data = AESGCM(key).decrypt(bytes(blob[5:17]), bytes(blob[17:]), record_id.encode())
        except InvalidTag as exc:
            raise CryptoError("value was changed or belongs to another record") from exc
        return json.loads(data)

    def seal_bytes(self, data: bytes, record_id: str) -> bytes:
        """Raw bytes (a screenshot) in the same format, without the JSON step."""
        key = self._keys[0]
        nonce = os.urandom(12)
        return VERSION + self._key_id(key) + nonce + AESGCM(key).encrypt(nonce, data, b"bytes:" + record_id.encode())

    def open_bytes(self, blob: bytes, record_id: str) -> bytes:
        if len(blob) < 1 + 4 + 12 + 16 or blob[:1] != VERSION:
            raise CryptoError("not an encrypted value")
        key = self._by_id.get(bytes(blob[1:5]))
        if key is None:
            raise CryptoError("encrypted with a key that is not configured")
        try:
            return AESGCM(key).decrypt(bytes(blob[5:17]), bytes(blob[17:]), b"bytes:" + record_id.encode())
        except InvalidTag as exc:
            raise CryptoError("value was changed or belongs to another record") from exc

    def needs_rotation(self, blob: bytes) -> bool:
        return bytes(blob[1:5]) != self._key_id(self._keys[0])


class Fingerprinter:
    def __init__(self, key: str):
        if not key:
            raise ValueError("a fingerprint key is required")
        self._key = _decode_key(key)

    def digest(self, text: str) -> str:
        return hmac.new(self._key, text.encode(), hashlib.sha256).hexdigest()

    def of(self, kind: str, value: str) -> str:
        """Same input -> same fingerprint; values are normalised so 'Jo@X.com ' matches 'jo@x.com'."""
        norm = "".join(value.split()).lower()
        return hmac.new(self._key, f"{kind}:{norm}".encode(), hashlib.sha256).hexdigest()
