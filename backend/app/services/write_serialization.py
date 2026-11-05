"""Serialize catalog validation and writes in their caller-owned transaction."""
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import OperationalError


async def serialize_catalog_write(db, table: str) -> None:
    if table not in {'product_models', 'category_applications', 'features'}:
        raise ValueError('Unsupported catalog lock')
    dialect = db.get_bind().dialect.name
    # Reuse the probe publishing no-op UPDATE pattern. SQLite acquires its
    # writer lock even when no rows match; no records or timestamps are changed.
    if dialect == 'sqlite':
        statement = f'UPDATE {table} SET id = id WHERE 0'
    elif dialect == 'postgresql':
        statement = f'LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE'
    else:
        raise ValueError('Catalog write serialization requires SQLite or PostgreSQL')
    try:
        with db.no_autoflush:
            await db.execute(text(statement))
    except OperationalError as error:
        raise HTTPException(409, '数据正在更新或暂时无法写入，请刷新后重试') from error
