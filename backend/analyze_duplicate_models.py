#!/usr/bin/env python3
"""
分析 VINNO 6 综合版 在两个系列中的区别
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, func
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigValue, ConfigItem

async def analyze_duplicate_models():
    async with async_session() as db:
        print("VINNO 6 综合版 在两个系列中的对比")
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

            # 统计配置值
            result = await db.execute(
                select(func.count()).where(ConfigValue.model_id == model.id)
            )
            count = result.scalar()
            print(f"配置值数量: {count}")

            # 获取部分配置值示例
            result = await db.execute(
                select(ConfigValue, ConfigItem)
                .join(ConfigItem, ConfigValue.item_id == ConfigItem.id)
                .where(ConfigValue.model_id == model.id)
                .limit(5)
            )
            values = result.fetchall()

            print("配置示例:")
            for cv, item in values:
                print(f"  - {item.rd_name}: final={cv.final_config}, current={cv.current_config}")

        # 检查两个机型的配置值是否完全相同
        if len(models) == 2:
            model1, series1 = models[0]
            model2, series2 = models[1]

            print("\n" + "=" * 80)
            print("配置对比分析")
            print("-" * 80)

            # 获取两个机型的所有配置值
            result = await db.execute(
                select(ConfigValue.item_id, ConfigValue.final_config)
                .where(ConfigValue.model_id == model1.id)
            )
            values1 = {v.item_id: v.final_config for v in result.fetchall()}

            result = await db.execute(
                select(ConfigValue.item_id, ConfigValue.final_config)
                .where(ConfigValue.model_id == model2.id)
            )
            values2 = {v.item_id: v.final_config for v in result.fetchall()}

            # 对比
            common_items = set(values1.keys()) & set(values2.keys())
            different = []
            same = []

            for item_id in common_items:
                if values1[item_id] != values2[item_id]:
                    different.append(item_id)
                else:
                    same.append(item_id)

            print(f"共同配置项: {len(common_items)}")
            print(f"相同配置: {len(same)}")
            print(f"不同配置: {len(different)}")

            if different:
                print("\n部分不同配置的示例:")
                for item_id in different[:3]:
                    result = await db.execute(
                        select(ConfigItem).where(ConfigItem.id == item_id)
                    )
                    item = result.scalar_one()
                    print(f"  - {item.rd_name}:")
                    print(f"    {series1.name}: {values1[item_id]}")
                    print(f"    {series2.name}: {values2[item_id]}")

if __name__ == "__main__":
    asyncio.run(analyze_duplicate_models())
