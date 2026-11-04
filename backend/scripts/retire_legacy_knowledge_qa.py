#!/usr/bin/env python3
"""Preview, archive/retire, or recover unscoped historical questions only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.knowledge_qa_retirement import (  # noqa: E402
    RetirementError, preview_retirement, retire_legacy_qa, restore_legacy_qa,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preview = commands.add_parser('preview', help='只读预览scope_key为空的历史问答')
    preview.add_argument('--database', type=Path, required=True)
    retire = commands.add_parser('retire', help='默认演练；--apply才执行，先保全归档和在线整库备份')
    retire.add_argument('--database', type=Path, required=True)
    retire.add_argument('--expected-fingerprint')
    retire.add_argument('--archive', type=Path)
    retire.add_argument('--backup', type=Path)
    retire.add_argument('--apply', action='store_true')
    restore = commands.add_parser('restore', help='仅恢复归档原始问答行；冲突时拒绝覆盖，默认演练')
    restore.add_argument('--database', type=Path, required=True)
    restore.add_argument('--archive', type=Path, required=True)
    restore.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'preview':
            result = preview_retirement(args.database)
        elif args.command == 'retire':
            result = retire_legacy_qa(args.database, expected_fingerprint=args.expected_fingerprint,
                                      archive_path=args.archive, backup_path=args.backup, apply=args.apply)
        else:
            result = restore_legacy_qa(args.database, args.archive, apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except RetirementError as error:
        print('error: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
