#!/usr/bin/env python3
"""
检查特定机型的系列归属
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select
from app.database import async_session
from app.models import ProductSeries, ProductModel

async def check_specific_models():
    async with async_session() as db:
        print("特定机型归属检查")
        print("=" * 80)

        # 检查 VINNO 6 综合版
        print("\nVINNO 6 综合版:")
        result = await db.execute(
            select(ProductModel, ProductSeries)
            .join(ProductSeries, ProductModel.series_id == ProductSeries.id)
            .where(ProductModel.name == "VINNO 6 综合版")
        )
        rows = result.fetchall()
        for model, series in rows:
            print(f"  - {series.name} (model_id={model.id})")

        # 检查 VINNO 5 综合版
        print("\nVINNO 5 综合版:")
        result = await db.execute(
            select(ProductModel, ProductSeries)
            .join(ProductSeries, ProductModel.series_id == ProductSeries.id)
            .where(ProductModel.name == "VINNO 5 综合版")
        )
        rows = result.fetchall()
        for model, series in rows:
            print(f"  - {series.name} (model_id={model.id})")

        # 列出所有 Before2023-Oversea 的机型
        print("\n" + "=" * 80)
        print("Before2023-Oversea 所有机型:")
        result = await db.execute(
            select(ProductSeries).where(ProductSeries.name == "Before2023-Oversea")
        )
        series = result.scalar_one_or_none()
        if series:
            result = await db.execute(
                select(ProductModel).where(ProductModel.series_id == series.id)
                .order_by(ProductModel.id)
            )
            models = result.scalars().all()
            for model in models:
                print(f"  - {model.name} (id={model.id})")

        # 列出所有 Before2023-China 的机型
        print("\n" + "=" * 80)
        print("Before2023-China 所有机型:")
        result = await db.execute(
            select(ProductSeries).where(ProductSeries.name == "Before2023-China")
        )
        series = result.scalar_one_or_none()
        if series:
            result = await db.execute(
                select(ProductModel).where(ProductModel.series_id == series.id)
                .order_by(ProductModel.id)
            )
            models = result.scalars().all()
            for model in models:
                print(f"  - {model.name} (id={model.id})")

if __name__ == "__main__":
    asyncio.run(check_specific_models())
