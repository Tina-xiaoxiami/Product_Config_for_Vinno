#!/usr/bin/env python3
"""
检查 ConfigValue 关联的 Model 是否正确
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, func
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigValue, ConfigItem

async def check_cv_model_relation():
    async with async_session() as db:
        print("ConfigValue 关联关系检查")
        print("=" * 80)

        # 获取 VINNO 6 综合版 在两个系列中的 model_id
        result = await db.execute(
            select(ProductModel, ProductSeries)
            .join(ProductSeries, ProductModel.series_id == ProductSeries.id)
            .where(ProductModel.name == "VINNO 6 综合版")
        )
        models = result.fetchall()

        print("\nVINNO 6 综合版 的 model_id:")
        for model, series in models:
            print(f"  - {series.name}: model_id={model.id}")

        # 检查每个 model_id 的 ConfigValue 数量
        print("\n各 model_id 的配置值数量:")
        for model, series in models:
            result = await db.execute(
                select(func.count()).where(ConfigValue.model_id == model.id)
            )
            count = result.scalar()
            print(f"  - {series.name} (model_id={model.id}): {count} 个配置值")

        # 随机检查一些 ConfigValue 的 item_id
        print("\n随机检查 ConfigValue 详情:")
        for model, series in models:
            result = await db.execute(
                select(ConfigValue, ConfigItem)
                .join(ConfigItem, ConfigValue.item_id == ConfigItem.id)
                .where(ConfigValue.model_id == model.id)
                .limit(3)
            )
            values = result.fetchall()
            print(f"\n  {series.name} (model_id={model.id}):")
            for cv, item in values:
                print(f"    - item_id={cv.item_id}, ipn={item.ipn}, rd_name={item.rd_name}")

        # 检查 Before2023-China 中的海外机型
        print("\n" + "=" * 80)
        print("Before2023-China 中的可疑机型:")

        result = await db.execute(
            select(ProductSeries).where(ProductSeries.name == "Before2023-China")
        )
        china_series = result.scalar_one_or_none()

        if china_series:
            result = await db.execute(
                select(ProductModel).where(ProductModel.series_id == china_series.id)
            )
            china_models = result.scalars().all()

            # 获取 Before2023-Oversea 的机型名称
            result = await db.execute(
                select(ProductSeries).where(ProductSeries.name == "Before2023-Oversea")
            )
            oversea_series = result.scalar_one_or_none()

            if oversea_series:
                result = await db.execute(
                    select(ProductModel.name).where(ProductModel.series_id == oversea_series.id)
                )
                oversea_model_names = set([r[0] for r in result.fetchall()])

                # 检查 China 中是否有只在 Oversea 应该出现的机型
                for model in china_models:
                    if model.name in oversea_model_names and model.name not in [
                        "VINNO 5", "VINNO 5PRO", "VINNO 3EXP", "VINNO 3", "VINNO 6",
                        "VINNO 6 综合版", "VINNO 5 综合版"
                    ]:
                        print(f"  ⚠️ {model.name} (id={model.id}) 可能不应该在 China 系列")

if __name__ == "__main__":
    asyncio.run(check_cv_model_relation())
