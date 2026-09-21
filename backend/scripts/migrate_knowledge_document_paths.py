"""Repoint verified product materials from iCloud to controlled Obsidian files."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.controlled_material_import import (  # noqa: E402
    CONTROLLED_MATERIALS_ROOT,
    ControlledMaterialsRootError,
    validate_controlled_materials_root,
)
from app.services.knowledge_document_path_migration import (  # noqa: E402
    migrate_knowledge_document_paths,
)


DEFAULT_DATABASE = BACKEND_ROOT / "product_config.db"
DEFAULT_SOURCE_ROOT = (
    Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
)
DEFAULT_TARGET_ROOT = CONTROLLED_MATERIALS_ROOT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify controlled Obsidian copies and migrate knowledge_documents paths. "
            "Runs as a dry-run unless --apply is supplied."
        )
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--target-root", type=Path, default=DEFAULT_TARGET_ROOT)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write verified path changes to the database",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        validate_controlled_materials_root(args.target_root)
    except ControlledMaterialsRootError as error:
        print(f"ERROR {error}")
        return 2
    result = migrate_knowledge_document_paths(
        args.database,
        source_root=args.source_root,
        target_root=args.target_root,
        apply=args.apply,
    )

    print("MODE apply" if result.apply else "MODE dry-run")
    for item in result.items:
        if item.status in {"ready", "updated"}:
            print(
                f"{item.status.upper()} id={item.document_id} "
                f"source={item.source_path} target={item.target_path}"
            )
        elif item.status not in {"outside_source_root", "unsupported_type"}:
            print(
                f"SKIP id={item.document_id} status={item.status} "
                f"source={item.source_path}"
            )
    summary = " ".join(
        f"{name}={value}" for name, value in sorted(result.counts.items())
    )
    print(f"SUMMARY {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
