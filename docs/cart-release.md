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

`targets` 是 PPTX 的物理页码和文本形状 ID。每个允许替换的字段应与原模板和对应快照一并核验。规则只替换字数和料号格式一致的文本，保留模板原有文字样式、框线、图片及备注。机型、选配语义、结构调整及尚未核实的映射需要人工处理。手工修订后核验新原件与快照、更新定位，并递增规则版本。

## 补跑

单个版本从「Cart 资料」补跑。批量操作调用 `POST /api/versions/cart-release/backfill`，传入 `series_id`，可用 `after_id`、`through_id`、`limit` 限定范围。按返回的 `next_after_id` 继续，直至为空。跨系列比较按所选版本当时可见的各系列快照计算，历史检查可以和当前检查并存。

归档接口为 `GET /api/versions/cart-release/archive/{key}`，原样下载归档候选使用同一路径的 `/presentation`。
