"""Import reviewed local fact data into an explicitly selected knowledge database."""
import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.services.knowledge_cart_facts import apply_cart_facts


async def run(database: Path, facts_file: Path) -> dict:
    data = json.loads(facts_file.read_text(encoding="utf-8"))
    engine = create_async_engine(URL.create("sqlite+aiosqlite", database=str(database.resolve(strict=True))))
    try:
        async with AsyncSession(engine) as db, db.begin():
            return await apply_cart_facts(db, data["facts"])
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--facts", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.database, args.facts)), ensure_ascii=False))
