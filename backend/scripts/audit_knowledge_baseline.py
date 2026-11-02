#!/usr/bin/env python3
"""Write a local, read-only knowledge baseline; never overwrite existing files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.knowledge_baseline import (  # noqa: E402
    KnowledgeBaselineError,
    build_knowledge_baseline,
    validate_baseline_destination,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--release-database", type=Path)
    parser.add_argument("--feature-library", type=Path)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--verify-file-hashes", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise KnowledgeBaselineError("输出文件已存在；请使用新文件名，避免覆盖原件或旧报告")
        validate_baseline_destination(
            args.database, args.output,
            other_inputs=(args.release_database, args.feature_library),
            publication_root=args.publication_root,
        )
        report = build_knowledge_baseline(
            args.database, release_database=args.release_database,
            feature_library=args.feature_library, publication_root=args.publication_root,
            verify_file_hashes=args.verify_file_hashes,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also protects against a destination appearing during collection.
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
        counts = report["sources"]["knowledge"]["counts"]
        print(f"baseline saved: documents={counts['documents']} "
              f"published_answers={counts['published_answers']} "
              f"uncited_answers={counts['published_answers_without_document_citation']}")
        return 0
    except (KnowledgeBaselineError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
