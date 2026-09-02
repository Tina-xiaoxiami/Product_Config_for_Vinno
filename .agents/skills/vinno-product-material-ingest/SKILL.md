---
name: vinno-product-material-ingest
description: Ingest and enrich the VINNO knowledge base from manuals, IFUs, whitepapers, datasheets, and software Release Notes. Use whenever the user supplies or references 产品说明书, IFU, 白皮书, datasheet, Release Note, 发布记录, software-version material, or asks whether a product fact is standard, optional, tender-supported, or available in a release. Preserve original files and separate evidence from inference.
compatibility: Requires local access to the Product_Config_for_Vinno project and document extraction dependencies.
---

# VINNO 产品材料入库

把说明书、白皮书和 Release Note 转换为可检索、可引用、可追溯的知识。原文始终是证据源，结构化内容是派生结果。

## 材料角色

- 说明书/IFU：操作、功能描述、适用产品和警告信息。
- 白皮书/Datasheet：产品功能、性能和配置表述。
- Release Note：软件版本、发布日期、功能进入版本的状态和变化。
- 注册材料交给 `vinno-registration-ingest`，不得混用规则。

## 工作流

1. 识别材料类型、产品系列、完整型号、市场、国家、版本和日期。
2. 把原文件纳入 Obsidian 受控材料目录，再登记受控副本的路径、文件名、哈希和预览入口，不只保存提取文字。
3. 检查相同哈希或同版本材料：相同内容复用，变化内容登记新版本。
4. 提取正文并分段，保留页码、章节、表格或工作表位置。
5. 生成候选事实，不把推断直接写成正式结论。
6. 关联已有型号、功能和 IPN；匹配可以命中中文主名、英文主名或对应语言的曾用名。
7. 把无法确定的型号、配置类别或版本范围集中列入待确认项。

## 受控原文件

- 说明书、白皮书和 Release Note 的登记路径必须指向本地 Obsidian 受控材料副本，不得直接指向 iCloud 来源文件。
- 目标结构为 `<Obsidian 受控材料根目录>/<类型目录>/<原文件名>`；类型目录使用 `说明书`、`白皮书`和 `发布记录`。
- 先复制或收纳文件，再计算 SHA-256；只有受控副本存在且哈希与来源一致时才可登记或更新路径。
- 已指向受控目录的相同文件应幂等复用。目标缺失、哈希不符或同名不同内容时停止登记并集中报告。
- 历史 iCloud 路径迁移时，先运行 `backend/scripts/migrate_knowledge_document_paths.py` 默认 dry-run；只有审查结果无误后才用 `--apply`。

## 已确认解释规则

- `X` 标配，`O` 选配，`Δ`/`∆` 招标支持，`#` 未注册或不允许支持。
- 注册红线优先于任何产品策略或宣传材料。
- “选型类别”是正式发布配置；“当前配置”是研发内部状态，仅在缺少选型类别时辅助说明。
- 对已确认采用该写法的 VINNO 白皮书，条目未标注选配、招标或不支持时，可形成“标配”候选结论，但要保留原句和版本。
- 材料说“系列支持”时不要擅自缩小到单个型号；只列部分型号时也不要扩展到整个系列。
- Release Note 证明功能进入某版本，但不能替代注册证证明注册范围，也不能单独证明选配或招标状态。

## 候选事实字段

- 规范化主题或功能身份
- 产品系列和适用型号
- 市场/国家
- 软件或材料版本
- 原文摘录和来源位置
- 结论类型：原文事实、经确认解释、待确认推断

## 报告格式

```markdown
# 产品材料入库报告
## 材料身份
## 原文件与预览
## 提取状态
## 新增或更新的候选事实
## 已关联功能和型号
## 与已有知识的冲突
## 集中待确认项
## 建议下一步
```

材料登记和正文提取可以执行；正式结论需遵循项目确认机制。不要直接改写注册红线、功能主身份或正式选型配置，也不要提交原始材料、数据库和提取产物到 Git。

## 规则反馈

```text
SKILL_FEEDBACK
skill: vinno-product-material-ingest
issue_type: unsupported_format | extraction_gap | missing_rule | evidence_conflict
input: 材料名、版本和相关型号
observed: 实际提取或匹配结果
expected: 期望结果
current_rule: 当前解释规则
suggested_change: 建议修改
impact: 受影响的事实、功能或型号
```
