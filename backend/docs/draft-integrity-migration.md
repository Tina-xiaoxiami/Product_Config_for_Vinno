# 草稿唯一性迁移

迁移需在服务停止期间离线执行。先停止后端并完整备份 SQLite 数据库，再运行默认只读检查。工具必须接收明确的数据库路径：

```bash
python3 scripts/migrate_draft_integrity.py --database /absolute/path/to/product_config.db
```

报告会区分完全相同重复和内容冲突，并列出 `item_id`/`model_id` 为 NULL 或 `field_name` 为空字符串的无效草稿。内容冲突和无效身份都不会自动处理。确认已备份且报告只有完全相同重复后，显式应用：

```bash
python3 scripts/migrate_draft_integrity.py --database /absolute/path/to/product_config.db --apply
```

`--apply` 在一个事务中完成全库预检、删除冗余草稿、刷新受影响批次的四项计数并创建唯一索引。它不修改配置值或历史版本。任一重复组存在类型、旧值或新值冲突，或全库存在无效草稿身份时，事务在任何删除前整体回滚。

唯一索引保障有效 `item_id` 和 `model_id` 的业务键，并用空值合并结构草稿的 `field_name=NULL`。由外键删除产生的孤立草稿不会自动合并，必须根据报告手工确认其原始身份后再处理。

apply 成功后，再次执行 dry run 并核对草稿数量、批次计数和唯一索引。确认复核结果后才启动后端服务。
