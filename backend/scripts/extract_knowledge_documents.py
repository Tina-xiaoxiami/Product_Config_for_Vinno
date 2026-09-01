"""Batch-extract every active knowledge document into controlled source chunks."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

from sqlalchemy import text


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import async_session, init_db  # noqa: E402
from app.services.knowledge_content import (  # noqa: E402
    KnowledgeContentError,
    extract_registered_document,
)


async def extract_all(*, force: bool) -> int:
    await init_db()
    async with async_session() as session:
        result = await session.execute(
            text(
                """
                SELECT id, title
                FROM knowledge_documents
                WHERE source_status = 'active'
                ORDER BY id
                """
            )
        )
        documents = [(int(row.id), row.title) for row in result]

    failures = 0
    total_chunks = 0
    for document_id, title in documents:
        async with async_session() as session:
            try:
                extraction = await extract_registered_document(
                    session,
                    document_id,
                    force=force,
                )
            except KnowledgeContentError as exc:
                await session.rollback()
                failures += 1
                print(f"FAIL {document_id}: {title} - {exc}")
                continue
        total_chunks += int(extraction["chunk_count"])
        mode = "REUSED" if extraction["reused"] else "DONE"
        print(f"{mode} {document_id}: {title} - {extraction['chunk_count']} chunks")

    print(
        f"SUMMARY documents={len(documents)} failures={failures} "
        f"reported_chunks={total_chunks}"
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-extract unchanged files")
    args = parser.parse_args()
    return asyncio.run(extract_all(force=args.force))


if __name__ == "__main__":
    raise SystemExit(main())
