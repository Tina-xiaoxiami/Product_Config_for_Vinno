---
name: vinno-qa-curation
description: Turn real downstream VINNO product questions into controlled, reusable answers with citations, aliases, version history, and a pending-review fallback. Use whenever the user provides a question from sales, clinical, service, tender, or another downstream colleague; asks to add or revise an answer; wants similar questions consolidated; or wants answers from registration, configuration, manuals, whitepapers, or Release Notes without guessing.
compatibility: Requires local access to the Product_Config_for_Vinno knowledge and registration APIs.
---

# VINNO 问答整理

把真实下游问题沉淀为受控知识。宁可进入待确认，也不生成缺乏证据的确定答案。

## 回答前确定范围

识别并在答案中说明：产品完整型号及基础型号、市场和国家、注册证或默认已启用证、软件版本，以及问题属于注册、配置、功能事实、版本发布还是操作说明。

信息不足但不会改变结论时可采用已知默认值并说明；会改变结论时提出一个集中澄清问题。

## 证据规则

- 注册范围以对应注册证及差异表为准。
- 默认只用已启用证；明确询问未启用证时可回答，但提示“正式未启用，不作为当前启用支持结论”。
- 产品策略以选型类别为正式依据，研发当前配置只在缺少正式选型时辅助说明。
- 产品事实引用说明书、白皮书和 Release Note 的明确表述。
- Release Note 不能单独证明注册范围或配置策略。
- 已确认问答可以复用表述，但不能覆盖与新版本受控材料冲突的事实。
- 每个关键结论关联可预览来源，或明确标为“产品负责人确认，暂未绑定原文”。

## 工作流

1. 规范化问题，同时保留原始问法。
2. 搜索已有正式答案和相似问法。
3. 已有答案且范围一致时，复用并返回当前版本和引用。
4. 只有材料候选时生成“待确认答案草稿”，不冒充正式结论。
5. 查不到时创建或更新待确认问题并累计询问次数。
6. 用户确认后发布答案，保存相似问法、引用和变更说明。
7. 修改答案时生成新版本，不覆盖历史。

## 标准答案

```markdown
结论：一句话直接回答。

适用范围：型号、市场/国家、注册证、软件版本。

依据：
- 注册红线：……
- 产品策略：……
- 产品材料：……

状态提示：已启用、未启用、辅助信息或待确认。

来源：可预览材料及页码/章节/工作表。
```

多证冲突、型号不明、材料版本不明、正式选型缺失、只有研发状态或来源冲突时进入待确认，并附已找到的候选依据。

## 规则反馈

```text
SKILL_FEEDBACK
skill: vinno-qa-curation
issue_type: intent_miss | missing_evidence | wrong_scope | stale_answer | answer_rule
input: 原始问题和识别范围
observed: 当前答案或待确认行为
expected: 期望回答
current_rule: 使用的查询或证据规则
suggested_change: 建议新增的问法、规则或数据
impact: 可能影响的相似问题
```
