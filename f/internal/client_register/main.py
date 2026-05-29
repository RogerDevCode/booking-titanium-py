# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "asyncpg>=0.30.0",
#   "pydantic>=2.10.0",
#   "beartype>=0.19.0",
#   "returns>=0.24.0"
# ]
# ///
from __future__ import annotations

import logging
from typing import Final

from .._db_client import create_db_client
from .._wmill_adapter import log

MODULE: Final[str] = "client_register"

logger = logging.getLogger(MODULE)


async def _main_async(
    client_id: str,
    name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    pg_url: str | None = None,
) -> dict[str, object]:
    """Update a client record in the clients table.

    Only the provided (non-None) fields are written. Returns updated=False when
    there is nothing to update, so the caller can skip downstream work.
    """
    # Build the SET clause from provided fields
    _ALLOWED_COLS = {"name", "phone", "email"}
    fields: dict[str, str] = {}
    if name is not None:
        fields["name"] = name
    if phone is not None:
        fields["phone"] = phone
    if email is not None:
        fields["email"] = email

    # Sanitise: reject any column not in whitelist
    for col in fields:
        if col not in _ALLOWED_COLS:
            raise ValueError(f"Invalid column for client update: {col}")

    if not fields:
        log("client_register.skip", client_id=client_id, reason="no_fields_provided")
        return {"success": True, "updated": False}

    db = await create_db_client(pg_url)
    try:
        # Build parameterised SET clause: name=$1, phone=$2, …
        set_parts = [f"{col}=${i}" for i, col in enumerate(fields, start=1)]
        set_clause = ", ".join(set_parts)
        # client_id goes after all field values
        client_id_placeholder = f"${len(fields) + 1}"

        query = f"UPDATE clients SET {set_clause}, updated_at=NOW() WHERE client_id={client_id_placeholder}::uuid"
        values: list[object] = list(fields.values())
        values.append(client_id)

        await db.execute(query, *values)
        log("client_register.updated", client_id=client_id, fields=list(fields.keys()))
        return {"success": True, "updated": True}
    finally:
        await db.close()


def main(
    client_id: str,
    name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    pg_url: str | None = None,
) -> dict[str, object]:
    """Windmill entrypoint (sync wrapper — WM-01)."""
    import asyncio

    return asyncio.run(_main_async(client_id=client_id, name=name, phone=phone, email=email, pg_url=pg_url))
