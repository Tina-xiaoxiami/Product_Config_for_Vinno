#!/usr/bin/env python3
"""
清理重复的 ConfigItem，保留每个 IPN 只有一条记录
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload
from app.database import async_session
from app.models import ConfigItem, ConfigValue

async def cleanup_duplicates():
    async with async_session() as db:
        print("开始清理重复的 ConfigItem...")

        # 1. 找出所有重复的 IPN
        result = await db.execute(
            select(ConfigItem.ipn, func.count()).group_by(ConfigItem.ipn).having(func.count() > 1)
        )
        duplicates = result.fetchall()
        print(f"发现 {len(duplicates)} 个重复的 IPN")

        for ipn, count in duplicates:
            if not ipn:
                continue
            print(f"\n处理 IPN: {ipn} ({count} 条重复)")

            # 2. 获取该 IPN 的所有配置项
            result = await db.execute(
                select(ConfigItem).where(ConfigItem.ipn == ipn).order_by(ConfigItem.id)
            )
            items = result.scalars().all()

            if len(items) <= 1:
                continue

            # 3. 保留第一个（id最小的），合并其他到第一个
            keep_item = items[0]
            delete_items = items[1:]

            print(f"  保留 id={keep_item.id}")

            # 4. 更新 ConfigValue 引用
            for delete_item in delete_items:
                print(f"  删除 id={delete_item.id}，迁移配置值...")

                # 获取该 item 的所有 ConfigValue
                values_result = await db.execute(
                    select(ConfigValue).where(ConfigValue.item_id == delete_item.id)
                )
                values = values_result.scalars().all()

                for v in values:
                    # 检查目标 item 是否已有该 model 的配置值
                    existing_result = await db.execute(
                        select(ConfigValue).where(
                            ConfigValue.item_id == keep_item.id,
                            ConfigValue.model_id == v.model_id
                        )
                    )
                    existing = existing_result.scalar_one_or_none()

                    if existing:
                        # 更新现有值
                        existing.final_config = v.final_config or existing.final_config
                        existing.current_config = v.current_config or existing.current_config
                        existing.selection_config = v.selection_config or existing.selection_config
                        existing.rd_status = v.rd_status or existing.rd_status
                        # 删除旧的
                        await db.delete(v)
                    else:
                        # 迁移到保留的 item
                        v.item_id = keep_item.id

                # 删除重复的配置项
                await db.delete(delete_item)

            await db.commit()
            print(f"  完成处理 {ipn}")

        # 5. 验证清理结果
        result = await db.execute(
            select(ConfigItem.ipn, func.count()).group_by(ConfigItem.ipn).having(func.count() > 1)
        )
        remaining = result.fetchall()
        print(f"\n清理完成，剩余重复 IPN: {len(remaining)}")

        # 统计
        result = await db.execute(select(func.count()).select_from(ConfigItem))
        total = result.scalar()
        print(f"当前 ConfigItem 总数: {total}")

if __name__ == "__main__":
    asyncio.run(cleanup_duplicates())
