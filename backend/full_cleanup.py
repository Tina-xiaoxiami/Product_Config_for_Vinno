#!/usr/bin/env python3
"""
完整清理方案
区分：
1. 业务上正常的重复（如 VINNO 5 同时在 China 和 Oversea，这是正常的）
2. 导入错误导致的重复（如 VINNO 6 综合版在 Oversea 中，这是错误的）
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, func, delete
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigValue

async def full_cleanup():
    async with async_session() as db:
        print("完整清理方案")
        print("=" * 80)

        # 获取 Before2023-China 的机型
        result = await db.execute(
            select(ProductSeries).where(ProductSeries.name == "Before2023-China")
        )
        china_series = result.scalar_one_or_none()

        # 获取 Before2023-Oversea 的机型
        result = await db.execute(
            select(ProductSeries).where(ProductSeries.name == "Before2023-Oversea")
        )
        oversea_series = result.scalar_one_or_none()

        if not china_series or not oversea_series:
            print("系列不存在")
            return

        # 获取两个系列的机型
        result = await db.execute(
            select(ProductModel).where(ProductModel.series_id == china_series.id)
        )
        china_models = {m.name: m for m in result.scalars().all()}

        result = await db.execute(
            select(ProductModel).where(ProductModel.series_id == oversea_series.id)
        )
        oversea_models = {m.name: m for m in result.scalars().all()}

        print(f"Before2023-China: {len(china_models)} 个机型")
        print(f"Before2023-Oversea: {len(oversea_models)} 个机型")

        # 找出重复的机型名
        common_names = set(china_models.keys()) & set(oversea_models.keys())

        print(f"\n两个系列共有的机型: {len(common_names)} 个")
        print("-" * 80)

        # 分析每个重复机型
        delete_candidates = []

        for name in sorted(common_names):
            china_model = china_models[name]
            oversea_model = oversea_models[name]

            # 获取配置值数量
            result = await db.execute(
                select(func.count()).where(ConfigValue.model_id == china_model.id)
            )
            china_configs = result.scalar()

            result = await db.execute(
                select(func.count()).where(ConfigValue.model_id == oversea_model.id)
            )
            oversea_configs = result.scalar()

            print(f"\n{name}:")
            print(f"  China (id={china_model.id}): {china_configs}配置值, col={china_model.column_start}")
            print(f"  Oversea (id={oversea_model.id}): {oversea_configs}配置值, col={oversea_model.column_start}")

            # 判断是否应该删除
            # 规则：如果 China 系列的 column_start 较小（先导入的），且该机型是 China 专属
            # 则删除 Oversea 中的重复

            # 检查是否是 China 专属机型（不应该出现在 Oversea）
            is_china_exclusive = any(kw in name for kw in ['综合版']) or \
                                   any(suffix in name for suffix in ['_POC', '_Anesthesia'])

            # 检查是否是 Oversea 专属机型（不应该出现在 China）
            is_oversea_exclusive = any(suffix in name for suffix in ['_BRA', '_RUA', '_EXP', '_PRO', '_S'])

            if is_china_exclusive and china_model.id < oversea_model.id:
                print(f"  ⚠️ 建议删除 Oversea 中的 {name}（China专属）")
                delete_candidates.append({
                    'model': oversea_model,
                    'reason': 'China专属机型错误出现在Oversea',
                    'configs': oversea_configs
                })
            elif is_oversea_exclusive and oversea_model.id < china_model.id:
                print(f"  ⚠️ 建议删除 China 中的 {name}（Oversea专属）")
                delete_candidates.append({
                    'model': china_model,
                    'reason': 'Oversea专属机型错误出现在China',
                    'configs': china_configs
                })
            else:
                print(f"  ✅ 保留两个（正常业务需求）")

        # 执行删除
        if delete_candidates:
            print("\n" + "=" * 80)
            print(f"准备删除 {len(delete_candidates)} 个机型")

            for item in delete_candidates:
                print(f"  - {item['model'].name} (series_id={item['model'].series_id}, configs={item['configs']}) - {item['reason']}")

            # 确认后执行删除
            print("\n执行删除...")
            deleted = 0
            for item in delete_candidates:
                try:
                    # 删除配置值
                    await db.execute(
                        delete(ConfigValue).where(ConfigValue.model_id == item['model'].id)
                    )
                    # 删除机型
                    await db.delete(item['model'])
                    deleted += 1
                    print(f"  ✅ 已删除 {item['model'].name}")
                except Exception as e:
                    print(f"  ❌ 删除失败: {e}")

            await db.commit()
            print(f"\n删除完成: 共删除 {deleted} 个机型")
        else:
            print("\n没有需要删除的机型")

        # 最终统计
        print("\n" + "=" * 80)
        print("清理后统计:")

        result = await db.execute(
            select(ProductModel).where(ProductModel.series_id == china_series.id)
        )
        china_count = len(result.scalars().all())

        result = await db.execute(
            select(ProductModel).where(ProductModel.series_id == oversea_series.id)
        )
        oversea_count = len(result.scalars().all())

        print(f"Before2023-China: {china_count} 个机型")
        print(f"Before2023-Oversea: {oversea_count} 个机型")

if __name__ == "__main__":
    asyncio.run(full_cleanup())
