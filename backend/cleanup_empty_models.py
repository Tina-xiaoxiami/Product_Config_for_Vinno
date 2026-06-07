#!/usr/bin/env python3
"""
清理 Before2023-China 系列中配置为空的错误机型
这些机型本应在 Before2023-Oversea 系列中
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, delete
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigValue

async def cleanup_empty_models():
    async with async_session() as db:
        print("开始清理 Before2023-China 系列中的空配置机型...")
        print("=" * 80)

        # 获取 Before2023-China 系列
        result = await db.execute(
            select(ProductSeries).where(ProductSeries.name == "Before2023-China")
        )
        series = result.scalar_one_or_none()

        if not series:
            print("❌ 未找到 Before2023-China 系列")
            return

        print(f"系列: {series.name} (id={series.id})")

        # 获取该系列下所有机型
        result = await db.execute(
            select(ProductModel).where(ProductModel.series_id == series.id)
        )
        models = result.scalars().all()

        # 找出配置值为空的机型
        empty_models = []
        for model in models:
            # 检查配置值数量
            result = await db.execute(
                select(ConfigValue).where(ConfigValue.model_id == model.id)
            )
            values = result.scalars().all()

            if len(values) == 0:
                empty_models.append(model)
                print(f"  ⚠️ {model.name} (id={model.id}): 0 个配置值 - 准备删除")

        if not empty_models:
            print("✅ 没有需要删除的空配置机型")
            return

        print(f"\n共发现 {len(empty_models)} 个空配置机型")
        print("-" * 80)

        # 删除这些机型
        deleted_count = 0
        for model in empty_models:
            try:
                # 由于 ConfigValue 是空的，直接删除型号即可
                await db.delete(model)
                print(f"  ✅ 已删除: {model.name} (id={model.id})")
                deleted_count += 1
            except Exception as e:
                print(f"  ❌ 删除失败 {model.name}: {e}")

        await db.commit()
        print("-" * 80)
        print(f"清理完成: 已删除 {deleted_count} 个空配置机型")

        # 验证清理结果
        result = await db.execute(
            select(ProductModel).where(ProductModel.series_id == series.id)
        )
        remaining_models = result.scalars().all()
        print(f"\nBefore2023-China 系列剩余机型数量: {len(remaining_models)}")
        for model in remaining_models:
            result = await db.execute(
                select(ConfigValue).where(ConfigValue.model_id == model.id)
            )
            values = result.scalars().all()
            print(f"  - {model.name}: {len(values)} 个配置值")

if __name__ == "__main__":
    asyncio.run(cleanup_empty_models())
