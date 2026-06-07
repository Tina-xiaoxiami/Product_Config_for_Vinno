#!/usr/bin/env python3
"""
检查数据库中机型的列位置信息
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select
from app.database import async_session
from app.models import ProductSeries, ProductModel

async def check_model_columns():
    async with async_session() as db:
        print("机型列位置信息检查")
        print("=" * 80)

        # 获取所有系列
        result = await db.execute(select(ProductSeries))
        series_list = result.scalars().all()

        for series in series_list:
            print(f"\n系列: {series.name}")
            print("-" * 80)

            result = await db.execute(
                select(ProductModel)
                .where(ProductModel.series_id == series.id)
                .order_by(ProductModel.column_start)
            )
            models = result.scalars().all()

            for model in models:
                print(f"  {model.name}:")
                print(f"    column_start: {model.column_start}, column_end: {model.column_end}")

                # 检查列范围是否与其他系列的机型重叠
                result = await db.execute(
                    select(ProductModel, ProductSeries)
                    .join(ProductSeries, ProductModel.series_id == ProductSeries.id)
                    .where(
                        ProductModel.series_id != series.id,
                        ProductModel.column_start == model.column_start
                    )
                )
                overlaps = result.fetchall()
                for other_model, other_series in overlaps:
                    print(f"    ⚠️ 列位置与 {other_series.name}/{other_model.name} 相同!")

if __name__ == "__main__":
    asyncio.run(check_model_columns())
