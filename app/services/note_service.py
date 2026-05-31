from typing import Any, Dict, List, Optional
from app.domain.protocols import NoteRepositoryProtocol
from app.core.crypto import encrypt_data, decrypt_data

class NoteService:
    def __init__(self, repo: NoteRepositoryProtocol) -> None:
        self._repo = repo

    async def create_note(
        self,
        provider_id: int,
        booking_id: Optional[int],
        client_id: int,
        content: str,
        tag_names: List[str]
    ) -> Dict[str, Any]:
        # 1. Normalize tags (get or create by name)
        tag_ids: List[int] = []
        for name in tag_names:
            if name.strip():
                tag = await self._repo.get_or_create_tag(name)
                tag_ids.append(tag["id"])
                
        # 2. Encrypt plaintext note content
        content_encrypted = encrypt_data(content)
        
        # 3. Create the note record
        note = await self._repo.create_note(
            provider_id=provider_id,
            booking_id=booking_id,
            client_id=client_id,
            content_encrypted=content_encrypted,
            tag_ids=tag_ids
        )
        
        # 4. Return note with plaintext content decrypted back for response
        note["content"] = content
        return note

    async def get_note(self, provider_id: int, note_id: int) -> Optional[Dict[str, Any]]:
        note = await self._repo.get_note(provider_id, note_id)
        if not note:
            return None
            
        # Decrypt ciphertext content
        try:
            note["content"] = decrypt_data(note["content_encrypted"])
        except Exception:
            note["content"] = "[ERROR: Unable to decrypt note]"
            
        return note

    async def list_notes(self, provider_id: int, booking_id: Optional[int] = None) -> List[Dict[str, Any]]:
        notes = await self._repo.list_notes(provider_id, booking_id)
        for note in notes:
            try:
                note["content"] = decrypt_data(note["content_encrypted"])
            except Exception:
                note["content"] = "[ERROR: Unable to decrypt note]"
        return notes

    async def delete_note(self, provider_id: int, note_id: int) -> bool:
        return await self._repo.delete_note(provider_id, note_id)

    async def list_tags(self) -> List[Dict[str, Any]]:
        return await self._repo.list_all_tags()
