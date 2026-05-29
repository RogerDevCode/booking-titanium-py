from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._rag_models import KBEntry

# FTS español sobre knowledge_base.search_vector (columna generada, índice GIN).
#
# AND→OR: plainto_tsquery produce lexemas unidos por ' & ' (exige TODOS los
# términos). Para retrieval de FAQ queremos rankear por cuántos términos
# coinciden, no exigir la intersección completa → reemplazamos ' & ' por ' | '.
# Castear plainto_tsquery::text de vuelta a ::tsquery es seguro: plainto_tsquery
# sanitiza la entrada del usuario (no admite inyección de sintaxis tsquery).
# Query vacía / solo stopwords → tsquery vacío → 0 filas (degradación limpia).
_FTS_SQL = """
WITH q AS (
    SELECT replace(
        plainto_tsquery('spanish', immutable_unaccent($1))::text,
        ' & ', ' | '
    )::tsquery AS query
)
SELECT kb_id, category, title, content,
       ts_rank(search_vector, q.query) AS rank
FROM knowledge_base, q
WHERE is_active = true
  AND ($2::text IS NULL OR category = $2)
  AND q.query @@ search_vector
ORDER BY rank DESC
LIMIT $3
"""


class KBRepository:
    def __init__(self, db: DBClient) -> None:
        self.db = db

    async def search(self, query: str, top_k: int, category: str | None = None) -> list[KBEntry]:
        """FTS español (stemming + stopwords + unaccent simétrico) rankeado por ts_rank."""
        try:
            rows = await self.db.fetch(_FTS_SQL, query, category, top_k)
        except Exception as e:
            raise RuntimeError(f"kb_fts_failed: {e}") from e

        result: list[KBEntry] = [
            {
                "kb_id": str(r["kb_id"]),
                "category": str(r["category"]),
                "title": str(r["title"]),
                "content": str(r["content"]),
                "similarity": float(str(r["rank"])),
            }
            for r in rows
        ]
        return result
