#!/usr/bin/env python3
"""
清理并重新导入三个Excel文件
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, delete
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigValue, ConfigItem, ImportHistory, ConfigDraft, DraftBatch, ConfigVersion, ChangeLog

async def cleanup_and_reimport():
    async with async_session() as db:
        print("准备清理现有数据...")
        print("=" * 80)

        # 获取要处理的系列
        series_names = [
            "Before2023-China",
            "Before2023-Oversea",
            "R&V10 series-China",
            "R&V10 series-Oversea",
            "Tulip-China",
            "Tulip-Oversea"
        ]

        total_deleted_models = 0
        total_deleted_values = 0

        for series_name in series_names:
            result = await db.execute(
                select(ProductSeries).where(ProductSeries.name == series_name)
            )
            series = result.scalar_one_or_none()

            if not series:
                print(f"\n{series_name}: 系列不存在，跳过")
                continue

            print(f"\n清理 {series_name}...")

            # 获取该系列的所有型号
            result = await db.execute(
                select(ProductModel).where(ProductModel.series_id == series.id)
            )
            models = result.scalars().all()
            model_ids = [m.id for m in models]

            if model_ids:
                # 删除配置值
                result = await db.execute(
                    delete(ConfigValue).where(ConfigValue.model_id.in_(model_ids))
                )
                deleted_values = result.rowcount
                total_deleted_values += deleted_values
                print(f"  删除 {deleted_values} 个配置值")

                # 删除草稿
                await db.execute(
                    delete(ConfigDraft).where(ConfigDraft.model_id.in_(model_ids))
                )

                # 删除型号
                result = await db.execute(
                    delete(ProductModel).where(ProductModel.series_id == series.id)
                )
                deleted_models = result.rowcount
                total_deleted_models += deleted_models
                print(f"  删除 {deleted_models} 个型号")

            # 删除版本历史
            await db.execute(
                delete(ConfigVersion).where(ConfigVersion.series_id == series.id)
            )

            # 删除变更日志
            await db.execute(
                delete(ChangeLog).where(ChangeLog.series_id == series.id)
            )

            # 删除草稿批次
            await db.execute(
                delete(DraftBatch).where(DraftBatch.series_id == series.id)
            )

            # 删除导入历史
            await db.execute(
                delete(ImportHistory).where(ImportHistory.series_id == series.id)
            )

        # 清理没有配置值的ConfigItem（可选）
        print("\n清理孤立的ConfigItem...")
        result = await db.execute(
            select(ConfigItem.id)
            .outerjoin(ConfigValue, ConfigItem.id == ConfigValue.item_id)
            .where(ConfigValue.id == None)
        )
        orphan_items = result.scalars().all()
        if orphan_items:
            await db.execute(
                delete(ConfigItem).where(ConfigItem.id.in_(orphan_items))
            )
            print(f"  删除 {len(orphan_items)} 个孤立配置项")

        await db.commit()

        print("\n" + "=" * 80)
        print(f"清理完成: 共删除 {total_deleted_models} 个型号, {total_deleted_values} 个配置值")

        # 显示清理后的状态
        print("\n清理后数据库状态:")
        result = await db.execute(select(ProductSeries))
        series_list = result.scalars().all()
        for series in series_list:
            result = await db.execute(
                select(ProductModel).where(ProductModel.series_id == series.id)
            )
            model_count = len(result.scalars().all())
            if model_count > 0:
                print(f"  {series.name}: {model_count} 个型号")

if __name__ == "__main__":
    asyncio.run(cleanup_and_reimport())
