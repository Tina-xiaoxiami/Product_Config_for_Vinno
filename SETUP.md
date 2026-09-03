# 产品配置管理系统 - Windows 安装指南

## 环境准备（一次性）

### 1. 安装 Python

下载地址：https://www.python.org/downloads/

- 选择 **Python 3.10 或更高版本**
- 安装时 **勾选 "Add Python to PATH"**（非常重要）

安装完成后打开命令提示符（Win+R 输入 `cmd`），验证：

```
python --version
```

### 2. 安装 Node.js

下载地址：https://nodejs.org/

- 选择 **LTS 版本**（长期支持版）
- 一路默认安装即可

验证：

```
node --version
npm --version
```

## 项目初始化（一次性）

打开命令提示符，进入项目目录：

```
cd 项目所在路径\产品配置管理系统
```

### 3. 安装后端依赖

```
cd backend
pip install -r requirements.txt
cd ..
```

### 4. 安装前端依赖

```
cd frontend
npm install
cd ..
```

### 5. 数据库

系统使用 SQLite 本地文件数据库，首次启动会自动创建空数据库。

如需使用现有数据，将 `product_config.db` 文件复制到 `backend/` 目录下即可。

## 日常使用

- **启动**：双击 `start.bat`，浏览器会自动打开
- **停止**：双击 `stop.bat`

启动后访问：http://localhost:3006

产品知识库：http://localhost:3006/knowledge

功能主数据管理：http://localhost:3006/feature-manage

国内注册数据管理：http://localhost:3006/registration-manage

- 功能主数据以 IPN 为唯一身份；中文描述和英文描述分别作为中英文主名，中英文曾用名分栏展示。研发名仅参与内部识别和搜索，`【启用】`等状态不会显示为名称。
- 功能名称、曾用名和 IPN 关系统一在“基础数据管理 > 功能管理”维护；国内注册型号、探头及来源统一在“基础数据管理 > 注册管理”查看，知识库只读聚合这些主数据。
- 注册红线来自受控注册差异表导入，不在查询页面随意手工修改；注册探头同时保留原始型号，并按 IPN 关联“探头管理”中的基础探头型号。
- 注册证与注册差异表作为一个不可拆分的“注册资料包”记录。注册管理页面可查看当前版、待确认草稿和历史版，分别预览两份受控归档原件，并查看型号、通道数、探头、IPN及注册状态变化；只更新其中一份文件不能形成新版本。
- 新增国内注册证时，在“注册管理 > 新增注册资料包”中成对选择注册证 PDF 和注册差异表 Excel。系统先解析为待确认草稿并自动匹配产品机型；人工确认基础注册型号后再发布。不同注册证分别保留当前版本，发布只影响该注册证绑定的机型。
- “问答查询”只复用已经确认发布的答案；未知问题自动进入待确认队列。确认答案时可登记相似问法、原始资料、页码/章节、原文摘录和变更说明，后续修订自动保留版本记录。
- 相似问答不会跨产品型号、国内/海外范围或相反意图自动复用；医疗器械结论查不到时系统明确返回待确认，不自行猜测。
- 原始资料支持“提取正文”：PDF保留页码，Word保留标题/段落/表格位置，Excel保留工作表和行号。未命中正式答案时系统展示材料候选依据，可带入答案草稿，但仍需人工核对和发布。
- “国内注册与策略”支持按完整产品型号、探头/IPN、注册状态和最终判定查询；`# 未注册`只取注册差异表，“选型类别”是正式策略，“当前配置”仅作辅助。
- `VINNO 9_Private`、`VINNO 9 综合版` 会显示其注册基础型号 `VINNO 9`，同时读取各自产品策略。
- 产品机型通过受控映射关联“注册证 + 注册基础型号”。“基础数据管理 > 产品型号”直接显示对应注册证；查询注册红线时只读取该注册证当前有效版本，不跨注册证汇总。
- PDF 和图片可在页面内预览，Word/Excel 通过“打开原文”访问。
- 普通知识资料不复制到数据库；注册资料包在建立版本时会按 SHA-256 保存只读归档副本，历史预览不依赖后来可能被替换的源文件路径。

批量提取所有已登记资料：

```bash
cd backend
python3 scripts/extract_knowledge_documents.py
```

批量登记知识库问题时使用受控 JSON 清单。默认只预览去重、已发布答案覆盖情况、候选依据和执行耗时；加 `--apply` 才写入待确认队列。系统生成的问题 `asked_count` 为 0，不会冒充真实下游询问次数，也不会自动发布答案：

```bash
cd backend
python3 scripts/seed_knowledge_questions.py --input "/完整路径/问题批次.json"
python3 scripts/seed_knowledge_questions.py --input "/完整路径/问题批次.json" --apply
```

问题批次格式：

```json
{
  "batch": "v10-first-qa-20260903",
  "questions": [
    {"category": "配置策略", "question": "某功能是标配、选配还是招标支持？"}
  ]
}
```

将旧数据库中已经导入的注册批次绑定为首个成对资料包时，必须显式指定两份资料和批次 ID：

```bash
cd backend
python3 scripts/migrate_registration_packages.py \
  --certificate-document-id 25 \
  --difference-document-id 24 \
  --import-batch-id 1 \
  --country-code CN \
  --unit-code V10 \
  --display-name "V10系列国内注册" \
  --product-series V10 \
  --registration-number "湘械注准20222062053" \
  --identity-source registration_certificate \
  --confirmed-by baseline_migration
```

普通成对登记只生成“待确认草稿”，不会替换当前生效注册红线。确认机型映射并通过跨注册证冲突校验后，草稿才能原子发布为该注册证的当前版；不同注册证不合并、不互相覆盖。
两份资料始终作为一对保存，但允许仅其中一份发生换版：例如注册证更新而差异表及结构化快照不变时，新版本会继续引用同一个差异表快照并记录“仅注册证变化”。
