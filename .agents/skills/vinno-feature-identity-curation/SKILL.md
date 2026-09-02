---
name: vinno-feature-identity-curation
description: Curate VINNO feature identities using IPN as the stable identifier, with Chinese and English primary names, language-specific aliases, related IPNs, and version variants. Use whenever the user mentions feature names, IPN, 中文描述, 英文描述, 研发名称, 曾用名, 备用名, 同功能判断, related functions, version IPNs, duplicate features, or corrections such as removing 【启用】 from a name.
compatibility: Requires local access to the Product_Config_for_Vinno feature master data.
---

# VINNO 功能身份整理

让材料使用中文名、英文名或历史名称时都能命中正确功能，同时保留 IPN 身份和关系，不因名称相似而误合并。

## 核心规则

- IPN 是功能身份的唯一稳定标识。
- 中文主名来自正式中文描述；英文主名来自正式英文描述。
- 研发名称不能覆盖正式主名，可作为对应语言的曾用名或来源说明。
- 中文曾用名和英文曾用名分开管理；材料使用任一主名或曾用名都应可命中。
- `【启用】`、`[启用]` 等是状态，不属于名称。清洗名称时保留状态信息但从名称字段移除。
- 名称相似不等于同一功能。只有已有确认关系、明确版本关系或用户确认后才能建立关系。
- 同一业务功能存在不同版本 IPN 时，保留各 IPN 身份，以 `version_variant` 或已定义关系连接。
- 已有人工确认优先于自动相似度，不重复询问已经确认的关系。

## 工作流

1. 收集候选 IPN、中文描述、英文描述、研发名称和材料中出现的名称。
2. 温和清洗名称：去除状态标记、首尾空白和明显格式噪声，不改写专业术语。
3. 查询现有身份、名称和关系，区分新身份、新曾用名、相关功能、版本变体和高风险疑似重复。
4. 自动应用无歧义变更；高风险合并候选一次性列出供确认。
5. 写入后验证 IPN 唯一、主名、名称语言和关系类型。

## 合并边界

合并功能时不要删除相关 IPN 或历史名称。把选定功能作为查询入口，其他 IPN 以相关功能或版本关系保留。用户说“合并到某功能”时，也要保留被合并 IPN 的关系，避免材料失去命中能力。

## 报告格式

```markdown
# 功能身份整理报告
## 自动确认变更
## 中文主名与曾用名
## 英文主名与曾用名
## IPN 关系
## 疑似重复与集中待确认项
## 未命中材料名称
## 建议下一步
```

每个待确认项同时显示 IPN、中文描述、英文描述、研发名称和建议关系。

## 规则反馈

```text
SKILL_FEEDBACK
skill: vinno-feature-identity-curation
issue_type: naming_rule | relation_rule | language_mismatch | unsafe_merge | system_bug
input: IPN 和所有已知名称
observed: 当前匹配或合并行为
expected: 期望身份或关系
current_rule: 触发问题的规则
suggested_change: 建议修改
impact: 受影响的材料命中和配置记录
```
