from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._dlq_models import DLQEntry, DLQListResult


def map_row_to_dlq_entry(row: object) -> DLQEntry:
    r = cast("dict[str, object]", row)

    def to_iso(val: object) -> str:
        if isinstance(val, datetime):
            return val.isoformat()
        return str(val)

    # Cast payload to Dict[str, object]
    raw_payload = r.get("original_payload")
    payload: dict[str, object] = {}
    if isinstance(raw_payload, dict):
        payload = cast("dict[str, object]", raw_payload)
    elif isinstance(raw_payload, str):
        try:
            payload = cast("dict[str, object]", json.loads(raw_payload))
        except Exception:
            payload = {}

    return {
        "dlq_id": int(cast("Any", r["dlq_id"])),
        "booking_id": str(r["booking_id"]) if r.get("booking_id") else None,
        "provider_id": str(r["provider_id"]) if r.get("provider_id") else None,
        "service_id": str(r["service_id"]) if r.get("service_id") else None,
        "failure_reason": str(r["failure_reason"]),
        "last_error_message": str(r["last_error_message"]),
        "last_error_stack": str(r["last_error_stack"]) if r.get("last_error_stack") else None,
        "original_payload": payload,
        "idempotency_key": str(r["idempotency_key"]),
        "status": cast("Literal['pending', 'resolved', 'discarded']", str(r["status"])),
        "created_at": to_iso(r.get("created_at")),
        "updated_at": to_iso(r.get("updated_at")),
        "resolved_at": to_iso(r.get("resolved_at")) if r.get("resolved_at") else None,
        "resolved_by": str(r["resolved_by"]) if r.get("resolved_by") else None,
        "resolution_notes": str(r["resolution_notes"]) if r.get("resolution_notes") else None,
    }


async def list_dlq(db: DBClient, status_filter: str | None) -> DLQListResult:
    status = status_filter if status_filter in ["pending", "resolved", "discarded"] else "pending"
    rows = await db.fetch(
        """
        SELECT * FROM booking_dlq
        WHERE status = $1
        ORDER BY created_at ASC
        LIMIT 100
        """,
        status,
    )
    entries = [map_row_to_dlq_entry(r) for r in rows]
    res: DLQListResult = {"entries": entries, "total": len(entries)}
    return res


async def retry_dlq(db: DBClient, dlq_id: int | None) -> dict[str, Any]:
    if dlq_id is None:
        # Batch retry
        rows = await db.fetch(
            """
            SELECT dlq_id FROM booking_dlq
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 10
            FOR UPDATE SKIP LOCKED
            """
        )
        retried_ids: list[int] = []
        for r in rows:
            await db.execute("UPDATE booking_dlq SET updated_at = NOW() WHERE dlq_id = $1", r["dlq_id"])
            retried_ids.append(int(cast("Any", r["dlq_id"])))
        res_batch: dict[str, Any] = {"retried": retried_ids, "count": len(retried_ids)}
        return res_batch

    # Single retry
    rows = await db.fetch("SELECT dlq_id FROM booking_dlq WHERE dlq_id = $1 AND status = 'pending' FOR UPDATE", dlq_id)
    if not rows:
        raise RuntimeError(f"dlq_entry_not_found_or_not_pending: ID {dlq_id}")

    await db.execute("UPDATE booking_dlq SET updated_at = NOW() WHERE dlq_id = $1", dlq_id)
    res_single: dict[str, Any] = {"retried": [dlq_id]}
    return res_single


async def resolve_dlq(db: DBClient, dlq_id: int, resolved_by: str | None, notes: str | None) -> dict[str, int]:
    res = await db.execute(
        """
        UPDATE booking_dlq
        SET status = 'resolved',
            resolved_at = NOW(),
            resolved_by = $1,
            resolution_notes = $2,
            updated_at = NOW()
        WHERE dlq_id = $3
        """,
        resolved_by,
        notes,
        dlq_id,
    )
    if "UPDATE 1" not in res:
        raise RuntimeError(f"dlq_entry_not_found: ID {dlq_id}")
    return {"resolved": dlq_id}


async def discard_dlq(db: DBClient, dlq_id: int, notes: str | None) -> dict[str, int]:
    res = await db.execute(
        """
        UPDATE booking_dlq
        SET status = 'discarded',
            resolved_at = NOW(),
            resolution_notes = $1,
            updated_at = NOW()
        WHERE dlq_id = $2
        """,
        notes or "Discarded manually",
        dlq_id,
    )
    if "UPDATE 1" not in res:
        raise RuntimeError(f"dlq_entry_not_found: ID {dlq_id}")
    return {"discarded": dlq_id}


async def get_dlq_status_stats(db: DBClient) -> dict[str, int]:
    rows = await db.fetch("SELECT status, COUNT(*) as count FROM booking_dlq GROUP BY status")
    stats: dict[str, int] = {str(r["status"]): int(cast("Any", r["count"])) for r in rows}
    return stats
