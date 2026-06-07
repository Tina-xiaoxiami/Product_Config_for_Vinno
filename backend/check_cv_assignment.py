#!/usr/bin/env python3
"""
检查 ConfigValue 的 model_id 归属是否正确
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigValue

async def check_config_value_assignment():
    async with async_session() as db:
        print("ConfigValue model_id 归属检查")
        print("=" * 80)

        # 获取所有系列
        result = await db.execute(select(ProductSeries))
        series_list = result.scalars().all()

        for series in series_list:
            print(f"\n系列: {series.name}")
            print("-" * 80)

            # 获取该系列下的所有型号
            result = await db.execute(
                select(ProductModel).where(ProductModel.series_id == series.id)
            )
            models = result.scalars().all()

            if not models:
                print("  无机型")
                continue

            model_ids = [m.id for m in models]

            # 统计每个型号的 ConfigValue 数量
            for model in models:
                result = await db.execute(
                    select(ConfigValue).where(ConfigValue.model_id == model.id)
                )
                values = result.scalars().all()

                if values:
                    print(f"  ✅ {model.name} (id={model.id}): {len(values)} 个配置值")

                    # 检查这些配置值是否也关联到了其他系列的型号
                    for v in values[:3]:  # 只检查前3个
                        # 获取该配置值关联的其他型号
                        result = await db.execute(
                            select(ConfigValue, ProductModel, ProductSeries)
                            .join(ProductModel, ConfigValue.model_id == ProductModel.id)
                            .join(ProductSeries, ProductModel.series_id == ProductSeries.id)
                            .where(ConfigValue.item_id == v.item_id)
                        )
                        related = result.fetchall()

                        series_names = set([s.name for _, _, s in related])
                        if len(series_names) > 1:
                            print(f"    ⚠️ item_id={v.item_id} 的配置值分布在多个系列: {series_names}")
                else:
                    print(f"  ❌ {model.name} (id={model.id}): 0 个配置值")

        # 专门检查 VINNO 6 综合版
        print("\n" + "=" * 80)
        print("专门检查: VINNO 6 综合版")
        print("-" * 80)

        result = await db.execute(
            select(ProductModel, ProductSeries)
            .join(ProductSeries, ProductModel.series_id == ProductSeries.id)
            .where(ProductModel.name == "VINNO 6 综合版")
        )
        models = result.fetchall()

        for model, series in models:
            result = await db.execute(
                select(ConfigValue).where(ConfigValue.model_id == model.id)
            )
            values = result.scalars().all()
            print(f"  {series.name} / {model.name} (id={model.id}): {len(values)} 个配置值")

            # 显示一些配置值的 item_id
            if values:
                item_ids = [v.item_id for v in values[:5]]
                print(f"    示例 item_ids: {item_ids}")

if __name__ == "__main__":
    asyncio.run(check_config_value_assignment())
