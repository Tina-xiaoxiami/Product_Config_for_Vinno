"""Mount the vendored release workbench inside the canonical FastAPI process."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from fastapi import FastAPI
from flask import Flask
from starlette.middleware.wsgi import WSGIMiddleware

from tracker.app import create_app
from tracker.config import load_config


MOUNT_PATH = "/release-workbench"
BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL_CONFIG = BACKEND_ROOT / "config" / "release_workbench.local.json"
DEFAULT_DATABASE = BACKEND_ROOT / "data" / "release_workbench.db"


def load_release_workbench_config(
    *,
    canonical_database: str | Path,
    backend_root: str | Path = BACKEND_ROOT,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Load local paths while forcing all canonical reads to the active database."""
    root = Path(backend_root).expanduser().resolve()
    variables = os.environ if environ is None else environ
    configured_path = str(variables.get("RELEASE_WORKBENCH_CONFIG", "")).strip()
    default_path = root / "config" / "release_workbench.local.json"
    explicit_config = Path(configured_path).expanduser() if configured_path else None
    database_override = str(variables.get("RELEASE_WORKBENCH_DATABASE", "")).strip()
    settings = load_config(
        database=database_override or None,
        product_config_database=Path(canonical_database).expanduser().resolve(),
        config_path=explicit_config,
        default_config_path=default_path,
        environ=variables,
        project_root=root,
    )
    config = settings.as_flask_config()
    if settings.config_path is None and not database_override:
        config["DATABASE_PATH"] = root / "data" / "release_workbench.db"
    config.update(
        {
            "PRODUCT_CONFIG_DATABASE": Path(canonical_database).expanduser().resolve(),
            "INTEGRATED_MODE": True,
            "INTEGRATED_ALLOWED_VIEWS": ["search", "review", "releases", "compare"],
            "WORKBENCH_HOME": False,
        }
    )
    return config


def create_integrated_workbench(config: Mapping[str, Any]) -> Flask:
    effective = dict(config)
    effective.update(
        {
            "INTEGRATED_MODE": True,
            "INTEGRATED_ALLOWED_VIEWS": ["search", "review", "releases", "compare"],
            "WORKBENCH_HOME": False,
        }
    )
    return create_app(effective)


def close_release_workbench(workbench: Flask) -> None:
    maintenance = workbench.extensions.get("search_maintenance")
    if maintenance is not None:
        maintenance.close()


def mount_release_workbench(host: FastAPI, workbench: Flask) -> None:
    host.mount(MOUNT_PATH, WSGIMiddleware(workbench), name="release-workbench")
    host.add_event_handler("shutdown", lambda: close_release_workbench(workbench))


def install_release_workbench(host: FastAPI, *, canonical_database: str | Path) -> Flask:
    config = load_release_workbench_config(canonical_database=canonical_database)
    workbench = create_integrated_workbench(config)
    mount_release_workbench(host, workbench)
    return workbench

