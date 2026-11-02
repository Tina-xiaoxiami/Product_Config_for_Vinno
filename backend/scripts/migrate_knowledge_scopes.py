#!/usr/bin/env python3
"""Inspect a selected Q&A database; --apply backs up and migrates scope identities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.knowledge_scope_migration import (  # noqa: E402
    KnowledgeScopeMigrationError,
    migrate_knowledge_scopes,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="明确的数据库路径；无默认正式库")
    parser.add_argument("--apply", action="store_true", help="在线备份后，在单个事务内迁移问答范围")
    args = parser.parse_args()
    try:
        print(json.dumps(migrate_knowledge_scopes(args.database, apply=args.apply), ensure_ascii=False, indent=2))
        return 0
    except KnowledgeScopeMigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
