from __future__ import annotations

import binascii
import hashlib
import os
import re
from typing import TypedDict

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ============================================================================
# CRYPTO — Password hashing (Scrypt) + AES-256-GCM data encryption
# ============================================================================

# Note: Using Scrypt for password hashing as it's the current project standard
# (Argon2id implementation in Python would require 'argon2-cffi' package)


def hash_password(password: str) -> str:
    salt = binascii.hexlify(os.urandom(16)).decode("utf-8")
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=16384, r=8, p=1, dklen=64)
    return f"{salt}:{binascii.hexlify(key).decode('utf-8')}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        parts = stored_hash.split(":")
        if len(parts) != 2:
            return False
        salt, stored_key = parts
        key = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=16384, r=8, p=1, dklen=64)
        return binascii.hexlify(key).decode("utf-8") == stored_key
    except Exception as e:
        from ._wmill_adapter import log

        log("SILENT_ERROR_CAUGHT", error=str(e), file="_crypto.py")
        return False


class PasswordPolicyResult(TypedDict):
    valid: bool
    errors: list[str]


def validate_password_policy(plain: str) -> PasswordPolicyResult:
    errors: list[str] = []
    if len(plain) < 8:
        errors.append("Minimum 8 characters")
    if len(plain) > 128:
        errors.append("Maximum 128 characters")
    if not re.search(r"[A-Z]", plain):
        errors.append("At least one uppercase letter")
    if not re.search(r"[a-z]", plain):
        errors.append("At least one lowercase letter")
    if not re.search(r"[0-9]", plain):
        errors.append("At least one digit")
    if not re.search(r"[!@#$%^&*()_+\-=[\]{};':\"\\|,.<>/?]", plain):
        errors.append("At least one special character")

    if re.match(r"^(.)\1+$", plain):
        errors.append("Password cannot be all same character")
    if re.match(r"^(123|abc|qwe|password|admin)", plain, re.I):
        errors.append("Password cannot start with common patterns")

    return {"valid": len(errors) == 0, "errors": errors}


# ============================================================================
# AES-256-GCM DATA ENCRYPTION
# ============================================================================


def get_encryption_key() -> bytes:
    key_env = os.getenv("ENCRYPTION_KEY")
    if not key_env:
        db_url = os.getenv("DATABASE_URL") or "fallback-key"
        return hashlib.scrypt(db_url.encode(), salt=b"booking-titanium-salt", n=16384, r=8, p=1, dklen=32)
    return binascii.unhexlify(key_env)


def encrypt_data(plain: str) -> str:
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plain.encode("utf-8"), None)

    # Structure: nonce + ciphertext (tag is at the end of ciphertext in cryptography lib)
    return binascii.hexlify(nonce + ciphertext).decode("utf-8")


def decrypt_data(encrypted_hex: str) -> str:
    key = get_encryption_key()
    data = binascii.unhexlify(encrypted_hex)
    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    decrypted = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted.decode("utf-8")
