from typing import Optional, Any
from app.domain.protocols import DatabaseClientProtocol

from app.domain.entities import TelegramUser

class UserService:
    def __init__(self, db: DatabaseClientProtocol) -> None:
        self._db = db
    async def get_user(self, user_id: int) -> Optional[TelegramUser]:
        query = "SELECT id, username, first_name, last_name, phone, email, address, rut FROM users WHERE id = $1"
        row = await self._db.fetchrow(query, user_id)
        if row:
            return TelegramUser(
                id=row['id'],
                username=row['username'],
                first_name=row['first_name'],
                last_name=row['last_name'],
                phone=row['phone'],
                email=row['email'],
                address=row['address'],
                rut=row['rut']
            )
        return None

    async def upsert_user(self, user: TelegramUser) -> tuple[TelegramUser, bool]:
        query = """
            INSERT INTO users (id, username, first_name, last_name, phone, email, address, rut, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = users.first_name,
                last_name = users.last_name,
                phone = COALESCE(EXCLUDED.phone, users.phone),
                email = COALESCE(EXCLUDED.email, users.email),
                address = COALESCE(EXCLUDED.address, users.address),
                rut = COALESCE(EXCLUDED.rut, users.rut),
                updated_at = NOW()
            RETURNING id, username, first_name, last_name, phone, email, address, rut, (xmax = 0) AS is_new
        """
        row = await self._db.fetchrow(
            query, 
            user.id, 
            user.username, 
            user.first_name, 
            user.last_name, 
            user.phone, 
            user.email,
            user.address,
            user.rut
        )
        row_dict: dict[str, Any] = dict(row) # type: ignore
        is_new = row_dict.pop("is_new", False)
        return TelegramUser.model_validate(row_dict), is_new

    async def update_field(self, user_id: int, field: str, value: str) -> bool:
        if field not in ["first_name", "phone", "email", "address", "rut"]:
            return False
        
        query = f"UPDATE users SET {field} = $1, updated_at = NOW() WHERE id = $2"
        await self._db.execute(query, value, user_id)
        return True

