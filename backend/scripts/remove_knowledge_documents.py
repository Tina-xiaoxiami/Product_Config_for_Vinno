"""Delete retired controlled materials and their derived knowledge rows."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.knowledge_document_removal import (  # noqa: E402
    KnowledgeDocumentRemovalError,
    remove_knowledge_documents,
)


DEFAULT_DATABASE = BACKEND_ROOT / "product_config.db"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Delete retired (archived) knowledge documents together with their "
            "chunks and extractions. Runs as a dry-run unless --apply is supplied."
        )
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument(
        "--document-id",
        type=int,
        action="append",
        required=True,
        dest="document_ids",
        help="document id to remove; repeat the flag for several ids",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the deletion to the database",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = remove_knowledge_documents(
            args.database, document_ids=tuple(args.document_ids), apply=args.apply
        )
    except KnowledgeDocumentRemovalError as error:
        print("REFUSED " + str(error))
        return 1

    print("MODE apply" if result.apply else "MODE dry-run")
    for item in result.items:
        detail = (
            f"chunks={item.chunk_count} extractions={item.extraction_count} "
            f"citations={item.citation_count}"
        )
        print(
            f"{item.status.upper()} id={item.document_id} "
            f"title={item.title} {detail}"
        )
    summary = " ".join(
        f"{name}={value}" for name, value in sorted(result.counts.items())
    )
    print(f"SUMMARY {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
