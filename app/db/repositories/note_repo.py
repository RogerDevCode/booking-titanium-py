from typing import Any, Dict, List, Optional
from app.domain.protocols import DatabaseClientProtocol


class NoteRepository:
    def __init__(self, db: DatabaseClientProtocol) -> None:
        self._db = db

    async def get_tags(self, note_id: int) -> List[Dict[str, Any]]:
        query = """
            SELECT t.id, t.name, t.color
            FROM note_tags nt
            JOIN tags t ON t.id = nt.tag_id
            WHERE nt.note_id = $1
            ORDER BY t.name ASC
        """
        rows = await self._db.fetch(query, note_id)
        return [{"id": r["id"], "name": r["name"], "color": r["color"]} for r in rows]

    async def assign_tags(self, note_id: int, tag_ids: List[int]) -> None:
        if not tag_ids:
            return
        query = """
            INSERT INTO note_tags (note_id, tag_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
        """
        for tid in tag_ids:
            await self._db.execute(query, note_id, tid)

    async def clear_tags(self, note_id: int) -> None:
        await self._db.execute("DELETE FROM note_tags WHERE note_id = $1", note_id)

    async def get_or_create_tag(self, name: str, color: str = "#757575") -> Dict[str, Any]:
        # Normalize tag name to title case or lower case to prevent duplicates
        name_clean = name.strip().title()
        
        # Try to select first
        row = await self._db.fetchrow("SELECT id, name, color FROM tags WHERE name = $1", name_clean)
        if row:
            return {"id": row["id"], "name": row["name"], "color": row["color"]}
            
        # Create if not exists
        query = """
            INSERT INTO tags (name, color)
            VALUES ($1, $2)
            ON CONFLICT (name) DO UPDATE SET color = EXCLUDED.color
            RETURNING id, name, color
        """
        row = await self._db.fetchrow(query, name_clean, color)
        if not row:
            raise RuntimeError(f"Failed to create or update tag: {name_clean}")
        return {"id": row["id"], "name": row["name"], "color": row["color"]}

    async def create_note(
        self,
        provider_id: int,
        booking_id: Optional[int],
        client_id: int,
        content_encrypted: str,
        tag_ids: List[int]
    ) -> Dict[str, Any]:
        query = """
            INSERT INTO service_notes (provider_id, booking_id, client_id, content_encrypted, encryption_version)
            VALUES ($1, $2, $3, $4, 1)
            RETURNING id, provider_id, booking_id, client_id, content_encrypted, encryption_version, created_at, updated_at
        """
        row = await self._db.fetchrow(query, provider_id, booking_id, client_id, content_encrypted)
        if not row:
            raise RuntimeError("Failed to create service note: no row returned")
            
        note_id = row["id"]
        await self.assign_tags(note_id, tag_ids)
        tags = await self.get_tags(note_id)
        
        return {
            "id": note_id,
            "provider_id": row["provider_id"],
            "booking_id": row["booking_id"],
            "client_id": row["client_id"],
            "content_encrypted": row["content_encrypted"],
            "encryption_version": row["encryption_version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "tags": tags
        }

    async def get_note(self, provider_id: int, note_id: int) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM service_notes WHERE id = $1 AND provider_id = $2"
        row = await self._db.fetchrow(query, note_id, provider_id)
        if not row:
            return None
            
        tags = await self.get_tags(note_id)
        return {
            "id": row["id"],
            "provider_id": row["provider_id"],
            "booking_id": row["booking_id"],
            "client_id": row["client_id"],
            "content_encrypted": row["content_encrypted"],
            "encryption_version": row["encryption_version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "tags": tags
        }

    async def list_notes(self, provider_id: int, booking_id: Optional[int] = None) -> List[Dict[str, Any]]:
        query = """
            SELECT sn.*, t.id as tag_id, t.name as tag_name, t.color as tag_color
            FROM service_notes sn
            LEFT JOIN note_tags nt ON nt.note_id = sn.id
            LEFT JOIN tags t ON t.id = nt.tag_id
            WHERE sn.provider_id = $1
        """
        params = [provider_id]
        if booking_id is not None:
            query += " AND sn.booking_id = $2"
            params.append(booking_id)
            
        query += " ORDER BY sn.created_at DESC, t.name ASC"
        rows = await self._db.fetch(query, *params)
        
        notes_dict: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            nid = r["id"]
            if nid not in notes_dict:
                notes_dict[nid] = {
                    "id": nid,
                    "provider_id": r["provider_id"],
                    "booking_id": r["booking_id"],
                    "client_id": r["client_id"],
                    "content_encrypted": r["content_encrypted"],
                    "encryption_version": r["encryption_version"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "tags": []
                }
            if r["tag_id"] is not None:
                notes_dict[nid]["tags"].append({
                    "id": r["tag_id"],
                    "name": r["tag_name"],
                    "color": r["tag_color"]
                })
                
        return list(notes_dict.values())

    async def delete_note(self, provider_id: int, note_id: int) -> bool:
        query = "DELETE FROM service_notes WHERE id = $1 AND provider_id = $2"
        status = await self._db.execute(query, note_id, provider_id)
        return "DELETE 1" in status

    async def list_all_tags(self) -> List[Dict[str, Any]]:
        rows = await self._db.fetch("SELECT id, name, color FROM tags ORDER BY name ASC")
        return [{"id": r["id"], "name": r["name"], "color": r["color"]} for r in rows]
