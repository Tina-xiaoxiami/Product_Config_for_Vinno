#!/usr/bin/env python3
"""Export or safely restore controlled knowledge Q&A data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.knowledge_qa_snapshot import (  # noqa: E402
    KnowledgeQaSnapshotError,
    export_knowledge_qa_snapshot,
    restore_knowledge_qa_snapshot,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--database", type=Path, required=True)
    export_parser.add_argument("--output", type=Path, required=True)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--database", type=Path, required=True)
    restore_parser.add_argument("--input", type=Path, required=True)
    restore_parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "export":
            snapshot = export_knowledge_qa_snapshot(args.database)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                f"exported questions={len(snapshot['questions'])} "
                f"sha256={snapshot['snapshot_sha256']} output={args.output}"
            )
            return 0

        snapshot = json.loads(args.input.read_text(encoding="utf-8"))
        result = restore_knowledge_qa_snapshot(
            args.database,
            snapshot,
            apply=args.apply,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (KnowledgeQaSnapshotError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
