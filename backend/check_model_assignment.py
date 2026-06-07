#!/usr/bin/env python3
"""
检查机型归属错误：分析哪些机型可能归属了错误的系列
基于命名规则判断
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select
from app.database import async_session
from app.models import ProductSeries, ProductModel

async def check_model_series_assignment():
    async with async_session() as db:
        print("机型归属检查")
        print("=" * 80)

        # 获取所有系列和机型
        result = await db.execute(
            select(ProductSeries, ProductModel)
            .join(ProductModel, ProductModel.series_id == ProductSeries.id)
            .order_by(ProductSeries.name, ProductModel.name)
        )
        rows = result.fetchall()

        # 定义关键字规则
        china_keywords = ['_CN', '_CHN', 'CHINA', '中国']
        oversea_keywords = ['_BRA', '_USA', '_EUR', '_JPN', '_KOR', '_RUA', '_EXP', '_PRO', '_S', '_POC', '_Anesthesia']
        tulip_keywords = ['ULTIMUS']
        v10_keywords = ['VINNO 10', 'VINNO 9', 'VINNO 9E']

        suspicious = []

        print("\n详细检查:")
        for series, model in rows:
            series_name = series.name.upper()
            model_name = model.name.upper()

            issue = None

            # 规则1: Tulip系列应该只有ULTIMUS
            if 'TULIP' in series_name and not any(k in model_name for k in tulip_keywords):
                issue = f"Tulip系列包含非ULTIMUS机型"

            # 规则2: R&V10系列应该只有VINNO 10/9
            elif 'R&V10' in series_name and not any(k in model_name for k in v10_keywords):
                issue = f"R&V10系列包含非V10/V9机型"

            # 规则3: Before2023系列
            elif 'BEFORE2023' in series_name:
                # China系列不应该有海外专属后缀
                if 'CHINA' in series_name and 'OVERSEA' not in series_name:
                    for kw in oversea_keywords:
                        if kw in model_name:
                            issue = f"China系列包含海外机型({kw})"
                            break

                # Oversea系列不应该有中国专属后缀
                elif 'OVERSEA' in series_name:
                    for kw in china_keywords:
                        if kw in model_name:
                            issue = f"Oversea系列包含中国专属机型({kw})"
                            break

            if issue:
                suspicious.append({
                    'series': series.name,
                    'model': model.name,
                    'issue': issue
                })
                print(f"  ⚠️ [{series.name}] {model.name}: {issue}")

        print("\n" + "=" * 80)
        if suspicious:
            print(f"发现 {len(suspicious)} 个可疑归属:")
            for item in suspicious:
                print(f"  - {item['series']} / {item['model']}: {item['issue']}")
        else:
            print("✅ 没有发现明显的归属错误")

        # 统计各系列机型数量
        print("\n" + "=" * 80)
        print("各系列机型统计:")
        result = await db.execute(select(ProductSeries))
        series_list = result.scalars().all()
        for series in series_list:
            result = await db.execute(
                select(ProductModel).where(ProductModel.series_id == series.id)
            )
            models = result.scalars().all()
            model_names = [m.name for m in models]
            print(f"\n{series.name} ({len(models)}个):")
            print(f"  {', '.join(model_names)}")

if __name__ == "__main__":
    asyncio.run(check_model_series_assignment())
