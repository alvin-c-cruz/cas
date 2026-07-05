"""Task 1 — AES-256-GCM crypto + KeyProvider."""
import os
import pytest
from app.backup.crypto import (encrypt, decrypt, StaticKeyProvider,
                               key_id_for, WrongKeyError)

KEY = b'0' * 32
KP = StaticKeyProvider(KEY)


@pytest.mark.parametrize("size", [0, 1, 664 * 1024, 3 * 1024 * 1024])
def test_round_trip(size):
    data = os.urandom(size)
    assert decrypt(encrypt(data, KP), KP) == data


def test_nonce_unique():
    a, b = encrypt(b"same", KP), encrypt(b"same", KP)
    assert a != b  # random 96-bit nonce per artifact


def test_tamper_ciphertext_raises():
    blob = bytearray(encrypt(b"secret books", KP))
    blob[-1] ^= 0x01
    with pytest.raises(Exception):
        decrypt(bytes(blob), KP)


def test_truncation_raises():
    blob = encrypt(b"secret", KP)
    with pytest.raises(Exception):
        decrypt(blob[:-1], KP)


def test_wrong_key_raises_wrongkey():
    blob = encrypt(b"secret", KP)
    with pytest.raises(WrongKeyError):
        decrypt(blob, StaticKeyProvider(b'1' * 32))


def test_key_id_stable():
    assert key_id_for(KEY) == key_id_for(KEY)
    assert key_id_for(KEY) != key_id_for(b'1' * 32)


def test_reject_wrong_length_key():
    with pytest.raises(ValueError):
        StaticKeyProvider(b'short')
