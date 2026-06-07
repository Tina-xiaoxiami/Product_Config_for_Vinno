#!/usr/bin/env python3
"""
清理导入逻辑错误导致的重复机型
分析哪些机型是重复的（同名且在不同系列中，但配置应该不同）
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, func
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigValue

async def analyze_and_cleanup():
    async with async_session() as db:
        print("分析重复机型")
        print("=" * 80)

        # 1. 找出所有重复的机型名
        result = await db.execute(
            select(ProductModel.name, func.count())
            .group_by(ProductModel.name)
            .having(func.count() > 1)
        )
        duplicate_names = result.fetchall()

        print(f"\n发现 {len(duplicate_names)} 个重复机型名:")
        for name, count in duplicate_names:
            print(f"  - {name}: {count} 个实例")

        # 2. 分析每个重复机型
        print("\n" + "=" * 80)
        print("详细分析:")

        cleanup_candidates = []

        for name, count in duplicate_names:
            print(f"\n{name}:")
            result = await db.execute(
                select(ProductModel, ProductSeries)
                .join(ProductSeries, ProductModel.series_id == ProductSeries.id)
                .where(ProductModel.name == name)
                .order_by(ProductModel.id)
            )
            models = result.fetchall()

            for model, series in models:
                # 统计配置值
                result = await db.execute(
                    select(func.count()).where(ConfigValue.model_id == model.id)
                )
                cv_count = result.scalar()

                # 获取导入信息（通过column_start判断来源）
                print(f"  - id={model.id}, series={series.name}, column_start={model.column_start}, configs={cv_count}")

                # 标记需要清理的机型（后创建的，column_start较大的）
                if len(models) > 1:
                    # 保留id最小的（先创建的），其他标记为待删除
                    if model.id > min(m.id for m, s in models):
                        cleanup_candidates.append({
                            'model_id': model.id,
                            'name': name,
                            'series': series.name,
                            'column_start': model.column_start,
                            'cv_count': cv_count
                        })

        # 3. 显示待清理列表
        print("\n" + "=" * 80)
        print(f"待清理的重复机型（建议删除后创建的）:")
        print(f"共 {len(cleanup_candidates)} 个机型")
        for item in cleanup_candidates:
            print(f"  - {item['series']}/{item['name']} (id={item['model_id']}, column={item['column_start']}, configs={item['cv_count']})")

        # 4. 执行清理（可选）
        print("\n" + "=" * 80)
        print("清理选项:")
        print("  1. 仅分析（不删除）")
        print("  2. 删除重复机型及其配置值")
        print("  3. 取消")

        # 自动执行选项1：仅分析
        print("\n当前执行：仅分析（不删除）")

        return cleanup_candidates

if __name__ == "__main__":
    candidates = asyncio.run(analyze_and_cleanup())
    print(f"\n如需清理，请手动确认后执行删除操作")
