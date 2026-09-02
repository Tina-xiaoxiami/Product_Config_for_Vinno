---
name: vinno-knowledge-audit
description: Audit the VINNO knowledge base for registration coverage, document availability, extraction status, model mappings, enablement mistakes, feature identity gaps, unanswered questions, stale evidence, and cross-source conflicts. Use whenever the user asks what is missing, what to improve next, whether an import is complete, why a query is wrong, or wants a compact feedback report for improving another VINNO skill. Run read-only by default.
compatibility: Requires read access to the Product_Config_for_Vinno project database and source files.
---

# VINNO 知识库质量审计

用只读检查发现数据缺口、规则缺口和系统缺陷。不要为了让报告“通过”而自动修改正式数据。

## 注册资料检查

- 正式版本是否同时关联注册证和差异表原件
- 原件是否存在、哈希一致、可预览
- 每张证是否只有一个正式版本
- 版本状态与启用状态是否被混用
- 机型映射是否指向该证自己的基础型号
- 同一机型多证是否分别保存
- 未启用证是否意外进入默认查询
- 外键和唯一约束是否完整

## 国内产品覆盖

- 按国内产品系列统计总机型、已映射、仅未启用映射、待确认和未覆盖
- 区分基础型号和衍生型号
- 不把海外系列混入国内覆盖率

## 产品材料检查

- 原始说明书、白皮书和 Release Note 是否登记并可预览
- 是否完成正文提取，提取哈希是否对应当前原件
- 材料版本、市场、国家和产品范围是否齐全
- 候选事实是否保留来源位置

## 功能身份检查

- IPN 是否唯一
- 中英文主名是否来源正确
- 状态标记是否污染名称
- 曾用名语言是否正确
- 相关功能或版本关系是否缺失、循环或误合并

## 问答检查

- 待确认和已发布数量
- 高频未回答问题
- 答案是否有引用、适用范围和版本
- 引用材料更新后答案是否可能过期

## 问题分类

- `data_ambiguity`：材料不清楚，需要用户判断
- `missing_rule`：技能未覆盖明确业务规则
- `parser_gap`：文件格式无法可靠提取
- `system_bug`：代码或数据库行为不符合规则
- `coverage_gap`：缺少材料、映射、事实或答案

## 报告格式

```markdown
# VINNO 知识库质量报告
## 执行摘要
## P0 必须处理
## P1 建议近期处理
## P2 可后续优化
## 覆盖率与数量
## 数据问题
## 技能规则问题
## 系统问题
## 建议下一批输入材料
```

每个问题提供证据、影响范围、建议动作和负责人类型，不只写“需要完善”。

## 技能反馈单

需要修改技能时输出：

```text
SKILL_FEEDBACK
skill: 应修改的技能名
issue_type: missing_rule | bad_trigger | unsafe_behavior | inefficient_flow
input: 触发问题的真实输入
observed: AI 实际行为
expected: 用户期望行为
current_rule: 当前规则或缺失点
suggested_change: 最小通用修改
regression_case: 修改后必须通过的测试提示
impact: 影响范围和优先级
```

修改技能时把 `regression_case` 加入对应 `evals/evals.json`，避免同类问题再次出现。
