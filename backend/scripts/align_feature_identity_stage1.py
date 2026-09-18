"""阶段 1 功能主数据对齐：默认只预演，`--apply` 才写入。

用法：

    python3 scripts/align_feature_identity_stage1.py --database /tmp/copy.db
    python3 scripts/align_feature_identity_stage1.py --database /tmp/copy.db --apply

写入内容一览（全部来自已裁定项，逐条带裁定编号）：

- H1：EI 的中文主名规范化为「压力式弹性成像」，旧值登记为中文曾用名；
- H4 / H5 / H3 / H7：为 6000242、6000185、6000281、6000075 新建功能身份与曾用名；
- D3：Vmind OB 补 6000294、STIC 补 6000323；
- 关系：PWV+/PWV、STIC/3200476 的 supersedes，CBI 的 supersedes（方向待确认，pending），
  SWE → 点式剪切波的 child；
- H2（穿刺引导/穿刺增强）显式不做任何动作。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.feature_identity_stage1 import (  # noqa: E402
    FeatureIdentityStage1Error,
    apply_stage1,
)


DEFAULT_DATABASE = BACKEND_ROOT / "product_config.db"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Align feature identity for stage 1 (aliases, new identities, relations). "
            "Runs as a dry-run unless --apply is supplied."
        )
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _print_plan(plan: dict) -> None:
    print(f"数据库：{plan['database']}")
    summary = plan["summary"]
    print(
        "计划：新建身份 {new_identities} | 主名规范化 {renames} | 补 IPN {ipn_backfills} | "
        "新关系 {relations} | 跳过 {skipped}".format(**summary)
    )

    for item in plan["new_identities"]:
        if item["action"] == "create":
            aliases = "、".join(item["aliases"]) or "无"
            print(
                f"  [新建身份] {item['ipn']} {item['primary_cn_name']}"
                f"（{item['group_name']}）曾用名：{aliases}  ← {item['a_record']}"
                f" [{item['source_reference']}]"
            )
        else:
            print(f"  [跳过] {item['ipn']} {item['primary_cn_name']} —— {item['reason']}")

    for item in plan["renames"]:
        if item["action"] == "rename":
            print(
                f"  [规范化主名] 功能 #{item['feature_id']} {item['legacy_name']}"
                f"（{item['ipn']}）：{item['current_name']} → {item['normalized_name']}"
                f"（旧值登记为曾用名） [{item['source_reference']}]"
            )
        else:
            print(f"  [跳过] 功能 #{item['feature_id']} 主名规范化 —— {item['reason']}")

    for item in plan["ipn_backfills"]:
        if item["action"] == "backfill":
            print(
                f"  [补 IPN] 功能 #{item['feature_id']} {item['legacy_name']}"
                f" → {item['ipn']}（{item['primary_cn_name']}） [{item['source_reference']}]"
            )
        else:
            print(f"  [跳过] 功能 #{item['feature_id']} 补 IPN —— {item['reason']}")

    for item in plan["relations"]:
        if item["action"] == "create":
            source = (
                f"#{item['source_feature_id']}"
                if item["source_feature_id"]
                else f"{item['source_reference_key']}（本次新建）"
            )
            target = (
                f"#{item['target_feature_id']}"
                if item["target_feature_id"]
                else f"{item['target_reference_key']}（本次新建）"
            )
            print(
                f"  [新关系] {source} --{item['relation_type']}--> {target}"
                f"（{item['review_status']}） {item['rationale']} [{item['source_reference']}]"
            )
        else:
            print(
                f"  [跳过] 关系 #{item['source_feature_id']} → #{item['target_feature_id']}"
                f" —— {item['reason']}"
            )

    if plan["blocked_relations"]:
        print("受阻关系（裁定已明确、但缺端点身份，需先裁定）：")
        for item in plan["blocked_relations"]:
            print(
                f"  - {item['source']} --{item['relation_type']}--> {item['target']}"
                f"（{item['review_status']}）：{item['blocked_by']}"
                f" [{item['source_reference']}]"
            )

    print("本轮不做（已裁定）：")
    for item in plan["ignored"]:
        print(f"  - {item['decision']}：{item['reason']}")

    print("遗留项（需要单独决定）：")
    for item in plan["residuals"]:
        print(f"  - {item}")

    if plan.get("applied"):
        created = plan["created"]
        print(
            f"已写入：功能 {created['features']} 个、名称 {created['names']} 条、"
            f"配置项关联 {created['links']} 条、关系 {created['relations']} 条"
        )
    else:
        print("dry-run：未写入任何数据；确认后加 --apply")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = apply_stage1(args.database, apply=args.apply)
    except FeatureIdentityStage1Error as error:
        print(f"ERROR {error}")
        return 2

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_plan(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
