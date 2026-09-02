# VINNO 产品知识库技能包

这些技能把当前已经确认的业务规则固化为可复用流程，适用于本项目中的其他 AI 助手。

| 场景 | 技能 |
| --- | --- |
| 注册证和注册差异表成对导入、更新、映射和启停 | `vinno-registration-ingest` |
| 说明书、白皮书、Release Note 的登记、提取和事实补充 | `vinno-product-material-ingest` |
| IPN、中英文主名、曾用名和相关功能关系整理 | `vinno-feature-identity-curation` |
| 下游问题整理、答案确认、引用和修订 | `vinno-qa-curation` |
| 检查覆盖率、冲突、缺失数据并生成技能反馈单 | `vinno-knowledge-audit` |

显式调用示例：

```text
请使用 vinno-registration-ingest 处理这组注册证和差异表，先生成草稿和集中待确认项，不要直接发布。
```

如果另一个 AI 不支持自动发现，把对应技能目录或 `SKILL.md` 路径一并提供给它。

可分发的 `.skill` 文件位于 `.agents/skill-packages/`，可按任务只安装一个，避免一次加载全部规则：

- 注册证或差异表：`vinno-registration-ingest.skill`
- 说明书、白皮书或发布记录：`vinno-product-material-ingest.skill`
- 功能名、IPN 或同功能关系：`vinno-feature-identity-curation.skill`
- 新问题和答案沉淀：`vinno-qa-curation.skill`
- 找数据缺口或规则问题：`vinno-knowledge-audit.skill`

为节省 token，建议平时只调用与当前材料相关的一个技能；批次完成后再单独调用审计技能。如果另一个 AI 发现规则缺口，请它保留完整 `SKILL_FEEDBACK`，用于修改对应技能并增加回归用例。

共同约定：原文件必须保留并支持预览；正式写入、发布和启停必须符合用户授权；不确定项集中反馈；业务数据和原始材料不提交 Git；规则缺口统一输出 `SKILL_FEEDBACK`。

修改技能后运行回归检查：

```bash
python3 .agents/skills/validate_skills.py
```
