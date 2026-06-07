"""
枚举值管理 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

from app.database import get_db
from app.models.config import ConfigValue
from app.schemas.config import EnumValueResponse

router = APIRouter()


@router.get("/extract")
async def extract_enum_values(
    series_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """从现有数据中提取枚举值"""
    # 查询所有配置值
    query = select(ConfigValue)
    result = await db.execute(query)
    values = result.scalars().all()

    # 提取枚举值
    selection_types = set()
    rd_statuses = set()

    for v in values:
        if v.selection_config and v.selection_config not in ['N/A', '', None]:
            selection_types.add(v.selection_config)
        if v.rd_status and v.rd_status not in ['N/A', '', None]:
            rd_statuses.add(v.rd_status)

    return {
        "selection_types": sorted(list(selection_types)),
        "rd_statuses": sorted(list(rd_statuses))
    }


@router.get("/selection-types")
async def get_selection_types(db: AsyncSession = Depends(get_db)):
    """获取选型类别枚举值"""
    query = select(ConfigValue.selection_config).distinct()
    result = await db.execute(query)
    values = [row[0] for row in result.fetchall() if row[0] and row[0] not in ['N/A', '']]
    return {"values": sorted(values)}


@router.get("/rd-statuses")
async def get_rd_statuses(db: AsyncSession = Depends(get_db)):
    """获取研发状态枚举值"""
    query = select(ConfigValue.rd_status).distinct()
    result = await db.execute(query)
    values = [row[0] for row in result.fetchall() if row[0] and row[0] not in ['N/A', '']]
    return {"values": sorted(values)}


@router.get("/config-values")
async def get_config_values(db: AsyncSession = Depends(get_db)):
    """获取当前配置值枚举"""
    query = select(ConfigValue.current_config).distinct()
    result = await db.execute(query)
    current_values = [row[0] for row in result.fetchall() if row[0] and row[0] not in ['N/A', '']]

    query = select(ConfigValue.final_config).distinct()
    result = await db.execute(query)
    final_values = [row[0] for row in result.fetchall() if row[0] and row[0] not in ['N/A', '']]

    all_values = sorted(set(current_values + final_values))
    return {"values": all_values}