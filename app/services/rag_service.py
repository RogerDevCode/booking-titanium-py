from typing import List, Optional
from app.domain.protocols import DatabaseClientProtocol

from app.core.logging import logger
from pydantic import BaseModel

class KBEntry(BaseModel):
    title: Optional[str]
    content: str
    category: str
    rank: float
    provider_id: Optional[str] = None

class RAGService:
    """
    Service for Retrieval Augmented Generation.
    Uses Postgres Full-Text Search for efficient Spanish document retrieval.
    """
    
    def __init__(self, db: DatabaseClientProtocol) -> None:
        self._db = db
    
    async def search(self, text: str, provider_id: Optional[str] = None, limit: int = 3) -> List[KBEntry]:
        query = """
            WITH q AS (
                SELECT replace(
                    plainto_tsquery('spanish', immutable_unaccent($1))::text,
                    ' & ', ' | '
                )::tsquery AS query
            )
            SELECT title, category, content, provider_id, ts_rank(search_vector, q.query) AS rank
            FROM knowledge_base, q
            WHERE (provider_id IS NULL OR provider_id = $2::uuid)
              AND is_active = true
              AND q.query @@ search_vector
            ORDER BY rank DESC
            LIMIT $3
        """
        try:
            rows = await self._db.fetch(query, text, provider_id, limit)
            return [
                KBEntry(
                    title=r['title'],
                    content=r['content'],
                    category=r['category'],
                    rank=float(r['rank']),
                    provider_id=str(r['provider_id']) if r['provider_id'] else None
                ) for r in rows
            ]
        except Exception as e:
            logger.error("RAG search failed", error=str(e))
            return []

    def format_context(self, entries: List[KBEntry]) -> str:
        if not entries:
            return ""
        
        context_parts = ["<CONTEXTO_DE_CONOCIMIENTO>"]
        for entry in entries:
            title_part = f"[{entry.title}] " if entry.title else ""
            context_parts.append(f"- {title_part}{entry.content}")
        context_parts.append("</CONTEXTO_DE_CONOCIMIENTO>")
        
        return "\n".join(context_parts)

