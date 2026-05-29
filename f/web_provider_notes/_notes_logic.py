from datetime import datetime
from typing import Any

from ..internal._crypto import decrypt_data, encrypt_data
from ..internal._result import DBClient
from ._notes_models import NoteRow, Tag


def decrypt_content(encrypted: str | None) -> str:
    if not encrypted:
        return ""
    try:
        return decrypt_data(encrypted)
    except Exception as e:
        from ..internal._wmill_adapter import log

        log("SILENT_ERROR_CAUGHT", error=str(e), file="_notes_logic.py")
        return "[ERROR: Unable to decrypt note]"


def map_row_to_note(r: dict[str, Any], tags: list[Tag] | None = None) -> NoteRow:
    if tags is None:
        tags = []
    enc = str(r["content_encrypted"]) if r.get("content_encrypted") else None
    return {
        "note_id": str(r["note_id"]),
        "booking_id": str(r["booking_id"]) if r.get("booking_id") else None,
        "client_id": str(r["client_id"]) if r.get("client_id") else None,
        "provider_id": str(r["provider_id"]),
        "content_encrypted": enc,
        "encryption_version": int(r["encryption_version"]),
        "created_at": r["created_at"].isoformat()
        if isinstance(r.get("created_at"), datetime)
        else str(r.get("created_at")),
        "updated_at": r["updated_at"].isoformat()
        if isinstance(r.get("updated_at"), datetime)
        else str(r.get("updated_at")),
        "content": decrypt_content(enc),
        "tags": tags,
    }


class NoteRepository:
    def __init__(self, db: DBClient) -> None:
        self.db = db

    async def get_tags(self, note_id: str) -> list[Tag]:
        rows = await self.db.fetch(
            """
            SELECT t.tag_id, t.name, t.color
            FROM note_tags nt
            JOIN tags t ON t.tag_id = nt.tag_id
            WHERE nt.note_id = $1::uuid
            ORDER BY t.name ASC
            """,
            note_id,
        )
        return [{"tag_id": str(r["tag_id"]), "name": str(r["name"]), "color": str(r["color"])} for r in rows]

    async def assign_tags(self, note_id: str, tag_ids: list[str]) -> None:
        if not tag_ids:
            return
        # Simple loop for safety/clarity in this phase
        for tid in tag_ids:
            await self.db.execute(
                "INSERT INTO note_tags (note_id, tag_id) VALUES ($1::uuid, $2::uuid) ON CONFLICT DO NOTHING",
                note_id,
                tid,
            )

    async def create(
        self, provider_id: str, booking_id: str, client_id: str, content: str, tag_ids: list[str]
    ) -> NoteRow:
        try:
            encrypted = encrypt_data(content)
            version = 1

            rows = await self.db.fetch(
                """
                INSERT INTO service_notes (provider_id, booking_id, client_id, content_encrypted, encryption_version)
                VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5)
                RETURNING *
                """,
                provider_id,
                booking_id,
                client_id,
                encrypted,
                version,
            )
            if not rows:
                raise RuntimeError("create_failed")

            note_id = str(rows[0]["note_id"])
            await self.assign_tags(note_id, tag_ids)
            tags = await self.get_tags(note_id)
            return map_row_to_note(rows[0], tags)
        except Exception as e:
            raise RuntimeError(f"create_failed: {e}") from e

    async def read(self, provider_id: str, note_id: str) -> NoteRow:
        rows = await self.db.fetch(
            "SELECT * FROM service_notes WHERE note_id = $1::uuid AND provider_id = $2::uuid LIMIT 1",
            note_id,
            provider_id,
        )
        if not rows:
            raise RuntimeError("Note not found or access denied")
        tags = await self.get_tags(note_id)
        return map_row_to_note(rows[0], tags)

    async def list_notes(self, provider_id: str, booking_id: str | None) -> list[NoteRow]:
        try:
            query = """
                SELECT sn.*, t.tag_id, t.name as tag_name, t.color as tag_color
                FROM service_notes sn
                LEFT JOIN note_tags nt ON nt.note_id = sn.note_id
                LEFT JOIN tags t ON t.tag_id = nt.tag_id
                WHERE sn.provider_id = $1::uuid
            """
            params = [provider_id]
            if booking_id:
                query += " AND sn.booking_id = $2::uuid"
                params.append(booking_id)

            query += " ORDER BY sn.created_at DESC, t.name ASC LIMIT 200"
            rows = await self.db.fetch(query, *params)

            note_map: dict[str, NoteRow] = {}
            for r in rows:
                nid = str(r["note_id"])
                if nid not in note_map:
                    note_map[nid] = map_row_to_note(r, [])

                if r.get("tag_id"):
                    note_map[nid]["tags"].append(
                        {"tag_id": str(r["tag_id"]), "name": str(r["tag_name"]), "color": str(r["tag_color"])}
                    )

            return list(note_map.values())
        except Exception as e:
            raise RuntimeError(f"list_failed: {e}") from e

    async def delete(self, provider_id: str, note_id: str) -> dict[str, bool]:
        res = await self.db.execute(
            "DELETE FROM service_notes WHERE note_id = $1::uuid AND provider_id = $2::uuid", note_id, provider_id
        )
        if "DELETE 1" not in res:
            raise RuntimeError("Note not found or access denied")
        return {"deleted": True}
