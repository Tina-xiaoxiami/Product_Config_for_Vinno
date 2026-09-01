"""Document catalog queries and registered-file resolution."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_knowledge_documents(
    session: AsyncSession,
    *,
    query: str | None = None,
    document_type: str | None = None,
    market: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    cleaned_query = str(query or "").strip()
    params = {
        "document_type": document_type,
        "market": market,
        "search_pattern": f"%{cleaned_query}%" if cleaned_query else None,
        "skip": skip,
        "limit": limit,
    }
    filters = """
        source_status = 'active'
        AND (:document_type IS NULL OR document_type = :document_type)
        AND (:market IS NULL OR market = :market)
        AND (
            :search_pattern IS NULL
            OR title LIKE :search_pattern
            OR file_name LIKE :search_pattern
            OR COALESCE(version, '') LIKE :search_pattern
            OR COALESCE(product_series, '') LIKE :search_pattern
        )
    """
    total_result = await session.execute(
        text(f"SELECT COUNT(*) FROM knowledge_documents WHERE {filters}"),
        params,
    )
    result = await session.execute(
        text(
            f"""
            SELECT id, document_type, title, file_name, file_path, version,
                   market, country, product_series, mime_type
            FROM knowledge_documents
            WHERE {filters}
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
            LIMIT :limit OFFSET :skip
            """
        ),
        params,
    )
    items = []
    for row in result:
        path = Path(row.file_path)
        available = path.is_absolute() and path.is_file()
        items.append(
            {
                "id": int(row.id),
                "document_type": row.document_type,
                "title": row.title,
                "file_name": row.file_name,
                "version": row.version,
                "market": row.market,
                "country": row.country,
                "product_series": row.product_series,
                "mime_type": row.mime_type,
                "file_size": path.stat().st_size if available else 0,
                "available": available,
                "preview_url": f"/api/knowledge/documents/{row.id}/preview",
            }
        )
    return items, int(total_result.scalar_one())


async def get_registered_document(
    session: AsyncSession,
    document_id: int,
) -> dict | None:
    result = await session.execute(
        text(
            """
            SELECT id, file_name, file_path, mime_type
            FROM knowledge_documents
            WHERE id = :document_id AND source_status = 'active'
            """
        ),
        {"document_id": document_id},
    )
    row = result.one_or_none()
    if row is None:
        return None
    return {
        "id": int(row.id),
        "file_name": row.file_name,
        "file_path": row.file_path,
        "mime_type": row.mime_type,
    }
