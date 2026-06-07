#!/usr/bin/env python3
"""
分析 ConfigItem 的分类分布
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, func
from app.database import async_session
from app.models import ConfigItem

async def analyze_categories():
    async with async_session() as db:
        print("ConfigItem 分类统计")
        print("=" * 80)

        # 按分类统计
        result = await db.execute(
            select(ConfigItem.category, func.count())
            .group_by(ConfigItem.category)
            .order_by(ConfigItem.category)
        )
        categories = result.fetchall()

        print("\n分类分布:")
        for cat, count in categories:
            print(f"  - {cat}: {count} 项")

        # 统计各分类下的IPN示例
        print("\n" + "=" * 80)
        print("各分类下的IPN示例（前5个）:")

        for cat, _ in categories:
            result = await db.execute(
                select(ConfigItem.ipn, ConfigItem.rd_name)
                .where(ConfigItem.category == cat)
                .limit(5)
            )
            items = result.fetchall()
            print(f"\n{cat}:")
            for ipn, rd_name in items:
                print(f"  - {ipn or 'N/A'}: {rd_name}")

        # 统计没有分类的数据
        result = await db.execute(
            select(func.count()).where(
                (ConfigItem.category == None) | (ConfigItem.category == "")
            )
        )
        no_cat_count = result.scalar()

        if no_cat_count > 0:
            print(f"\n⚠️ 没有分类的数据: {no_cat_count} 项")

if __name__ == "__main__":
    asyncio.run(analyze_categories())
