from datetime import datetime

from ..internal._result import DBClient
from ._tags_models import CategoryRow, InputSchema, TagRow


def map_category(r: dict[str, object]) -> CategoryRow:
    created_at_raw = r.get("created_at")
    return {
        "category_id": str(r["category_id"]),
        "name": str(r["name"]),
        "description": str(r["description"]) if r.get("description") else None,
        "is_active": bool(r["is_active"]),
        "sort_order": int(str(r["sort_order"])),
        "created_at": created_at_raw.isoformat() if isinstance(created_at_raw, datetime) else str(created_at_raw),
        "tag_count": int(str(r.get("tag_count", 0))),
    }


def map_tag(r: dict[str, object]) -> TagRow:
    created_at_raw = r.get("created_at")
    return {
        "tag_id": str(r["tag_id"]),
        "category_id": str(r["category_id"]),
        "category_name": str(r.get("category_name", "")),
        "name": str(r["name"]),
        "description": str(r["description"]) if r.get("description") else None,
        "color": str(r["color"]),
        "is_active": bool(r["is_active"]),
        "sort_order": int(str(r["sort_order"])),
        "created_at": created_at_raw.isoformat() if isinstance(created_at_raw, datetime) else str(created_at_raw),
    }


async def verify_admin_access(db: DBClient, user_id: str) -> bool:
    rows = await db.fetch("SELECT role FROM users WHERE user_id = $1::uuid AND is_active = true LIMIT 1", user_id)
    if not rows:
        raise RuntimeError("UNAUTHORIZED: Admin user not found or inactive")
    if rows[0]["role"] != "admin":
        raise RuntimeError("FORBIDDEN: Admin access required")
    return True


class TagRepository:
    def __init__(self, db: DBClient) -> None:
        self.db = db

    async def list_categories(self) -> list[CategoryRow]:
        try:
            rows = await self.db.fetch(
                """
                SELECT tc.category_id, tc.name, tc.description, tc.is_active, tc.sort_order, tc.created_at,
                       COUNT(t.tag_id) FILTER (WHERE t.is_active = true)::int AS tag_count
                FROM tag_categories tc
                LEFT JOIN tags t ON t.category_id = tc.category_id
                GROUP BY tc.category_id, tc.name, tc.description, tc.is_active, tc.sort_order, tc.created_at
                ORDER BY tc.sort_order ASC, tc.name ASC
                """
            )
            return [map_category(r) for r in rows]
        except Exception as e:
            raise RuntimeError(f"list_categories_failed: {e}") from e

    async def create_category(self, name: str, description: str | None, sort_order: int) -> CategoryRow:
        try:
            rows = await self.db.fetch(
                "INSERT INTO tag_categories (name, description, sort_order) VALUES ($1, $2, $3) RETURNING *, 0 as tag_count",  # noqa: E501
                name,
                description,
                sort_order,
            )
            if not rows:
                raise RuntimeError("create_failed")
            return map_category(rows[0])
        except Exception as e:
            raise RuntimeError(f"create_failed: {e}") from e

    async def update_category(self, category_id: str, input_data: InputSchema) -> CategoryRow:
        try:
            _ALLOWED = {"name", "description", "sort_order"}
            fields: list[str] = []
            params: list[object] = []
            idx = 1
            for field in ["name", "description", "sort_order"]:
                if field not in _ALLOWED:
                    continue
                val = getattr(input_data, field)
                if val is not None:
                    fields.append(f"{field} = ${idx}")
                    params.append(val)
                    idx += 1
            if not fields:
                raise RuntimeError("update_failed: no fields provided")
            params.append(category_id)
            query = f"UPDATE tag_categories SET {', '.join(fields)}, updated_at = NOW() WHERE category_id = ${idx}::uuid RETURNING *, 0 as tag_count"  # noqa: E501
            rows = await self.db.fetch(query, *params)
            if not rows:
                raise RuntimeError("update_failed: not found")
            return map_category(rows[0])
        except Exception as e:
            raise RuntimeError(f"update_failed: {e}") from e

    async def set_category_status(self, category_id: str, active: bool) -> dict[str, object]:
        try:
            rows = await self.db.fetch(
                "UPDATE tag_categories SET is_active = $1, updated_at = NOW() WHERE category_id = $2::uuid RETURNING category_id, is_active",  # noqa: E501
                active,
                category_id,
            )
            if not rows:
                raise RuntimeError("not_found")
            return {"category_id": str(rows[0]["category_id"]), "is_active": bool(rows[0]["is_active"])}
        except Exception as e:
            raise RuntimeError(f"status_failed: {e}") from e

    async def delete_category(self, category_id: str) -> dict[str, bool]:
        try:
            res = await self.db.execute("DELETE FROM tag_categories WHERE category_id = $1::uuid", category_id)
            return {"deleted": "DELETE 1" in res}
        except Exception as e:
            raise RuntimeError(f"delete_failed: {e}") from e

    async def list_tags(self, category_id: str | None = None) -> list[TagRow]:
        try:
            if category_id:
                rows = await self.db.fetch(
                    """
                    SELECT t.*, tc.name AS category_name
                    FROM tags t JOIN tag_categories tc ON tc.category_id = t.category_id
                    WHERE t.category_id = $1::uuid
                    ORDER BY t.sort_order ASC, t.name ASC
                    """,
                    category_id,
                )
            else:
                rows = await self.db.fetch(
                    """
                    SELECT t.*, tc.name AS category_name
                    FROM tags t JOIN tag_categories tc ON tc.category_id = t.category_id
                    ORDER BY tc.sort_order ASC, t.sort_order ASC, t.name ASC
                    """
                )
            return [map_tag(r) for r in rows]
        except Exception as e:
            raise RuntimeError(f"list_tags_failed: {e}") from e

    async def create_tag(
        self, category_id: str, name: str, description: str | None, color: str, sort_order: int
    ) -> TagRow:
        try:
            rows = await self.db.fetch(
                """
                INSERT INTO tags (category_id, name, description, color, sort_order)
                VALUES ($1::uuid, $2, $3, $4, $5)
                RETURNING *, (SELECT name FROM tag_categories WHERE category_id = $1::uuid) as category_name
                """,
                category_id,
                name,
                description,
                color,
                sort_order,
            )
            if not rows:
                raise RuntimeError("create_tag_failed")
            return map_tag(rows[0])
        except Exception as e:
            raise RuntimeError(f"create_tag_failed: {e}") from e

    async def update_tag(self, tag_id: str, input_data: InputSchema) -> TagRow:
        try:
            _ALLOWED = {"name", "description", "color", "sort_order", "category_id"}
            fields: list[str] = []
            params: list[object] = []
            idx = 1
            for field in ["name", "description", "color", "sort_order"]:
                if field not in _ALLOWED:
                    continue
                val = getattr(input_data, field)
                if val is not None:
                    fields.append(f"{field} = ${idx}")
                    params.append(val)
                    idx += 1
            if input_data.category_id and "category_id" in _ALLOWED:
                fields.append(f"category_id = ${idx}::uuid")
                params.append(input_data.category_id)
                idx += 1

            if not fields:
                raise RuntimeError("update_failed: no fields")
            params.append(tag_id)
            query = f"UPDATE tags SET {', '.join(fields)}, updated_at = NOW() WHERE tag_id = ${idx}::uuid RETURNING *, (SELECT name FROM tag_categories WHERE category_id = tags.category_id) as category_name"  # noqa: E501
            rows = await self.db.fetch(query, *params)
            if not rows:
                raise RuntimeError("not_found")
            return map_tag(rows[0])
        except Exception as e:
            raise RuntimeError(f"update_failed: {e}") from e

    async def set_tag_status(self, tag_id: str, active: bool) -> dict[str, object]:
        try:
            rows = await self.db.fetch(
                "UPDATE tags SET is_active = $1, updated_at = NOW() WHERE tag_id = $2::uuid RETURNING tag_id, is_active",  # noqa: E501
                active,
                tag_id,
            )
            if not rows:
                raise RuntimeError("not_found")
            return {"tag_id": str(rows[0]["tag_id"]), "is_active": bool(rows[0]["is_active"])}
        except Exception as e:
            raise RuntimeError(f"status_failed: {e}") from e

    async def delete_tag(self, tag_id: str) -> dict[str, bool]:
        try:
            res = await self.db.execute("DELETE FROM tags WHERE tag_id = $1::uuid", tag_id)
            return {"deleted": "DELETE 1" in res}
        except Exception as e:
            raise RuntimeError(f"delete_failed: {e}") from e
