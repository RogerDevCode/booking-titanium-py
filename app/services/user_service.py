from typing import Optional, Any
from app.domain.protocols import DatabaseClientProtocol
from app.domain.entities import TelegramUser, ReminderPreferences

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

    async def get_reminder_preferences(self, user_id: int) -> ReminderPreferences:
        query_select = """
            SELECT user_id, telegram_enabled, email_enabled, window_24h, window_2h, updated_at
            FROM reminder_preferences
            WHERE user_id = $1
        """
        row = await self._db.fetchrow(query_select, user_id)
        if not row:
            query_insert = """
                INSERT INTO reminder_preferences (user_id, telegram_enabled, email_enabled, window_24h, window_2h)
                VALUES ($1, true, false, true, true)
                ON CONFLICT (user_id) DO NOTHING
                RETURNING user_id, telegram_enabled, email_enabled, window_24h, window_2h, updated_at
            """
            row = await self._db.fetchrow(query_insert, user_id)
            if not row:
                row = await self._db.fetchrow(query_select, user_id)
        
        if not row:
            raise ValueError(f"Reminder preferences not found or created for user {user_id}")
        
        from app.domain.entities import ReminderPreferences
        return ReminderPreferences(
            user_id=row['user_id'],
            telegram_enabled=row['telegram_enabled'],
            email_enabled=row['email_enabled'],
            window_24h=row['window_24h'],
            window_2h=row['window_2h'],
            updated_at=row['updated_at']
        )

    async def update_reminder_preference(self, user_id: int, field: str) -> ReminderPreferences:
        if field not in ["telegram_enabled", "email_enabled", "window_24h", "window_2h", "all_off", "all_on"]:
            raise ValueError(f"Invalid preference field: {field}")
        
        await self.get_reminder_preferences(user_id)

        if field == "all_off":
            query = """
                UPDATE reminder_preferences
                SET telegram_enabled = false, email_enabled = false, window_24h = false, window_2h = false, updated_at = NOW()
                WHERE user_id = $1
                RETURNING user_id, telegram_enabled, email_enabled, window_24h, window_2h, updated_at
            """
            row = await self._db.fetchrow(query, user_id)
        elif field == "all_on":
            query = """
                UPDATE reminder_preferences
                SET telegram_enabled = true, email_enabled = true, window_24h = true, window_2h = true, updated_at = NOW()
                WHERE user_id = $1
                RETURNING user_id, telegram_enabled, email_enabled, window_24h, window_2h, updated_at
            """
            row = await self._db.fetchrow(query, user_id)
        else:
            query = f"""
                UPDATE reminder_preferences
                SET {field} = NOT {field}, updated_at = NOW()
                WHERE user_id = $1
                RETURNING user_id, telegram_enabled, email_enabled, window_24h, window_2h, updated_at
            """
            row = await self._db.fetchrow(query, user_id)

        if not row:
            raise ValueError(f"Failed to update or retrieve reminder preferences for user {user_id}")
            
        from app.domain.entities import ReminderPreferences
        return ReminderPreferences(
            user_id=row['user_id'],
            telegram_enabled=row['telegram_enabled'],
            email_enabled=row['email_enabled'],
            window_24h=row['window_24h'],
            window_2h=row['window_2h'],
            updated_at=row['updated_at']
        )

