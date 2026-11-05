"""Incrementally register product materials from the controlled Obsidian tree."""

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
    import_controlled_product_materials,
    validate_controlled_materials_root,
)


DEFAULT_DATABASE = BACKEND_ROOT / "product_config.db"
DEFAULT_CONTROLLED_ROOT = CONTROLLED_MATERIALS_ROOT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Incrementally register controlled manuals, whitepapers, and Release Notes. "
            "Runs as a dry-run unless --apply is supplied."
        )
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--controlled-root", type=Path, default=DEFAULT_CONTROLLED_ROOT)
    parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        validate_controlled_materials_root(args.controlled_root)
    except ControlledMaterialsRootError as error:
        print(f"ERROR {error}")
        return 2
    result = import_controlled_product_materials(
        args.database,
        args.controlled_root,
        apply=args.apply,
    )
    print("MODE apply" if result.apply else "MODE dry-run")
    for item in result.items:
        if item.status in {"ready", "inserted", "name_conflict", "duplicate_content"}:
            print(
                f"{item.status.upper()} type={item.document_type} "
                f"id={item.document_id or '-'} path={item.path}"
            )
    print(
        "SUMMARY "
        + " ".join(f"{name}={value}" for name, value in sorted(result.counts.items()))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
