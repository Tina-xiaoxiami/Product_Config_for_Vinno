# KH-02 Office 确定性定位合同 v1

阶段：`kh02-office-locator-contract-v1`。日期：2026-11-05。

固定基线为产品 PR40 `44705fb96d08d4cee685d263e3d2cd90de3c7dfd`，以及指南最终发布副本 `/private/tmp/guideline-reader-publish-20261104` 的 `e3e969864573dd9039efbb9b77ad1bc297329dd7`（tree `9dc7d9f5b29ab502e92cf040970724483e7273ed`）。在独立 Git 对象库和分支准备，本阶段不部署、不合 main，不修改真实库、草稿或服务，不接入非PDF模型回答。

## 单一提取与回查链路

继续使用 `knowledge_content` 的 DOCX/XLSX 解析器、`build_document_chunks` 和登记提取事务；`knowledge_sources` 从登记ID与摘要读取同一份不可变原件快照，再用同一解析器重放结构。片段的索引、正文、正文摘要、source_ref、section_name和page_number必须逐项一致；结构坐标由程序生成，不接受调用方提供坐标或文件路径。

不新增数据表或字段。数据库仍保存已有的chunk_index、source_ref、正文和摘要；结构定位在核验请求中从原件重建。PDF/text提取版本继续为2，Office使用独立 `office-locator-v1`。旧Office索引须显式重新提取后才可标记结构已匹配，未自动迁移或批量重提真实资料。

## 响应合同

沿用 `GET /api/knowledge/documents/{document_id}/evidence?version_id={sha256}&chunk_id={id}`。短引可选，按原有6至400字边界核对；Office不使用PDF页号。

返回已有document_id、version_id、source_ref、text、quote、preview_url，同时增加Office专用locator和状态：

```json
{
  "page": null,
  "model_answer_eligible": false,
  "locator": {
    "schema_version": 1,
    "format": "xlsx",
    "kind": "worksheet_row",
    "document_id": 17,
    "source_sha256": "原件SHA256",
    "sheet_name": "规格 表",
    "sheet_index": 1,
    "row_index": 5,
    "range": "A5:C5",
    "cells": [
      {"cell":"A5","column_index":1,"text":"合成规格项","value_type":"literal"},
      {"cell":"C5","column_index":3,"text":"合成值","value_type":"literal"}
    ],
    "formula_state": "not_evaluated"
  },
  "verification": {
    "source":"hash_verified",
    "extraction":"hash_verified",
    "quote":"matched",
    "structure":"matched",
    "visual":"not_checked",
    "human":"not_reviewed"
  }
}
```

示例值仅说明字段。未提供短引时quote核验状态为not_requested。定位详情返回对应原内容及真实结构位置；原件链接仍绑定登记摘要。无Office分页或外部Word/Excel自动跳转承诺。

| 格式/类型 | 真实结构位置 | 覆盖边界 |
| --- | --- | --- |
| DOCX paragraph | `part=word/document.xml`、body_index、paragraph_index | 正文直接段落；索引从1开始并包含空段落，body_index保留被跳过正文节点的位置 |
| DOCX table_row | part、body_index、table_index、row_index、cells | 正文顶层表；物理XML单元格索引及grid_span/vertical_merge，不把合并投影视为独立单元格 |
| XLSX worksheet_row | sheet_name、sheet_index、row_index、range、cells | 原工作表与实际非空单元格地址，空列不压缩；保留合并范围和number_format |

DOCX页眉、页脚及嵌套表正文尚不覆盖，嵌套表存在性会标记。XLSX文本是规范化存储值或原公式，不是Excel渲染显示或计算结果；公式及数组公式保留稳定源码/范围并标记未求值，无法稳定表达的特殊公式明确拒绝。

## 失效和安全边界

- 原件换版、登记摘要不符、提取版本过旧、索引或结构变化返回409/410并要求重新查询/提取；无定位或伪短引分别按原有404/422语义拒绝。不使用其他版本替代。
- 定位和版本锁原件响应沿用no-store；原件读取上限128MiB。Office ZIP最多10000成员、总解压64MiB、单成员16MiB；重复/加密/错误结构、DTD/实体拒绝。XML大小写变体也执行预检。
- 加载openpyxl之前限制实际/声明单元格范围及合并展开预算，最多100000格，避免稀疏巨量范围先分配。公式不执行、不获取外部链接结果。
- 旧XLS明确不支持，不因伪装MIME而转入XLSX解析。格式和MIME冲突拒绝。
- 结构已匹配仅代表文字与位置核验，`visual=not_checked`；不能据此冒充表格原页图像核验、自动生成或发布正式数值答案。生产资料问答继续仅接PDF；指南1.4.1只补拒绝Office伪PDF页号的保护，1.4双语归并及确定性配置/参数路径保持。

## 验证与交付门槛

合成DOCX段落/表格、XLSX多工作表/空列/单元格/合并范围/普通及数组公式，经登记提取和HTTP引用打开后逐项核对原件ID、摘要、结构位置和摘录。覆盖旧版本、原件换版、索引伪造、解析期间换版/ABA、预算/格式攻击及Office生产模型隔离。

产品106项相关回归通过，content/source模块行覆盖91%/90%；精确openpyxl3.1.2下39项Office回归通过，两模块限定mypy及复审通过。指南567项Python回归通过，总覆盖87.76%，Ruff/格式/限定mypy通过；没有JS或界面改动，未重复浏览器/Node套件，也未使用真实资料或业务模型。

父候选和本阶段草稿PR的远端检查分别记录，不以本地结果替代。形成草稿候选不等于父链或本阶段已获得发布资格；本阶段未合 main、未部署。生产非PDF模型接入、原页渲染/视觉核验、旧XLS及真实Office资料业务验收另行推进。
