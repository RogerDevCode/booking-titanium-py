from datetime import datetime

from ..internal._result import DBClient
from ._specialty_models import InputSchema, SpecialtyRow


def map_row(r: dict[str, object]) -> SpecialtyRow:
    created_at_raw = r.get("created_at")
    return {
        "specialty_id": str(r["specialty_id"]),
        "name": str(r["name"]),
        "description": str(r["description"]) if r.get("description") else None,
        "category": str(r["category"]) if r.get("category") else None,
        "is_active": bool(r["is_active"]),
        "sort_order": int(str(r["sort_order"])),
        "created_at": created_at_raw.isoformat() if isinstance(created_at_raw, datetime) else str(created_at_raw),
    }


async def list_specialties(db: DBClient) -> list[SpecialtyRow]:
    try:
        rows = await db.fetch("SELECT * FROM specialties ORDER BY sort_order ASC, name ASC")
        return [map_row(r) for r in rows]
    except Exception as e:
        raise RuntimeError(f"list_failed: {e}") from e


async def create_specialty(db: DBClient, input_data: InputSchema) -> SpecialtyRow:
    if not input_data.name:
        raise RuntimeError("create_failed: name is required")
    try:
        rows = await db.fetch(
            """
            INSERT INTO specialties (name, description, category, sort_order)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            input_data.name,
            input_data.description,
            input_data.category or "Medicina",
            input_data.sort_order or 99,
        )
        if not rows:
            raise RuntimeError("create_failed: no row returned")
        return map_row(rows[0])
    except Exception as e:
        raise RuntimeError(f"create_failed: {e}") from e


async def update_specialty(db: DBClient, id: str, input_data: InputSchema) -> SpecialtyRow:
    try:
        _ALLOWED = {"name", "description", "category", "sort_order"}
        fields: list[str] = []
        params: list[object] = []
        idx = 1

        for field in ["name", "description", "category", "sort_order"]:
            if field not in _ALLOWED:
                continue
            val = getattr(input_data, field)
            if val is not None:
                fields.append(f"{field} = ${idx}")
                params.append(val)
                idx += 1

        if not fields:
            raise RuntimeError("update_failed: no fields provided")

        params.append(id)
        query = f"UPDATE specialties SET {', '.join(fields)} WHERE specialty_id = ${idx}::uuid RETURNING *"
        rows = await db.fetch(query, *params)

        if not rows:
            raise RuntimeError(f"update_failed: specialty {id} not found")
        return map_row(rows[0])
    except Exception as e:
        raise RuntimeError(f"update_failed: {e}") from e


async def delete_specialty(db: DBClient, id: str) -> dict[str, bool]:
    try:
        await db.execute("DELETE FROM specialties WHERE specialty_id = $1::uuid", id)
        return {"deleted": True}
    except Exception as e:
        raise RuntimeError(f"delete_failed: {e}") from e


async def set_status(db: DBClient, id: str, active: bool) -> dict[str, object]:
    try:
        res = await db.execute("UPDATE specialties SET is_active = $1 WHERE specialty_id = $2::uuid", active, id)
        if "UPDATE 1" not in res:
            raise RuntimeError(f"status_update_failed: specialty {id} not found")
        return {"specialty_id": id, "is_active": active}
    except Exception as e:
        raise RuntimeError(f"status_update_failed: {e}") from e
