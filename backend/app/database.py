"""
数据库配置
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 数据库路径
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./product_config.db")

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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)