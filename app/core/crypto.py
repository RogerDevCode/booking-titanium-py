import binascii
import hashlib
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def get_encryption_key() -> bytes:
    key_env = os.getenv("ENCRYPTION_KEY")
    if not key_env:
        # Use DATABASE_URL or a fallback salt key to derive key
        db_url = os.getenv("DATABASE_URL") or "fallback-key"
        return hashlib.scrypt(
            db_url.encode(),
            salt=b"booking-titanium-salt",
            n=16384,
            r=8,
            p=1,
            dklen=32
        )
    return binascii.unhexlify(key_env)

def encrypt_data(plain: str) -> str:
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plain.encode("utf-8"), None)
    return binascii.hexlify(nonce + ciphertext).decode("utf-8")

def decrypt_data(encrypted_hex: str) -> str:
    key = get_encryption_key()
    data = binascii.unhexlify(encrypted_hex)
    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    decrypted = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted.decode("utf-8")
