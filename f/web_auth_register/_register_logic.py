import binascii
import hashlib
import os
import re


def validate_rut(rut: str) -> bool:
    clean = re.sub(r"[.-]", "", rut).upper()
    if len(clean) < 2:
        return False

    body = clean[:-1]
    dv = clean[-1:]

    if not re.match(r"^\d+$", body):
        return False
    if not re.match(r"^[\dK]$", dv):
        return False

    s = 0
    m = 2
    for digit in reversed(body):
        s += int(digit) * m
        m = 2 if m == 7 else m + 1

    remainder = 11 - (s % 11)
    expected_dv = "0" if remainder == 11 else "K" if remainder == 10 else str(remainder)

    return dv == expected_dv


def validate_password_strength(password: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"
    if not re.search(r"[0-9]", password):
        return "Password must contain at least one number"
    if not re.search(r"[^A-Za-z0-9]", password):
        return "Password must contain at least one special character"
    return None


def hash_password_sync(password: str) -> str:
    # Use 16 bytes random salt
    salt = binascii.hexlify(os.urandom(16)).decode("utf-8")

    # Match Node.js default scrypt params
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=16384, r=8, p=1, dklen=64)

    return f"{salt}:{binascii.hexlify(key).decode('utf-8')}"
