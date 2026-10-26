from __future__ import annotations

import json
from pathlib import Path

from app.integrations.release_workbench import load_release_workbench_config
from scripts.import_release_workbench_config import build_config_snapshot


def test_local_config_resolves_paths_without_overriding_canonical_database(
    tmp_path: Path,
) -> None:
    backend_root = tmp_path / "backend"
    config_dir = backend_root / "config"
    config_dir.mkdir(parents=True)
    local_config = config_dir / "release_workbench.local.json"
    local_config.write_text(
        json.dumps(
            {
                "database": "../runtime/release.db",
                "release_note_root": "../sources/releases",
                "product_config_database": "/wrong/database.db",
                "source_roots": ["../sources/history"],
            }
        ),
        encoding="utf-8",
    )
    canonical_database = backend_root / "product_config.db"

    config = load_release_workbench_config(
        backend_root=backend_root,
        canonical_database=canonical_database,
        environ={"RELEASE_WORKBENCH_CONFIG": str(local_config)},
    )

    assert config["DATABASE_PATH"] == (backend_root / "runtime/release.db").resolve()
    assert config["RELEASE_NOTE_ROOT"] == str((backend_root / "sources/releases").resolve())
    assert config["SOURCE_ROOTS"] == [str((backend_root / "sources/history").resolve())]
    assert config["PRODUCT_CONFIG_DATABASE"] == canonical_database.resolve()
    assert config["INTEGRATED_MODE"] is True


def test_environment_can_select_existing_history_database(tmp_path: Path) -> None:
    canonical_database = tmp_path / "canonical.db"
    history_database = tmp_path / "legacy" / "feature_tracker.db"

    config = load_release_workbench_config(
        backend_root=tmp_path,
        canonical_database=canonical_database,
        environ={"RELEASE_WORKBENCH_DATABASE": str(history_database)},
    )

    assert config["DATABASE_PATH"] == history_database.resolve()
    assert config["PRODUCT_CONFIG_DATABASE"] == canonical_database.resolve()


def test_snapshot_import_preserves_legacy_relative_path_meaning(tmp_path: Path) -> None:
    source_root = tmp_path / "product-management"
    source_config = source_root / "config" / "local.json"
    source_config.parent.mkdir(parents=True)
    source_config.write_text(
        json.dumps(
            {
                "database": "data/feature_tracker.db",
                "release_note_root": "sources/releases",
                "controlled_materials_root": "sources/controlled",
                "controlled_extraction_roots": ["sources/extracted"],
                "training_root": "training",
                "source_roots": ["sources/history"],
                "workbench": {"home": True},
            }
        ),
        encoding="utf-8",
    )

    snapshot = build_config_snapshot(source_root, source_config)

    assert snapshot["database"] == str((source_root / "data/feature_tracker.db").resolve())
    assert snapshot["release_note_root"] == str((source_root / "sources/releases").resolve())
    assert snapshot["controlled_materials_root"] == str(
        (source_root / "sources/controlled").resolve()
    )
    assert snapshot["controlled_extraction_roots"] == [
        str((source_root / "sources/extracted").resolve())
    ]
    assert snapshot["source_roots"] == [str((source_root / "sources/history").resolve())]
    assert "product_config_database" not in snapshot
