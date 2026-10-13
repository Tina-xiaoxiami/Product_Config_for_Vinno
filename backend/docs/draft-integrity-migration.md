# 草稿唯一性迁移

迁移工具必须接收明确的 SQLite 数据库路径，默认只读检查：

```bash
python scripts/migrate_draft_integrity.py --database /absolute/path/to/product_config.db
```

报告会区分完全相同重复和内容冲突。内容冲突不会自动处理。确认已备份且报告只有完全相同重复后，显式应用：

```bash
python scripts/migrate_draft_integrity.py --database /absolute/path/to/product_config.db --apply
```

`--apply` 在一个事务中完成全库预检、删除冗余草稿、刷新受影响批次的四项计数并创建唯一索引。它不修改配置值或历史版本。任一重复组存在类型、旧值或新值冲突时，事务整体回滚。
