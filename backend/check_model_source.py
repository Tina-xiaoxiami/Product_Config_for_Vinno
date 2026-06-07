#!/usr/bin/env python3
"""
检查 VINNO 6 综合版 在两个系列中的详细信息
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigValue, ConfigItem, ImportHistory

async def check_model_details():
    async with async_session() as db:
        print("VINNO 6 综合版 详细信息对比")
        print("=" * 80)

        # 获取两个 VINNO 6 综合版
        result = await db.execute(
            select(ProductModel, ProductSeries)
            .join(ProductSeries, ProductModel.series_id == ProductSeries.id)
            .where(ProductModel.name == "VINNO 6 综合版")
        )
        models = result.fetchall()

        for model, series in models:
            print(f"\n系列: {series.name} (model_id={model.id})")
            print("-" * 80)
            print(f"  column_start: {model.column_start}")
            print(f"  column_end: {model.column_end}")
            print(f"  sort_order: {model.sort_order}")
            print(f"  created_at: {model.created_at}")

            # 查找导入历史
            result = await db.execute(
                select(ImportHistory)
                .where(ImportHistory.series_id == series.id)
                .order_by(ImportHistory.created_at.desc())
            )
            imports = result.scalars().all()
            print(f"\n  该系列的导入历史:")
            for imp in imports:
                print(f"    - {imp.filename} at {imp.created_at}")

        # 检查是否有导入历史记录了这个型号
        print("\n" + "=" * 80)
        print("所有导入历史:")
        result = await db.execute(
            select(ImportHistory, ProductSeries)
            .join(ProductSeries, ImportHistory.series_id == ProductSeries.id)
            .order_by(ImportHistory.created_at.desc())
        )
        imports = result.fetchall()
        for imp, series in imports:
            print(f"  - {series.name}: {imp.filename} ({imp.records_count}条记录) at {imp.created_at}")

if __name__ == "__main__":
    asyncio.run(check_model_details())
