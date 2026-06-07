#!/usr/bin/env python3
"""
详细检查 Before2023-China 中的海外机型配置情况
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, func
from app.database import async_session
from app.models import ProductSeries, ProductModel, ConfigValue

async def check_china_oversea_models():
    async with async_session() as db:
        print("Before2023-China 系列中的海外机型检查")
        print("=" * 80)

        # 获取 Before2023-China 系列
        result = await db.execute(
            select(ProductSeries).where(ProductSeries.name == "Before2023-China")
        )
        series = result.scalar_one_or_none()

        if not series:
            print("未找到 Before2023-China 系列")
            return

        # 获取该系列下所有机型
        result = await db.execute(
            select(ProductModel).where(ProductModel.series_id == series.id)
        )
        models = result.scalars().all()

        oversea_keywords = ['_BRA', '_RUA', '_EXP', '_PRO', '_S', '_POC', '_Anesthesia']

        print(f"\n系列: {series.name} (共 {len(models)} 个机型)")
        print("-" * 80)

        for model in models:
            is_oversea = any(kw in model.name for kw in oversea_keywords)

            # 统计配置值数量
            cv_count_result = await db.execute(
                select(func.count()).where(ConfigValue.model_id == model.id)
            )
            cv_count = cv_count_result.scalar()

            status = "⚠️ 海外" if is_oversea else "✅ 正常"
            config_status = f"({cv_count}配置值)" if cv_count > 0 else "❌ 无配置"

            print(f"  {status} {model.name} (id={model.id}): {config_status}")

if __name__ == "__main__":
    asyncio.run(check_china_oversea_models())
