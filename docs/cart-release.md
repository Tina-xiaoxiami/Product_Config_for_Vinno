# Cart 发货资料检查

打开「版本历史」中某个配置版本的「Cart 资料」。保存配置版本、发布草稿、发布关联配置快照及回滚时，系统在同一事务记录检查结果。检查复用配置项身份、历史机型和空值处理，跟踪最终配置、选型类别、物料身份与描述。历史版本可补跑。回滚检查使用回滚实际保存的快照，沿用系统对共享物料主数据的处理。

检查按市场分别保存。变更记录列出修改前后、型号、快照来源和受影响页面。命中明确的替换规则且区域内证据一致时生成候选 PPT。缺少基线、页面定位、机型或料号映射时进入待核。候选和变更记录按版本归档，同一文件内容复用存储。生成历史在配置版本删除后可凭变更记录中的 `version.key` 查阅。正式成品与人工修订由原资料目录管理。

## 配置核验规则

通过服务环境变量 `CART_RELEASE_RULES_FILE` 指向受控 JSON。每个市场分别绑定 PPTX 原件 SHA-256、系列快照和允许的替换。优先按 SHA-256 从现有资料登记读取原件，也可通过 `CART_RELEASE_TEMPLATE_ROOT` 提供包含 `国内/` 和 `海外/` 的受控目录。真实模板和规则文件应放在部署方的资料存储中。

以下使用虚构示例。每个基线的 `sha256` 取该版本数据库原始 `snapshot_data` 的 UTF-8 字节，模板取 PPTX 文件字节。

```json
{
  "version": "example-1",
  "templates": {
    "domestic": {
      "filename": "example.pptx",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "anchors": [{
        "series": "Example-China",
        "version": "1.0.0",
        "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
      }],
      "rules": [{
        "series": ["Example-China"],
        "code": "V70001",
        "ipn": "7000001-1",
        "field": "ipn",
        "targets": [[7, "4"]]
      }],
      "review_notes": ["新增型号和选配范围须单独核对。"]
    }
  },
  "common_pages": {},
  "market_pages": {"domestic": {"V70001": [3, 7]}},
  "ipn_pages": {}
}
```

`targets` 是 PPTX 的物理页码和文本形状 ID。`selection_rules` 可以绑定全适用范围一致的标配和选配转换。规则需要物料身份、基线状态、同长原文及替换短语，各系列的最终配置和选型须共同支持转换。每个允许替换的字段应与原模板和对应快照一并核验。料号规则只替换字数和料号格式一致的文本，保留模板原有文字样式、框线、图片及备注。机型、选配语义、结构调整及尚未核实的映射需要人工处理。手工修订后核验新原件与快照、更新定位，并递增规则版本。

## 补跑

单个版本从「Cart 资料」补跑。批量操作调用 `POST /api/versions/cart-release/backfill`，传入 `series_id`，可用 `after_id`、`through_id`、`limit` 限定范围。按返回的 `next_after_id` 继续，直至为空。跨系列比较按所选版本当时可见的各系列快照计算，历史检查可以和当前检查并存。

归档接口为 `GET /api/versions/cart-release/archive/{key}`，原样下载归档候选使用同一路径的 `/presentation`。

## 公共事实联动

Cart 模板可以通过 `facts` 绑定公共事实键，通过 `watch_facts` 记录有影响页码且尚无可自动更新位置的事实。每个 `facts` 规则提供原文字段 `original`、含字段占位符的 `replacement`、字段到事实键的映射 `facts` 及原页形状 `targets`。事实须有可核验的原件版本和位置。带测试条件的事实需提供同时展示条件的值。可变长度替换限原段落已核验的文字空间，候选在原模板的相关形状内替换。

`excluded_codes` 与 `excluded_ipns` 用于过滤专用物料，`excluded_pages` 用于保护模板中的整页。混合配置按机型拆分，保留职责范围内的条目。只更改相关的候选页面，原模板、旧候选和事实快照均可沿归档记录追溯。

公共事实服务拥有事实、来源及待决根因。Cart 将同一根因在各市场的页码和归档键回传。资料变动通过 `refresh_cart_for_facts(db, fact_keys)` 重新核验受影响的市场，调用方提交事务。候选内容相同会复用文件，来源版本有变时保留新的证据记录。历史接口为 `GET /api/versions/{version_id}/cart-release/history`。

联动接口由知识侧的 `knowledge_cart_facts` 提供。其 `resolve_cart_fact(db, key, market, config_versions)` 返回事实状态、值和条件、原件版本及位置。需要合并核对的事实返回根因键，`link_cart_fact_impact(db, root_key, impact)` 接收市场、页码和归档键。


联调时使用数据库副本，并由知识侧的 `scripts/apply_knowledge_facts.py` 导入受控事实文件。导入会在同一事务更新受影响的知识依据和 Cart 候选。当前成品仍由模板资料登记及哈希定位，候选记录显示相对上一份候选实际变更的页面。知识待决接口按根因同时返回受影响答案和 Cart 页。
