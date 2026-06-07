#!/usr/bin/env python3
"""
清理真正错误归属的机型
基于业务规则：
1. 带 _BRA, _RUA 等海外后缀的应该在 Oversea 系列，不应该在 China
2. 带 _EXP, _PRO, _S, _POC 后缀的如果是海外专属，应该在 Oversea
3. 基础机型（VINNO 5, VINNO 6 等）可以在两个系列中
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, func, delete
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigValue

async def cleanup_wrong_models():
    async with async_session() as db:
        print("清理错误归属的机型")
        print("=" * 80)

        # 定义海外专属后缀
        oversea_suffixes = ['_BRA', '_RUA', '_USA', '_EUR', '_JPN', '_KOR']
        china_only_keywords = ['CHN', 'CN', '中国']

        wrong_models = []

        # 获取所有 Before2023-China 的机型
        result = await db.execute(
            select(ProductSeries).where(ProductSeries.name == "Before2023-China")
        )
        china_series = result.scalar_one_or_none()

        if china_series:
            result = await db.execute(
                select(ProductModel).where(ProductModel.series_id == china_series.id)
            )
            china_models = result.scalars().all()

            print(f"\nBefore2023-China 系列中的可疑机型:")
            for model in china_models:
                # 检查是否包含海外专属后缀
                for suffix in oversea_suffixes:
                    if suffix in model.name:
                        # 统计配置值
                        result = await db.execute(
                            select(func.count()).where(ConfigValue.model_id == model.id)
                        )
                        cv_count = result.scalar()
                        wrong_models.append({
                            'model': model,
                            'reason': f'包含海外后缀{suffix}',
                            'cv_count': cv_count
                        })
                        print(f"  ⚠️ {model.name} (id={model.id}): {cv_count}配置值 - 包含海外后缀{suffix}")
                        break

        # 获取所有 Before2023-Oversea 的机型
        result = await db.execute(
            select(ProductSeries).where(ProductSeries.name == "Before2023-Oversea")
        )
        oversea_series = result.scalar_one_or_none()

        if oversea_series:
            result = await db.execute(
                select(ProductModel).where(ProductModel.series_id == oversea_series.id)
            )
            oversea_models = result.scalars().all()

            print(f"\nBefore2023-Oversea 系列中的可疑机型:")
            for model in oversea_models:
                # 检查是否包含中国专属关键字
                for kw in china_only_keywords:
                    if kw in model.name:
                        result = await db.execute(
                            select(func.count()).where(ConfigValue.model_id == model.id)
                        )
                        cv_count = result.scalar()
                        wrong_models.append({
                            'model': model,
                            'reason': f'包含中国关键字{kw}',
                            'cv_count': cv_count
                        })
                        print(f"  ⚠️ {model.name} (id={model.id}): {cv_count}配置值 - 包含中国关键字{kw}")
                        break

        print(f"\n共发现 {len(wrong_models)} 个错误归属的机型")

        if wrong_models:
            print("\n" + "=" * 80)
            print("准备删除以下机型及其配置值:")
            for item in wrong_models:
                print(f"  - {item['model'].name} (id={item['model'].id}, configs={item['cv_count']}) - {item['reason']}")

            # 执行删除
            print("\n执行删除...")
            deleted_count = 0
            for item in wrong_models:
                try:
                    # 删除配置值
                    await db.execute(
                        delete(ConfigValue).where(ConfigValue.model_id == item['model'].id)
                    )
                    # 删除机型
                    await db.delete(item['model'])
                    deleted_count += 1
                    print(f"  ✅ 已删除 {item['model'].name}")
                except Exception as e:
                    print(f"  ❌ 删除 {item['model'].name} 失败: {e}")

            await db.commit()
            print(f"\n删除完成: 共删除 {deleted_count} 个机型")
        else:
            print("\n没有发现错误归属的机型")

if __name__ == "__main__":
    asyncio.run(cleanup_wrong_models())
