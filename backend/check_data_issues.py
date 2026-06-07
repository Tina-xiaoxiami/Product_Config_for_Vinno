#!/usr/bin/env python3
"""
分析数据问题：
1. 哪些机型配置为空
2. 哪些机型归属了错误的系列
3. ConfigValue和ConfigItem的关联关系
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigItem, ConfigValue

async def analyze_data():
    async with async_session() as db:
        print("=" * 80)
        print("数据问题分析")
        print("=" * 80)

        # 1. 获取所有系列和型号
        result = await db.execute(
            select(ProductSeries).options(selectinload(ProductSeries.product_models))
        )
        series_list = result.scalars().all()

        print("\n【1】系列和型号分布：")
        for series in series_list:
            print(f"\n系列: {series.name} (id={series.id})")
            for model in series.product_models:
                # 统计该型号的配置值数量
                cv_count_result = await db.execute(
                    select(func.count()).where(ConfigValue.model_id == model.id)
                )
                cv_count = cv_count_result.scalar()
                print(f"    - {model.name} (id={model.id}): {cv_count} 个配置值")

        # 2. 查找配置值为空的机型
        print("\n" + "=" * 80)
        print("\n【2】配置值为空的机型（可能需要检查）：")
        empty_models = []
        for series in series_list:
            for model in series.product_models:
                cv_count_result = await db.execute(
                    select(func.count()).where(ConfigValue.model_id == model.id)
                )
                cv_count = cv_count_result.scalar()
                if cv_count == 0:
                    empty_models.append((series.name, model.name))

        if empty_models:
            for series_name, model_name in empty_models:
                print(f"    ⚠️ {series_name} / {model_name}")
        else:
            print("    ✅ 所有机型都有配置值")

        # 3. 统计ConfigItem使用情况
        print("\n" + "=" * 80)
        print("\n【3】ConfigItem全局统计：")
        item_count_result = await db.execute(select(func.count()).select_from(ConfigItem))
        total_items = item_count_result.scalar()
        print(f"    总配置项数量: {total_items}")

        # 统计每个ConfigItem被多少个型号引用
        result = await db.execute(
            select(ConfigValue.item_id, func.count()).group_by(ConfigValue.item_id)
        )
        item_ref_counts = result.fetchall()
        print(f"    被引用的配置项: {len(item_ref_counts)}")

        # 4. 检查同名型号在不同系列的情况
        print("\n" + "=" * 80)
        print("\n【4】同名型号出现在多个系列中（可能需要合并）：")
        result = await db.execute(
            select(ProductModel.name, func.count()).group_by(ProductModel.name).having(func.count() > 1)
        )
        dup_models = result.fetchall()
        if dup_models:
            for name, count in dup_models:
                # 查找这些型号属于哪些系列
                result = await db.execute(
                    select(ProductSeries.name, ProductModel.name)
                    .join(ProductModel, ProductModel.series_id == ProductSeries.id)
                    .where(ProductModel.name == name)
                )
                locations = result.fetchall()
                print(f"    ⚠️ {name} (出现在 {count} 个系列):")
                for s_name, m_name in locations:
                    print(f"       - {s_name}")
        else:
            print("    ✅ 没有同名型号")

        # 5. 检查可能归属错误的机型
        print("\n" + "=" * 80)
        print("\n【5】可能的系列-机型归属问题（关键字匹配）：")
        keywords = {
            "China": ["_CN", "_CHN", "CHINA"],
            "Oversea": ["_BRA", "_USA", "_EUR", "_JPN", "_KOR", "Oversea"],
        }

        for series in series_list:
            series_name_upper = series.name.upper()
            for model in series.product_models:
                model_name_upper = model.name.upper()

                # 检查China系列中是否有Oversea机型
                if "CHINA" in series_name_upper or "中国" in series.name:
                    for keyword in keywords["Oversea"]:
                        if keyword in model_name_upper:
                            print(f"    ⚠️ {series.name} 中包含海外机型: {model.name}")

                # 检查Oversea系列中是否有China专属机型
                if "OVERSEA" in series_name_upper or "海外" in series.name:
                    for keyword in keywords["China"]:
                        if keyword in model_name_upper:
                            print(f"    ⚠️ {series.name} 中包含中国专属机型: {model.name}")

        print("\n" + "=" * 80)
        print("分析完成")

if __name__ == "__main__":
    asyncio.run(analyze_data())
