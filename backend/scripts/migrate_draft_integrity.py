"""Inspect or repair duplicate config drafts in one explicitly named SQLite database."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.draft_integrity import migrate_sqlite_draft_integrity  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        required=True,
        type=Path,
        help="要检查的 SQLite 数据库明确路径；没有默认正式库路径",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="单事务删除完全相同的冗余草稿、刷新受影响批次计数并创建唯一索引",
    )
    args = parser.parse_args()
    report = migrate_sqlite_draft_integrity(args.database, apply=args.apply)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
