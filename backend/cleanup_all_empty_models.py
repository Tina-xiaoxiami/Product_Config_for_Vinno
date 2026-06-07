#!/usr/bin/env python3
"""
清理所有系列中配置为空的机型
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, func
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigValue

async def cleanup_all_empty_models():
    async with async_session() as db:
        print("开始清理所有系列中的空配置机型...")
        print("=" * 80)

        # 获取所有系列
        result = await db.execute(select(ProductSeries))
        series_list = result.scalars().all()

        total_deleted = 0
        all_empty_models = []

        for series in series_list:
            print(f"\n检查系列: {series.name}")

            # 获取该系列下所有机型
            result = await db.execute(
                select(ProductModel).where(ProductModel.series_id == series.id)
            )
            models = result.scalars().all()

            series_empty = []
            for model in models:
                # 检查配置值数量
                cv_count_result = await db.execute(
                    select(func.count()).where(ConfigValue.model_id == model.id)
                )
                cv_count = cv_count_result.scalar()

                if cv_count == 0:
                    series_empty.append(model)
                    all_empty_models.append((series.name, model.name, model.id))

            if series_empty:
                print(f"  发现 {len(series_empty)} 个空配置机型:")
                for model in series_empty:
                    print(f"    - {model.name} (id={model.id})")
                    await db.delete(model)
                    total_deleted += 1
            else:
                print(f"  ✅ 没有空配置机型")

        if total_deleted > 0:
            await db.commit()

        print("\n" + "=" * 80)
        print(f"清理完成: 共删除 {total_deleted} 个空配置机型")

        if all_empty_models:
            print("\n删除的机型列表:")
            for series_name, model_name, model_id in all_empty_models:
                print(f"  - [{series_name}] {model_name} (id={model_id})")

        # 最终验证
        print("\n" + "=" * 80)
        print("最终验证 - 各系列机型统计:")
        result = await db.execute(select(ProductSeries))
        series_list = result.scalars().all()

        for series in series_list:
            result = await db.execute(
                select(ProductModel).where(ProductModel.series_id == series.id)
            )
            models = result.scalars().all()
            print(f"\n{series.name}: {len(models)} 个机型")
            for model in models:
                cv_count_result = await db.execute(
                    select(func.count()).where(ConfigValue.model_id == model.id)
                )
                cv_count = cv_count_result.scalar()
                status = "✅" if cv_count > 0 else "❌"
                print(f"  {status} {model.name}: {cv_count} 个配置值")

if __name__ == "__main__":
    asyncio.run(cleanup_all_empty_models())
