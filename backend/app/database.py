"""
数据库配置
"""
import os
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex

# 数据库路径（锚定到 backend/ 目录，避免依赖启动时的工作目录）
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{BACKEND_ROOT / 'product_config.db'}",
)

# 异步引擎
engine = create_async_engine(DATABASE_URL, echo=False)

# 异步会话工厂
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# 模型基类
Base = declarative_base()


async def get_db():
    """获取数据库会话"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """初始化数据库表"""
    try:
        async with engine.begin() as conn:
            # create_all does not add columns to existing installations.
            columns = await conn.run_sync(
                lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("product_models")}
                if inspect(sync_conn).has_table("product_models") else set()
            )
            if columns and "is_enabled" not in columns:
                await conn.execute(text(
                    "ALTER TABLE product_models ADD COLUMN is_enabled BOOLEAN NOT NULL DEFAULT 1"
                ))
            feature_columns = await conn.run_sync(
                lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("features")}
                if inspect(sync_conn).has_table("features") else set()
            )
            if feature_columns and "probe_matrix_enabled" not in feature_columns:
                await conn.execute(text("ALTER TABLE features ADD COLUMN probe_matrix_enabled BOOLEAN NOT NULL DEFAULT 1"))
            await conn.run_sync(Base.metadata.create_all)
            from app.models.draft import DRAFT_BUSINESS_KEY_INDEX

            await conn.execute(
                CreateIndex(DRAFT_BUSINESS_KEY_INDEX, if_not_exists=True)
            )
    except IntegrityError as error:
        raise RuntimeError(
            "config_drafts 存在重复业务键，已拒绝启动。请先备份数据库并运行 "
            "scripts/migrate_draft_integrity.py --database <明确数据库路径> 检查；"
            "确认仅有完全相同重复后再加 --apply。"
        ) from error
    from app.services.feature_catalog import sync_optional_feature_catalog
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await sync_optional_feature_catalog(session)
        await session.commit()
