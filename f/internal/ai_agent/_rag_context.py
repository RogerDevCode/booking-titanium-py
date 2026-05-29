from typing import TypedDict

from .._db_client import create_db_client


class RAGResult(TypedDict):
    context: str
    count: int
    hasProviderSpecific: bool


async def build_rag_context(provider_id: str | None, text: str, limit: int = 3, pg_url: str | None = None) -> RAGResult:
    # 1. Fetch relevant FAQs from knowledge_base
    # Ensure pg_url is a non-empty string before passing to create_db_client
    clean_pg_url = pg_url if pg_url and str(pg_url).strip() else None
    conn = await create_db_client(clean_pg_url)
    try:
        # Search in public docs OR provider specific docs
        # This uses simple text search for compatibility with the TS version
        rows = await conn.fetch(
            """
            WITH q AS (
                SELECT replace(
                    plainto_tsquery('spanish', immutable_unaccent($2))::text,
                    ' & ', ' | '
                )::tsquery AS query
            )
            SELECT title, category, content, provider_id
            FROM knowledge_base, q
            WHERE (provider_id IS NULL OR provider_id = $1::uuid)
              AND is_active = true
              AND q.query @@ search_vector
            ORDER BY provider_id DESC NULLS LAST, ts_rank(search_vector, q.query) DESC
            LIMIT $3
            """,
            provider_id,
            text,
            limit,
        )

        if not rows:
            return {"context": "", "count": 0, "hasProviderSpecific": False}

        context_parts = ["<KNOWLEDGE_BASE_CONTEXT>"]
        has_provider = False
        for r in rows:
            title = r["title"]
            content = r["content"]
            if title:
                context_parts.append(f"- [{title}] {content}")
            else:
                context_parts.append(f"- {content}")
            if r["provider_id"]:
                has_provider = True
        context_parts.append("</KNOWLEDGE_BASE_CONTEXT>")

        return {"context": "\n".join(context_parts), "count": len(rows), "hasProviderSpecific": has_provider}
    except Exception as e:
        from .._wmill_adapter import log

        log("RAG_CONTEXT_DB_ERROR", error=str(e), file="_rag_context.py")
        # Graceful degradation: return empty context instead of crashing
        return {"context": "", "count": 0, "hasProviderSpecific": False}
    finally:
        await conn.close()


async def get_rag_context(provider_id: str | None, text: str) -> str:
    res = await build_rag_context(provider_id, text)
    return res["context"]
