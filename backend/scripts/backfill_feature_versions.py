"""从 Release Note 正文回填「功能版本」候选，默认只预演。

用法：

    python3 scripts/backfill_feature_versions.py --database /tmp/copy.db
    python3 scripts/backfill_feature_versions.py --database /tmp/copy.db --apply

约定：

- 默认 dry-run，只打印候选，不写库；`--apply` 才写入。
- 运行前会补齐缺失的表（与后端启动时的 init_db 行为一致，只建新表不碰已有数据），
  因此可以直接对正式库副本执行。
- 写入的行一律 `review_status='pending'`、`source='release_note'`，
  确认动作仍由人工在功能发布页完成。
- 「资料中最早出现」不等于「首发版本」：脚本会打印已纳管 Release Note 的最早版本。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.feature_release_backfill import (  # noqa: E402
    apply_feature_version_candidates,
    feature_release_coverage,
    preview_feature_version_candidates,
)


DEFAULT_DATABASE = BACKEND_ROOT / "product_config.db"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Derive feature_versions candidates from Release Note content. "
            "Runs as a dry-run unless --apply is supplied."
        )
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--product-series", default=None)
    parser.add_argument(
        "--version",
        action="append",
        dest="software_versions",
        default=None,
        help="只处理指定软件版本，可重复",
    )
    parser.add_argument(
        "--feature-id",
        action="append",
        dest="feature_ids",
        type=int,
        default=None,
        help="只处理指定功能 ID，可重复",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="按功能汇总回填覆盖情况（不改数据）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出候选，便于存档或复核",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.models  # noqa: F401 - 注册全部模型，保证 create_all 能补齐新表
    from app.database import Base

    database = Path(args.database).expanduser().resolve()
    if not database.is_file():
        print(f"ERROR 数据库不存在：{database}")
        return 2

    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            if args.coverage:
                return await _report_coverage(session, database, args.json)
            preview = await preview_feature_version_candidates(
                session,
                product_series=args.product_series,
                software_versions=args.software_versions,
                feature_ids=args.feature_ids,
                limit=args.limit,
            )
            created = 0
            if args.apply:
                created = await apply_feature_version_candidates(
                    session, preview["candidates"]
                )
    finally:
        await engine.dispose()

    if args.json:
        print(
            json.dumps(
                {**preview, "created": created},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"数据库：{database}")
        print(
            f"候选 {preview['total']} 条（可写入 {preview['applicable']}，"
            f"已存在 {preview['skipped']}）"
        )
        if preview["coverage_note"]:
            print(f"覆盖边界：{preview['coverage_note']}")
        for item in preview["candidates"]:
            marker = "首发候选" if item["is_first_release_candidate"] else item["change_type"]
            print(
                f"  [{marker}] 功能 #{item['feature_id']} {item['feature_name']}"
                f" | {item['software_version']} | {item['product_series'] or '未指定系列'}"
                f" | 命中方式 {item['matched_by']} | {item['evidence_source_ref']}"
                + (f" | {item['skip_reason']}" if item.get("skip_reason") else "")
            )
        if args.apply:
            print(f"已写入 {created} 条待复核候选（review_status=pending）")
        else:
            print("dry-run：未写入任何数据；确认后加 --apply")
    return 0


STATUS_LABELS = {
    "first_release": "有首发证据",
    "other_evidence": "仅其他证据",
    "no_candidate": "无任何候选",
}


async def _report_coverage(session, database: Path, as_json: bool) -> int:
    rows = await feature_release_coverage(session)
    if as_json:
        print(json.dumps({"database": str(database), "coverage": rows}, ensure_ascii=False, indent=2))
        return 0

    counts = {status: 0 for status in STATUS_LABELS}
    for row in rows:
        counts[row["status"]] += 1
    print(f"数据库：{database}")
    print(
        "覆盖：功能 "
        f"{len(rows)} 个 | 有首发证据 {counts['first_release']} | "
        f"仅其他证据 {counts['other_evidence']} | 无任何候选 {counts['no_candidate']}"
    )
    for row in rows:
        name = row["primary_cn_name"] or row["feature_name"]
        detail = (
            f"首发证据 {row['first_release_version']}"
            if row["status"] == "first_release"
            else "—"
        )
        print(
            f"  [{STATUS_LABELS[row['status']]}] #{row['feature_id']} {name}"
            f" | 候选 {row['candidate_count']} 条 | {detail}"
        )
    print(
        "提示：「仅其他证据」的功能多半首发于已纳管资料之前，"
        "需要补充更早的 Release Note 或人工确认；「无任何候选」多为尚未发布的功能。"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
