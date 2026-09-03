---
name: vinno-model-routing
description: Route VINNO product knowledge work between GPT-5.6 Luna, Terra, and Sol according to workload volume, semantic ambiguity, business risk, and release impact. Use when a request spans material ingestion, registration processing, feature identity, Q&A, implementation, audit, or publishing and should select or recommend a model for each stage. Do not use for a single straightforward request that already has an explicitly selected model.
---

# VINNO 知识库模型路由

用一个入口判断任务阶段、选择业务技能和模型，并在证据歧义或风险上升时逐级升级。模型能力不能替代业务授权；正式发布、启停和高影响正式库写入仍遵循用户确认边界。

## 路由顺序

1. 判断任务属于注册资料、普通产品材料、功能身份、问答整理、系统开发还是质量审计。
2. 只加载对应业务技能：`vinno-registration-ingest`、`vinno-product-material-ingest`、`vinno-feature-identity-curation`、`vinno-qa-curation` 或 `vinno-knowledge-audit`。
3. 根据下表选择当前步骤的最低充分模型和推理强度。
4. 每个阶段结束时输出结构化交接摘要；有升级条件时把摘要交给更强模型，不重复传入全部材料。
5. 写入正式库或发布前执行适当核验；需要用户授权的动作必须停在可审查状态。

## 模型选择

| 模型 | 默认推理强度 | 使用场景 |
| --- | --- | --- |
| `gpt-5.6-luna` | `low` 或 `medium` | 批量文件盘点、哈希核对、格式识别、可确定字段提取、表格行列规范化、重复项检查和其他高吞吐机械处理 |
| `gpt-5.6-terra` | `medium`，复杂匹配用 `high` | 默认日常模型；IPN/主名/曾用名匹配、机型映射、候选事实和问答整理、普通代码实现、测试与常规故障修复 |
| `gpt-5.6-sol` | `high` 或 `xhigh` | 注册红线或跨来源冲突裁决、证据不足的关键结论、复杂功能身份合并、数据库架构或迁移方案、正式发布前的高风险审核 |

优先按工作风险而不是文本长度选模型。不要为了每个小步骤频繁切换；同一批次的连续低风险步骤可保持当前模型。

## 典型流程

- 说明书、白皮书、Release Note：Luna完成盘点和初提取；Terra完成语义关联、候选事实及问答整理；出现注册或关键证据冲突时升级Sol。
- 注册证与差异表：Luna可做原件核验和确定性表格提取；Terra完成证书、基础型号、探头和差异映射；红线冲突、同机型多证歧义或发布决策交给Sol。
- 功能身份：普通名称清洗和单一IPN关联用Terra；多个IPN版本关系、疑似误合并或影响既有正式身份时用Sol复核。
- 系统开发：常规接口、页面、查询优化和测试用Terra；数据模型、正式库迁移、权限边界或大范围重构用Sol设计或复核。
- 质量审计：确定性覆盖率统计可用Luna；问题归因和修复建议用Terra；涉及注册结论或发布阻断的最终判断用Sol。

## 自动升级条件

### Luna 升级 Terra

- 同一字段存在多个合理候选，不能靠确定性规则排除。
- 中文名、英文名、曾用名或IPN无法稳定匹配。
- 表格结构异常、跨页或跨工作表关系需要语义判断。
- 提取结果与已有知识不一致，且不是简单格式差异。

### Terra 升级 Sol

- 注册证、注册差异表、产品策略、白皮书或Release Note之间出现实质冲突。
- 结论会改变未注册判断、注册红线、证书启用状态或默认查询结果。
- 功能合并会影响多个IPN、既有版本关系或已发布问答。
- 需要变更数据库结构、执行正式库迁移或进行大范围不可轻易回退的更新。
- 关键事实没有足够原文证据，仍需要作业务判断。

### Sol 交给用户确认

- 材料本身无法消除的业务歧义。
- 正式发布、注册证启停、批量覆盖正式数据或其他外部/高影响写操作。
- 需要新增或修改业务规则，而不是修正明确的实现错误。

Sol审核通过不等于获得发布授权。

## 阶段交接

模型切换时仅传递完成下一步所需的信息：

```yaml
objective: 当前批次目标
domain_skill: 使用的VINNO业务技能
completed: 已完成动作
materials: 文件、版本、SHA-256及受控路径
evidence: 页码、章节、单元格或数据库记录定位
candidates: 已规范化候选结果
unresolved: 歧义、冲突和缺失证据
side_effects: 已发生及计划发生的写操作
validation: 已运行检查及结果
requested_decision: 下一模型或用户需要决定的事项
```

不要把整份PDF、工作簿或全量数据库结果重复塞入交接；提供受控路径和精确证据定位，需要时再读取。

## 执行环境不支持切换时

明确说明当前运行器不能按步骤选择模型，并把上述选择作为建议记录。继续使用当前模型完成安全、能力范围内的工作；不要声称已经切换，也不要为了模拟切换而降低验证标准。

## 路由反馈

发现分配不合理时输出：

```text
SKILL_FEEDBACK
skill: vinno-model-routing
issue_type: wrong_model | unnecessary_escalation | missed_escalation | unsupported_runner
input: 原始任务和阶段
observed: 实际模型与结果
expected: 建议模型和原因
current_rule: 命中的现有规则
suggested_change: 最小通用修改
regression_case: 修改后必须通过的路由提示
impact: 对质量、速度、成本或发布风险的影响
```
