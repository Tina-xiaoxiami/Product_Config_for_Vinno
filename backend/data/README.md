# 受控问答快照

`knowledge_qa_snapshot.json` 是已发布知识库问答的可版本控制快照，包含问题、正式答案、相似问法、引用依据和答案版本记录。它不替代 SQLite 正式库，主要用于审计、迁移和灾难恢复。

导出当前正式库：

```bash
cd backend
python3 scripts/manage_knowledge_qa_snapshot.py export \
  --database product_config.db \
  --output data/knowledge_qa_snapshot.json
```

恢复前预演（默认不写数据库）：

```bash
cd backend
python3 scripts/manage_knowledge_qa_snapshot.py restore \
  --database /目标数据库完整路径/product_config.db \
  --input data/knowledge_qa_snapshot.json
```

确认预演结果后写入：

```bash
cd backend
python3 scripts/manage_knowledge_qa_snapshot.py restore \
  --database /目标数据库完整路径/product_config.db \
  --input data/knowledge_qa_snapshot.json \
  --apply
```

恢复会先验证快照的规范化内容及其 `snapshot_sha256`；对内容已一致的数据库再次执行时返回 `already_current`，不会重复生成记录。正式库恢复前仍应由产品负责人确认目标数据库和快照版本。

# 功能名称标准表

`feature_name_standard.tsv` 是功能中英文名称的标准定义（中文名称 / 英文名称 / 中文UI），
作为种子数据随仓库版本控制。应用侧存在 `feature_name_standards` 表，由「功能管理 > 标准名称」
或接口整表覆盖导入：

```bash
cd backend
curl -X POST -F "file=@data/feature_name_standard.tsv" \
  http://127.0.0.1:8086/api/features/standards/import
```

标准表是名称定义来源，应用只用它做提示（`GET /api/features/standards`、`GET /api/features/standards/flags`），
不会自动改写功能主数据。拿到更新的原表（.xlsx/.csv/.tsv）后可直接重新导入覆盖。
