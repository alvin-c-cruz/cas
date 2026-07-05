"""AES-256-GCM encryption for backup artifacts.

On-disk framing (see plan Pinned Contracts):
    MAGIC(6) | len(key_id)(1) | key_id(ascii) | nonce(12) | AESGCM ciphertext(+tag)
"""
import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"CASBK1"
NONCE_LEN = 12


class WrongKeyError(Exception):
    """Raised when an artifact's key_id does not match any available key."""


def key_id_for(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]


class KeyProvider:
    def current(self):  # -> (key_id: str, key: bytes)
        raise NotImplementedError

    def get(self, key_id):  # -> key bytes
        raise NotImplementedError


class StaticKeyProvider(KeyProvider):
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("AES-256 key must be 32 bytes")
        self._key = key
        self._id = key_id_for(key)

    def current(self):
        return self._id, self._key

    def get(self, key_id):
        if key_id != self._id:
            raise WrongKeyError(f"no key for id {key_id}")
        return self._key


class FileKeyProvider(StaticKeyProvider):
    """Reads a base64-encoded 32-byte key from a file outside the web root."""

    def __init__(self, path: str):
        with open(path, "rb") as fh:
            key = base64.b64decode(fh.read().strip())
        super().__init__(key)


def encrypt(plaintext: bytes, kp: KeyProvider) -> bytes:
    key_id, key = kp.current()
    kid = key_id.encode("ascii")
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return MAGIC + bytes([len(kid)]) + kid + nonce + ct


def decrypt(blob: bytes, kp: KeyProvider) -> bytes:
    if blob[:6] != MAGIC:
        raise ValueError("bad magic / not a CAS backup artifact")
    klen = blob[6]
    kid = blob[7:7 + klen].decode("ascii")
    nonce = blob[7 + klen:7 + klen + NONCE_LEN]
    ct = blob[7 + klen + NONCE_LEN:]
    key = kp.get(kid)  # raises WrongKeyError if unknown
    return AESGCM(key).decrypt(nonce, ct, None)
