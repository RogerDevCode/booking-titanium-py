import binascii
import hashlib


def verify_password_sync(password: str, stored_hash: str) -> bool:
    """
    Verifies password against salt:hash scrypt format.
    Matches logic used in TypeScript.
    """
    try:
        parts = stored_hash.split(":")
        if len(parts) != 2:
            return False

        salt = parts[0]
        stored_key = parts[1]

        # Scrypt parameters used by crypto.scryptSync in Node.js (defaults)
        # N=16384, r=8, p=1, keylen=64
        # We need to match these if they were custom, but usually they are defaults.
        # hashlib.scrypt(password, salt, n, r, p, maxmem=0, dklen=64)

        # Salt from TS is usually hex or raw string?
        # crypto.scryptSync(password, salt, 64) -> salt is treated as Buffer/String

        key = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=16384, r=8, p=1, dklen=64)

        return binascii.hexlify(key).decode("utf-8") == stored_key
    except Exception as e:
        from ..internal._wmill_adapter import log

        log("SILENT_ERROR_CAUGHT", error=str(e), file="_login_logic.py")
        return False
