# 面向 main 的整合候选（2026-11-04）

## 固定输入与审阅边界

- 实时 GitHub `main`：`e022942425c79510f35ae470b3c7df0ab72104d9`。
- 固定交付输入：PR #39 的 `d3db8762a42f5ed94b11e3dfe0d2212b48d26442`，已包含 #37、#38、测量排序/批次管理及国家资料提交。
- 输入相对 main：800 个提交、564 个文件，增加 142,352 行、删除 6,538 行，其中 219 个文件位于测试目录。此数值是固定输入的差异，不包含本次测试修复及本文。
- `backend/resources/measurement_calculation_suggestions_1.51.90.json` 单独占 35,600 行，是已有的待人工核对建议资源，不是临床计算器或实际数据库。
- 本候选继承已交付的完整固定历史，不重复 cherry-pick，不修改旧专题 PR 的 base。专题 PR 用于增量审阅，本 PR 用于核对完整树相对 main 的缺口。
- 文件清单与精确差异以 `git diff --name-status e022942 d3db876` 及汇总 PR 的 Files changed 为准。本次是范围与整合阻断检查，不是对 800 个历史提交逐行重新认证。

## 交付范围映射

| 已批准领域 | 对应代码与关键行为 | 关联审阅记录 |
| --- | --- | --- |
| 配置与型号 | `backend/app/api/{config,drafts,models,versions,import_export}.py`，配置历史/工作簿/发布/机型身份服务，前端 Config、Models、Versions、Compare；停用保留历史、分组、导入身份及版本预检 | #3–#7、#10 |
| 国家与注册资料 | RegistrationManage、countryNames、registration API，overseas/registration 服务；中文国名、紧凑注册工作区、PDF/差异表只读预解析 | #2；`097b61b`→`6eea38e`→`19ff152` |
| 模板、探头与应用 | ProbeConfig/ProbeModelsView/TemplateFeatures/ApplicationsView，probe/template/application API 与服务，子系列组合、共同总集、机型差异、模板自动定义、列宽/滚动、标准名/独立显示名、应用草稿 | #11、#14、#16、#21、#30、#34、#35、#37 |
| 测量库 | measurements/measurement_workspace API、schema、服务，MeasurementLibrary 与控件、计算建议资源、导入工具；应用/模式筛选、草稿/版本、字典排序、来源批次管理 | #13、#20、#31、#33；`fe489a1` 至 `1b6c60b` 的 6 项含测试提交 |
| 功能发布 | FeatureRelease/ReleaseWorkspace、release API、`backend/tracker/` 及其 FastAPI 挂载；正文/更新记录、版本演变、证据查询、发布工作区 | #7、#18；`backend/tracker/VENDOR.md` 记录来源与整合模式 |
| KH-02 | knowledge API/schema/service、KnowledgeHub 与证据/引用/参数/历史组件、guideline_evidence 桥接；范围隔离、历史溯源、原页核验、双语去重 | #8、#12、#15、#19、#22、#24–#27、#29、#32、#36、#38、#39 |
| 共用界面与运行依赖 | App/Layout/router、工作区样式、TableColumnSettings/ResizableSidebar、service_manager、启动/停止脚本、依赖声明、CI、测试 fixture 与操作文档 | #17、#23、#28；属于上述交付共用依赖 |

这些路径都能映射到既有产品领域；较早提交仅通过领域映射不能证明其全部业务决定均发生于本周。下列具体历史内容需在汇总审阅中单列。

## 历史范围单列与建议

1. `backend/tracker/services/{description_model,description_settings,scenario_descriptions}.py`、`tracker/config.py`、`tracker/database.py`：包含 10 月既有的模型自动描述、独立手工修订、调用记录和 token 预算机制。VENDOR.md 有出处，但这轮七类交付摘要没有给出其每一项原始人类决定。建议保留为既有发布工作区代码依赖，CEO 核对原发布工作区目标后再批准整合；本轮不设置模型、修改预算、调用模型或执行迁移。
2. `backend/scripts/align_feature_identity_stage1.py`、`backend/app/services/{feature_identity_stage1,feature_identity_migration}.py` 及 `docs/阶段1-功能主数据对齐-20260918.md`、`docs/功能主数据映射-A到B-20260913.md`：含早期功能身份裁定及手工迁移工具。不能把继承这些工具等同于授权处理当前 54 项名称歧义。建议保留代码与裁定出处，禁止在本次整合执行工具；任何新身份决定另走原业务目标。
3. `.agents/skills/vinno-product-material-ingest/SKILL.md` 的受控 Obsidian 根目录修正，以及 AGENTS.md 的 9 行提交约定：属于历史维护规则而非本周产品功能。前者对应 controlled_material_import 的既有路径校验，后者与现有人类全局约定一致，建议保留；不把旧维护规则扩张为新的写库/发布授权。

未因上述范围判断删除、替换或执行历史业务代码；汇总 PR 保持草稿。这些是具体的范围核对项，不是新增实现任务。

## 测量来源批次浏览器失败

固定输入 CI：Actions `41854774734` 的 `probe-browser` 有 14 项通过、1 项失败，失败为 `frontend/e2e/measurements.spec.js:240`。

旧断言对来源批次 `combobox` 使用 `toHaveValue(/batch-newer-test/)`。失败日志中的目标是 `<input readonly value="">`；项目锁定的 Element Plus 实现将输入值与选中标签分开，非搜索输入保持空字符串。实际组件使用 numeric batch id 的 v-model，并在 `.batch-select` 显示 `版本 · 文件 · #批次ID`。因此空 input 不能证明选中批次为空。

本次只修正 E2E 的观察位置，不修改生产组件：

- 验证初始可见标签含准确版本、文件和批次 ID；当前批次的切换按钮禁用。
- 打开列表核对当前 option 的 `aria-selected=true`。
- 选择旧批次后检查标签与按钮启用，再确认工作区版本切到旧批次。
- 保留进入历史快照的只读验证，再从管理入口切回新批次并确认退出只读状态。
- 不跳过测试，不放宽超时，不移除批次切换断言。

本地前端 724 项单元测试和构建通过。浏览器回归使用仓库既有 GitHub Linux `npm run test:e2e` 流程；不在本机启动浏览器，不占用运行中的 3006/8086 端口。最终运行号和结果记录在 PR 验证说明中。

## 真实资源保护

- 唯一实施目录为独立 worktree `main-integration-20261104`；不把共享运行目录的 WIP 收入提交。
- 未启动真实应用、执行数据同步/导入/迁移、修改任何真实数据库、子系列文件或草稿。
- 不部署，不合并 main，不发布配置版本，也不处理 54 项名称映射的新业务判断。
- 本 PR 审阅通过不代替今后部署前对真实数据库迁移、配置及备份的检查。
