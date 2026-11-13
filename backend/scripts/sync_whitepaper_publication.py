"""Preview or register one explicitly scoped, verified whitepaper publication."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.controlled_material_import import CONTROLLED_MATERIALS_ROOT, validate_controlled_materials_root
from app.services.knowledge_whitepaper_publication import sync_publication


async def run(args):
    root = validate_controlled_materials_root(CONTROLLED_MATERIALS_ROOT)
    database = args.database.resolve()
    if not database.is_file():
        raise ValueError("请选择已存在的配置数据库")
    url = f"sqlite+aiosqlite:///{database}" if args.apply else f"sqlite+aiosqlite:///{database.as_uri()}?mode=ro&uri=true"
    engine = create_async_engine(url)
    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    scope = {"product_model_id": args.model_id, "market": args.market,
             "country": args.country, "software_version": args.version}
    try:
        async with AsyncSession(engine) as db:
            return await sync_publication(db, root, args.task, args.receipt, args.product, scope, apply=args.apply)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("database", "task", "receipt"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    for name in ("product", "country", "version"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--model-id", required=True, type=int)
    parser.add_argument("--market", choices=["domestic", "overseas"], required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
