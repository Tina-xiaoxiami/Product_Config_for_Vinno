"""Snapshot legacy workbench paths into the ignored integrated local config."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tracker.config import load_config


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = BACKEND_ROOT / "config" / "release_workbench.local.json"


def build_config_snapshot(source_root: str | Path, source_config: str | Path) -> dict:
    root = Path(source_root).expanduser().resolve()
    settings = load_config(
        config_path=Path(source_config).expanduser().resolve(),
        environ={},
        project_root=root,
    )
    snapshot: dict[str, object] = {"database": str(settings.database.resolve())}
    optional_paths = {
        "release_note_root": settings.release_note_root,
        "controlled_materials_root": settings.controlled_materials_root,
        "training_root": settings.training_root,
    }
    snapshot.update(
        {key: str(value.resolve()) for key, value in optional_paths.items() if value is not None}
    )
    if settings.source_roots:
        snapshot["source_roots"] = [str(path.resolve()) for path in settings.source_roots]
    if settings.controlled_extraction_roots:
        snapshot["controlled_extraction_roots"] = [
            str(path.resolve()) for path in settings.controlled_extraction_roots
        ]
    snapshot["workbench"] = {"home": False}
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="导入旧工作台的路径配置；不复制数据库或业务资料。"
    )
    parser.add_argument("source_project", type=Path)
    parser.add_argument("--source-config", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    source_root = args.source_project.expanduser().resolve()
    source_config = args.source_config or source_root / "config" / "local.json"
    output = args.output.expanduser().resolve()
    if output.exists() and not args.force:
        parser.error(f"输出文件已存在：{output}（如需覆盖请加 --force）")
    snapshot = build_config_snapshot(source_root, source_config)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已写入本机配置：{output}；未复制任何数据库或资料文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

