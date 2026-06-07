"""
版本清理 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from typing import List, Optional
from datetime import datetime, timedelta
import os

from app.database import get_db
from app.models import ConfigVersion, ProductSeries

router = APIRouter()


@router.get("/status")
async def get_storage_status(
    db: AsyncSession = Depends(get_db)
):
    """获取存储状态"""
    # 统计版本数量
    result = await db.execute(select(func.count(ConfigVersion.id)))
    total_versions = result.scalar()

    # 获取数据库大小
    db_path = "product_config.db"
    db_size_mb = 0
    if os.path.exists(db_path):
        db_size_mb = os.path.getsize(db_path) / (1024 * 1024)

    # 按系列统计
    series_result = await db.execute(
        select(ProductSeries.id, ProductSeries.name)
    )
    series_list = series_result.fetchall()

    versions_by_series = []
    for series_id, series_name in series_list:
        count_result = await db.execute(
            select(func.count(ConfigVersion.id)).where(ConfigVersion.series_id == series_id)
        )
        count = count_result.scalar()
        versions_by_series.append({
            'series_id': series_id,
            'series_name': series_name,
            'version_count': count
        })

    return {
        'total_versions': total_versions,
        'db_size_mb': round(db_size_mb, 2),
        'versions_by_series': versions_by_series
    }


@router.get("/check-policy")
async def check_version_policy(
    db: AsyncSession = Depends(get_db)
):
    """
    检查版本是否符合保留策略

    策略：
    - 近1个月（30天）：全部保留
    - 超过1个月：每半个月（15天）保留1个版本
    """
    now = datetime.utcnow()
    one_month_ago = now - timedelta(days=30)

    # 获取所有版本，按系列分组
    result = await db.execute(
        select(ConfigVersion)
        .order_by(ConfigVersion.series_id, ConfigVersion.published_at.desc())
    )
    all_versions = result.scalars().all()

    # 按系列分组
    versions_by_series = {}
    for v in all_versions:
        if v.series_id not in versions_by_series:
            versions_by_series[v.series_id] = []
        versions_by_series[v.series_id].append(v)

    # 分析每个系列的版本
    versions_to_keep = set()
    versions_to_remove = []

    for series_id, versions in versions_by_series.items():
        for i, v in enumerate(versions):
            if v.published_at >= one_month_ago:
                # 近1个月，全部保留
                versions_to_keep.add(v.id)
            else:
                # 超过1个月，检查是否是半个月内的第一个版本
                days_ago = (now - v.published_at).days
                period_start = (days_ago // 15) * 15
                period_end = period_start + 15

                # 找到该周期内是否有更新的版本已保留
                period_versions = [
                    vv for vv in versions
                    if period_start <= (now - vv.published_at).days < period_end
                    and vv.series_id == series_id
                ]

                if period_versions:
                    # 保留该周期内最新的版本
                    period_versions.sort(key=lambda x: x.published_at, reverse=True)
                    if period_versions[0].id == v.id:
                        versions_to_keep.add(v.id)
                    else:
                        versions_to_remove.append({
                            'id': v.id,
                            'version_number': v.version_number,
                            'published_at': v.published_at.isoformat(),
                            'days_ago': days_ago
                        })
                else:
                    versions_to_remove.append({
                        'id': v.id,
                        'version_number': v.version_number,
                        'published_at': v.published_at.isoformat(),
                        'days_ago': days_ago
                    })

    return {
        'total_versions': len(all_versions),
        'versions_to_keep': len(versions_to_keep),
        'versions_to_remove': len(versions_to_remove),
        'removal_list': versions_to_remove,
        'policy': {
            'recent_days': 30,
            'period_days': 15
        }
    }


@router.post("/cleanup")
async def cleanup_old_versions(
    dry_run: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """
    清理旧版本

    Args:
        dry_run: 如果为True，只返回将被删除的版本，不实际删除
    """
    # 获取清理建议
    check_result = await check_version_policy(db)
    versions_to_remove = [v['id'] for v in check_result['removal_list']]

    if dry_run:
        return {
            'dry_run': True,
            'would_remove': len(versions_to_remove),
            'removal_list': check_result['removal_list']
        }

    # 实际删除
    if versions_to_remove:
        await db.execute(
            delete(ConfigVersion).where(ConfigVersion.id.in_(versions_to_remove))
        )
        await db.commit()

    return {
        'dry_run': False,
        'removed': len(versions_to_remove),
        'removed_ids': versions_to_remove
    }


@router.post("/archive/{version_id}")
async def archive_version(
    version_id: int,
    db: AsyncSession = Depends(get_db)
):
    """归档版本（标记为已归档，不删除）"""
    result = await db.execute(select(ConfigVersion).where(ConfigVersion.id == version_id))
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")

    # 这里可以添加归档逻辑，比如移动到归档存储
    # 目前只是标记
    # 如果需要，可以在ConfigVersion模型中添加status字段

    return {"message": "版本已归档", "version_id": version_id}