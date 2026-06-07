#!/usr/bin/env python3
"""
验证 VINNO 6 综合版 的归属
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, func
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigValue

async def verify():
    async with async_session() as db:
        print("验证 VINNO 6 综合版 的归属")
        print("=" * 80)

        # 查找 VINNO 6 综合版
        result = await db.execute(
            select(ProductModel, ProductSeries)
            .join(ProductSeries, ProductModel.series_id == ProductSeries.id)
            .where(ProductModel.name == "VINNO 6 综合版")
        )
        models = result.fetchall()

        print(f"\n找到 {len(models)} 个 VINNO 6 综合版:")
        for model, series in models:
            result = await db.execute(
                select(func.count()).where(ConfigValue.model_id == model.id)
            )
            cv_count = result.scalar()
            print(f"  - {series.name}: model_id={model.id}, column_start={model.column_start}, configs={cv_count}")

        if len(models) == 1 and models[0][1].name == "Before2023-China":
            print("\n✅ VINNO 6 综合版 正确归属于 Before2023-China")
        else:
            print("\n❌ 归属有问题！")

        # 验证其他关键机型
        print("\n" + "=" * 80)
        print("验证其他关键机型:")

        check_models = [
            "VINNO 5 综合版",
            "VINNO 3EXP_Anesthesia",
            "VINNO 3EXP_POC",
            "VINNO 5PRO_POC"
        ]

        for name in check_models:
            result = await db.execute(
                select(ProductModel, ProductSeries)
                .join(ProductSeries, ProductModel.series_id == ProductSeries.id)
                .where(ProductModel.name == name)
            )
            found = result.fetchall()
            locations = [f"{s.name}" for m, s in found]
            print(f"  {name}: {', '.join(locations)}")

if __name__ == "__main__":
    asyncio.run(verify())
