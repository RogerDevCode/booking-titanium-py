import os
import hashlib
import binascii
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import jwt
from app.domain.protocols import DatabaseClientProtocol
from app.core.config import Settings

class AuthService:
    def __init__(self, db: DatabaseClientProtocol, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def hash_password(self, password: str) -> str:
        salt = binascii.hexlify(os.urandom(16)).decode("utf-8")
        key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt.encode("utf-8"),
            n=16384,
            r=8,
            p=1,
            dklen=64
        )
        hashed = binascii.hexlify(key).decode("utf-8")
        return f"{salt}:{hashed}"

    def verify_password(self, password: str, hashed_value: str) -> bool:
        try:
            parts = hashed_value.split(":")
            if len(parts) != 2:
                return False
            salt, stored_hash = parts[0], parts[1]
            key = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt.encode("utf-8"),
                n=16384,
                r=8,
                p=1,
                dklen=64
            )
            return binascii.hexlify(key).decode("utf-8") == stored_hash
        except Exception:
            return False

    async def authenticate_web_user(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT id, email, password_hash, role, provider_id
            FROM web_users
            WHERE email = $1
        """
        row = await self._db.fetchrow(query, email)
        if not row:
            return None

        if not self.verify_password(password, row["password_hash"]):
            return None

        return {
            "id": row["id"],
            "email": row["email"],
            "role": row["role"],
            "provider_id": row["provider_id"]
        }

    async def register_web_user(
        self, email: str, password: str, role: str, provider_id: Optional[int] = None
    ) -> Dict[str, Any]:
        pwd_hash = self.hash_password(password)
        query = """
            INSERT INTO web_users (email, password_hash, role, provider_id)
            VALUES ($1, $2, $3, $4)
            RETURNING id, email, role, provider_id
        """
        row = await self._db.fetchrow(query, email, pwd_hash, role, provider_id)
        if not row:
            raise RuntimeError("Failed to create web user")

        return {
            "id": row["id"],
            "email": row["email"],
            "role": row["role"],
            "provider_id": row["provider_id"]
        }

    def generate_jwt(self, user_id: int, email: str, role: str, provider_id: Optional[int] = None) -> str:
        payload = {
            "sub": str(user_id),
            "email": email,
            "role": role,
            "provider_id": provider_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=7),
            "iat": datetime.now(timezone.utc)
        }
        return jwt.encode(payload, self._settings.JWT_SECRET, algorithm="HS256")

    def decode_jwt(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            payload = jwt.decode(token, self._settings.JWT_SECRET, algorithms=["HS256"])
            return payload
        except Exception:
            return None
