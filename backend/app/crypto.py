"""Symmetric encryption for secrets stored in the database (Fernet: AES-128-CBC + HMAC)."""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class DecryptionError(Exception):
    """The value was encrypted with a different secret key, or is corrupt."""


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("Could not decrypt a stored secret") from exc


@lru_cache
def _fernet() -> Fernet:
    # Fernet needs a 32-byte key; derive one so any secret string can be configured.
    digest = hashlib.sha256(get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
