# Office 派生索引受控迁移（本地候选）

KH-02 的 Office 引用定位能力已能复用现有提取器，从同一 SHA-256 的 DOCX/XLSX 原件重放段落、表格或单元格位置。旧 `2` 索引需要升级到 `office-locator-v1`，才能完成结构核验。此工具只编排已有提取、缓存暂存和引用核验服务，不维护第二套解析规则。

本阶段仅交付本地工具与合成测试。`ready_for_production_apply` 始终为 `false`：计划和测试不能证明服务已部署、旧写入器已隔离，或正式迁移已获授权。配置/参数确定性查询规则不变。

## 默认只读计划

必须明确指定已有 SQLite 数据库。工具不会调用应用启动或 `init_db`，不会创建数据库或补建表。输入仅支持活动 DOCX/XLSX、旧提取版本 `2`、明确 SHA-256 与旧片段数；不支持 PDF、DOC、XLS 或已升级索引。

以下仅为参数格式，使用经审核的实际路径、ID、哈希和数量替换占位符：

```sh
python backend/scripts/migrate_knowledge_office_index.py \
  --database /absolute/path/existing.sqlite \
  --document 'ID:SHA256:2:COUNT' \
  --document 'OTHER_ID:OTHER_SHA256:2:OTHER_COUNT' \
  --output /absolute/path/private/plan.json
```

省略 `--action` 即为 `plan`；省略 `--output` 只输出计划。输出父目录必须已存在，新文件不可覆盖输入或现有文件。计划不包含原文内容；私有恢复清单包含旧/新索引全文，均以 `0600` 写入，不应入库、上传或共享。校验和用于发现损坏，不是数字签名；必须保护本地文件及父目录，审核来源可信的计划。

计划绑定数据库规范路径、设备/inode、精确文档集合、源文件 SHA-256、提取版本/数量和选中行摘要。应用时取得写锁后及提交前重新检查数据库身份和这些条件。SQLite 行锁无法防止外部替换路径，执行窗口仍须确保没有其他进程重命名/替换数据库文件。无人工修订、无已发布问答/功能版本引用、旧缓存与片段一一对应且未改值，才允许迁移。未知可变表列直接拒绝，不丢弃未知元数据。

## 应用、检查和恢复

只有后续明确授权的窗口才能执行实际资料迁移；此处记录工具接口，当前阶段不执行正式库：

```sh
python backend/scripts/migrate_knowledge_office_index.py --action apply \
  --database /absolute/path/existing.sqlite --ids 'ID,OTHER_ID' \
  --plan /absolute/path/private/plan.json --manifest /absolute/path/private/run.json

python backend/scripts/migrate_knowledge_office_index.py --action status \
  --database /absolute/path/existing.sqlite --ids 'ID,OTHER_ID' \
  --manifest /absolute/path/private/run.json

python backend/scripts/migrate_knowledge_office_index.py --action rollback \
  --database /absolute/path/existing.sqlite --ids 'ID,OTHER_ID' \
  --manifest /absolute/path/private/run.json
```

同一数据库/清单只允许一个维护操作进程，独占期须持续到最终清单写入结束。清单内容 token 用于乐观漂移检查，检查与替换并非原子 CAS，不支持任意并发编辑清单。原子文件替换与完整前后快照保证中断后仍可检查实际状态；不应在迁移或恢复期间手工编辑清单。

整批使用同一个 `BEGIN IMMEDIATE` 外层事务；现有提取服务内部提交只释放保存点。先暂存新缓存，再删除精确旧缓存ID，避免旧审核ID绑定到新片段。旧片段ID若被复用，整批拒绝；工具不修改 schema、插入占位行或操纵分配计数。单份资料占据最高片段ID等情形可能因此拒绝，需要另行评估，不能绕过。

提交前逐片段调用现有 `citation_evidence` 和 `verified_original`：原件哈希、提取版本、内容与结构位置必须匹配。结构匹配不等于视觉或人工核验；Office 保持 `page=null`、`model_answer_eligible=false`、`structure=matched`、`visual=not_checked`、`human=not_reviewed`。

恢复清单以同目录原子安装、文件与父目录 fsync 写入。阶段依次为：`prepared`（完整旧行）→`commit_prepared`（完整新行，提交前落盘）→`applied`。若提交或末次清单写入失败，必须先执行只读 `status`，不能重跑 `apply`。已有清单始终阻止重复应用。

状态按当前数据库选中行和源文件核验结果判定，不能仅相信清单的阶段：

| 状态 | 含义及处理 |
| --- | --- |
| `old` | 当前仍为计划前状态；不要盲目重放，先查失败原因并重新审核计划。 |
| `new` | 当前为完整迁移后状态；即使阶段仍是 `commit_prepared` 也不重复应用。 |
| `unknown` | 行状态不匹配；命令非零退出，保留现场另行调查，禁止自动恢复。 |

回滚必须精确匹配清单中的新状态，重新检查人工修订、引用及全部退休ID占用（含其他文档或其他数据类型）。回滚只恢复选中派生行，不还原整个数据库，不删除并行新增业务数据，不回退自增计数；提取状态行使用 UPDATE，避免级联删除。恢复提交前写入 `rollback_prepared`，成功后写入 `rolled_back`，中断同样使用 `status` 判断。

## 验证与剩余工作

自动测试仅使用临时 SQLite 和合成 Office 文件，覆盖批次中途失败、源文件/行漂移、旧ID占用、人工历史、引用阻断、提交后清单写入失败、只读检查、精确恢复以及 CLI 全链路。关联提取器、引用核验与暂存测试一起验证；本阶段不重跑实际资料演练，不执行浏览器、模型或服务启动。

本阶段验证：新工具合成测试 38 项通过，关联既有提取器/引用/暂存测试 66 项通过；迁移服务行覆盖 98%，CLI 89%（独立子进程覆盖合并）。三个 Python 文件 Ruff 检查及格式检查通过，两个生产文件限定 mypy（含 `--check-untyped-defs`，跳过外部导入）通过。代码与 Python 专项复核的已知问题已修正或明确操作边界。

正式部署状态确认、旧写入器隔离、经审核的具体生产计划及正式窗口执行仍需后续阶段处理；不能将本地 GREEN 作为线上资料已完成迁移的证据。
