from typing import TYPE_CHECKING, Any

from ..internal._result import DBClient

if TYPE_CHECKING:
    from ._regions_models import CommuneRow, RegionRow


async def list_regions(db: DBClient) -> dict[str, Any]:
    try:
        rows = await db.fetch(
            "SELECT region_id, name, code, is_active, sort_order FROM regions WHERE is_active = true ORDER BY sort_order ASC, name ASC"  # noqa: E501
        )
        regions: list[RegionRow] = [
            {
                "region_id": int(r["region_id"]),  # type: ignore[call-overload]
                "name": str(r["name"]),
                "code": str(r["code"]),
                "is_active": bool(r["is_active"]),
                "sort_order": int(r["sort_order"]),  # type: ignore[call-overload]
            }
            for r in rows
        ]
        return {"regions": regions, "count": len(regions)}
    except Exception as e:
        raise RuntimeError(f"list_regions_failed: {e}") from e


async def list_communes(db: DBClient, region_id: int | None) -> dict[str, Any]:
    try:
        if region_id is not None:
            rows = await db.fetch(
                """
                SELECT c.commune_id, c.name, c.region_id, c.is_active, r.name AS region_name
                FROM communes c JOIN regions r ON r.region_id = c.region_id
                WHERE c.is_active = true AND c.region_id = $1
                ORDER BY c.name ASC
                """,
                region_id,
            )
        else:
            rows = await db.fetch(
                """
                SELECT c.commune_id, c.name, c.region_id, c.is_active, r.name AS region_name
                FROM communes c JOIN regions r ON r.region_id = c.region_id
                WHERE c.is_active = true ORDER BY r.sort_order ASC, c.name ASC
                """
            )

        communes: list[CommuneRow] = [
            {
                "commune_id": int(r["commune_id"]),  # type: ignore[call-overload]
                "name": str(r["name"]),
                "region_id": int(r["region_id"]),  # type: ignore[call-overload]
                "is_active": bool(r["is_active"]),
                "region_name": str(r["region_name"]),
            }
            for r in rows
        ]
        return {"communes": communes, "count": len(communes)}
    except Exception as e:
        raise RuntimeError(f"list_communes_failed: {e}") from e


async def search_communes(db: DBClient, search: str, region_id: int | None) -> dict[str, Any]:
    try:
        pattern = f"%{search}%"
        if region_id is not None:
            rows = await db.fetch(
                """
                SELECT c.commune_id, c.name, c.region_id, c.is_active, r.name AS region_name
                FROM communes c JOIN regions r ON r.region_id = c.region_id
                WHERE c.is_active = true AND c.region_id = $1
                  AND c.name ILIKE $2
                ORDER BY c.name ASC LIMIT 50
                """,
                region_id,
                pattern,
            )
        else:
            rows = await db.fetch(
                """
                SELECT c.commune_id, c.name, c.region_id, c.is_active, r.name AS region_name
                FROM communes c JOIN regions r ON r.region_id = c.region_id
                WHERE c.is_active = true AND c.name ILIKE $1
                ORDER BY r.sort_order ASC, c.name ASC LIMIT 50
                """,
                pattern,
            )

        communes: list[CommuneRow] = [
            {
                "commune_id": int(r["commune_id"]),  # type: ignore[call-overload]
                "name": str(r["name"]),
                "region_id": int(r["region_id"]),  # type: ignore[call-overload]
                "is_active": bool(r["is_active"]),
                "region_name": str(r["region_name"]),
            }
            for r in rows
        ]
        return {"communes": communes, "count": len(communes)}
    except Exception as e:
        raise RuntimeError(f"search_communes_failed: {e}") from e
