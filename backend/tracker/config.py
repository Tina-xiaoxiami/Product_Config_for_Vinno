"""应用配置加载：CLI 参数 > 环境变量 > 配置文件 > 内置默认值。

配置文件默认读取 `config/local.json`（不入版本库，模板见 `config/example.json`）。
只用标准库，不引入 dotenv 之类的依赖。

键与对应关系：

| 配置文件键 | 环境变量 | Flask 配置键 | 内置默认值 |
|---|---|---|---|
| `database` | `FEATURE_TRACKER_DATABASE` | `DATABASE_PATH` | `data/feature_tracker.db` |
| `release_note_root` | `FEATURE_TRACKER_RELEASE_NOTES` | `RELEASE_NOTE_ROOT` | 无（不注册来源目录） |
| `product_config_database` | `PRODUCT_CONFIG_DATABASE` | `PRODUCT_CONFIG_DATABASE` | iCloud 下的配置系统主库 |
| `workbench.home` | —（仅配置文件） | `WORKBENCH_HOME` | `true` |
| `controlled_materials_root` | `CONTROLLED_MATERIALS_ROOT` | `CONTROLLED_MATERIALS_ROOT` | 无（未配置即如实标未配置） |
| `controlled_extraction_roots` | — | `CONTROLLED_EXTRACTION_ROOTS` | []（只读已登记的独立抽取源） |
| `training_root` | `TRAINING_ROOT` | `TRAINING_ROOT` | 无（未配置即如实标未配置） |
| `product_config_system_url` | `PRODUCT_CONFIG_SYSTEM_URL` | `PRODUCT_CONFIG_SYSTEM_URL` | 无（未配置即不提供入口） |
| `source_roots` | —（仅配置文件） | `SOURCE_ROOTS` | 空（此时只允许上面三个只读根） |

约定：

- 空字符串（含纯空白）一律视为未设置，回落到下一优先级——避免空值被当成有效路径；
- 相对路径按项目根目录解析，`~` 按当前用户展开；
- 配置文件里出现未知键直接报错，避免拼错的键被当成“已生效”；
- `workbench.home=false` 关闭工作台首页，默认页回落版本中心（回退开关）；
- `tracker/app.py` 与 `manage.py` 都经由此模块取值，不再各自读取环境变量。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "local.json"

ENV_DATABASE = "FEATURE_TRACKER_DATABASE"
ENV_RELEASE_NOTE_ROOT = "FEATURE_TRACKER_RELEASE_NOTES"
ENV_PRODUCT_CONFIG_DATABASE = "PRODUCT_CONFIG_DATABASE"
ENV_CONTROLLED_MATERIALS_ROOT = "CONTROLLED_MATERIALS_ROOT"
ENV_TRAINING_ROOT = "TRAINING_ROOT"
ENV_PRODUCT_CONFIG_SYSTEM_URL = "PRODUCT_CONFIG_SYSTEM_URL"

DATABASE_KEY = "database"
RELEASE_NOTE_ROOT_KEY = "release_note_root"
PRODUCT_CONFIG_DATABASE_KEY = "product_config_database"
CONTROLLED_MATERIALS_ROOT_KEY = "controlled_materials_root"
TRAINING_ROOT_KEY = "training_root"
PRODUCT_CONFIG_SYSTEM_URL_KEY = "product_config_system_url"
SOURCE_ROOTS_KEY = "source_roots"
CONTROLLED_EXTRACTION_ROOTS_KEY = "controlled_extraction_roots"
WORKBENCH_KEY = "workbench"
WORKBENCH_HOME_KEY = "home"

# 顺序即报错提示里的展示顺序。
KNOWN_KEYS = (
    DATABASE_KEY,
    RELEASE_NOTE_ROOT_KEY,
    PRODUCT_CONFIG_DATABASE_KEY,
    CONTROLLED_MATERIALS_ROOT_KEY,
    TRAINING_ROOT_KEY,
    PRODUCT_CONFIG_SYSTEM_URL_KEY,
    WORKBENCH_KEY,
    SOURCE_ROOTS_KEY,
    CONTROLLED_EXTRACTION_ROOTS_KEY,
)
WORKBENCH_KEYS = (WORKBENCH_HOME_KEY,)

DEFAULT_DATABASE = PROJECT_ROOT / "data" / "feature_tracker.db"
DEFAULT_PRODUCT_CONFIG_DATABASE = (
    Path.home()
    / "Library/Mobile Documents/com~apple~CloudDocs/Documents/项目"
    / "产品配置管理系统/backend/product_config.db"
)


class ConfigurationError(Exception):
    """配置缺失或损坏。消息面向操作者，应能直接照着处理。"""


@dataclass(frozen=True)
class AppConfig:
    database: Path
    product_config_database: Path
    release_note_root: Path | None = None
    controlled_materials_root: Path | None = None
    training_root: Path | None = None
    source_roots: tuple[Path, ...] = ()
    controlled_extraction_roots: tuple[Path, ...] = ()
    product_config_system_url: str | None = None
    workbench_home: bool = True
    config_path: Path | None = None

    def as_flask_config(self) -> dict[str, Any]:
        """转成 Flask 配置字典，键名沿用 `create_app` 既有约定。"""
        return {
            "DATABASE_PATH": self.database,
            "RELEASE_NOTE_ROOT": (
                str(self.release_note_root) if self.release_note_root is not None else None
            ),
            "PRODUCT_CONFIG_DATABASE": self.product_config_database,
            "CONTROLLED_MATERIALS_ROOT": (
                str(self.controlled_materials_root)
                if self.controlled_materials_root is not None
                else None
            ),
            "TRAINING_ROOT": (
                str(self.training_root) if self.training_root is not None else None
            ),
            "PRODUCT_CONFIG_SYSTEM_URL": self.product_config_system_url,
            "SOURCE_ROOTS": [str(path) for path in self.source_roots],
            "CONTROLLED_EXTRACTION_ROOTS": [str(path) for path in self.controlled_extraction_roots],
            "WORKBENCH_HOME": self.workbench_home,
        }


def load_config(
    *,
    database: str | Path | None = None,
    release_note_root: str | Path | None = None,
    product_config_database: str | Path | None = None,
    config_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    project_root: Path = PROJECT_ROOT,
    default_config_path: str | Path | None = None,
) -> AppConfig:
    """按 CLI > 环境变量 > 配置文件 > 内置默认值解析配置。

    `config_path` 由调用方显式给出时文件必须存在（写错了要立刻知道）；
    走默认路径时文件可以不存在，此时直接使用环境变量与内置默认值。
    """
    variables: Mapping[str, str] = os.environ if environ is None else environ
    file_settings, used_path = _read_config_file(
        config_path,
        project_root=project_root,
        default_config_path=default_config_path,
    )

    database_value = _first_set(database, variables.get(ENV_DATABASE), file_settings.get(DATABASE_KEY))
    product_config_value = _first_set(
        product_config_database,
        variables.get(ENV_PRODUCT_CONFIG_DATABASE),
        file_settings.get(PRODUCT_CONFIG_DATABASE_KEY),
    )
    release_note_value = _first_set(
        release_note_root,
        variables.get(ENV_RELEASE_NOTE_ROOT),
        file_settings.get(RELEASE_NOTE_ROOT_KEY),
    )
    materials_value = _first_set(
        variables.get(ENV_CONTROLLED_MATERIALS_ROOT),
        file_settings.get(CONTROLLED_MATERIALS_ROOT_KEY),
    )
    training_value = _first_set(
        variables.get(ENV_TRAINING_ROOT),
        file_settings.get(TRAINING_ROOT_KEY),
    )
    config_system_value = _first_set(
        variables.get(ENV_PRODUCT_CONFIG_SYSTEM_URL),
        file_settings.get(PRODUCT_CONFIG_SYSTEM_URL_KEY),
    )

    return AppConfig(
        database=(
            _as_path(database_value, project_root) if database_value else DEFAULT_DATABASE
        ),
        product_config_database=(
            _as_path(product_config_value, project_root)
            if product_config_value
            else DEFAULT_PRODUCT_CONFIG_DATABASE
        ),
        release_note_root=(
            _as_path(release_note_value, project_root) if release_note_value else None
        ),
        controlled_materials_root=(
            _as_path(materials_value, project_root) if materials_value else None
        ),
        training_root=(
            _as_path(training_value, project_root) if training_value else None
        ),
        product_config_system_url=config_system_value,
        source_roots=tuple(
            _as_path(root, project_root) for root in (file_settings.get(SOURCE_ROOTS_KEY) or [])
        ),
        controlled_extraction_roots=tuple(
            _as_path(root, project_root)
            for root in (file_settings.get(CONTROLLED_EXTRACTION_ROOTS_KEY) or [])
        ),
        workbench_home=_workbench_home(file_settings),
        config_path=used_path,
    )


def _workbench_home(file_settings: Mapping[str, Any]) -> bool:
    """首页开关只来自配置文件（或 `create_app` 的显式覆盖），默认开启。"""
    workbench = file_settings.get(WORKBENCH_KEY) or {}
    return bool(workbench.get(WORKBENCH_HOME_KEY, True))


def _first_set(*candidates: object) -> str | None:
    """返回第一个有值的候选；`None`、空字符串与纯空白都算未设置。"""
    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text:
            return text
    return None


def _as_path(value: str, project_root: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_root / path


def _read_config_file(
    config_path: str | Path | None,
    *,
    project_root: Path,
    default_config_path: str | Path | None = None,
) -> tuple[dict[str, Any], Path | None]:
    """读取配置文件；未显式指定且默认文件不存在时返回空设置。"""
    if config_path is not None:
        path = _as_path(str(config_path), project_root)
        if not path.is_file():
            raise ConfigurationError(f"配置文件不存在：{path}")
    else:
        path = (
            _as_path(str(default_config_path), project_root)
            if default_config_path is not None
            else DEFAULT_CONFIG_PATH
        )
        if not path.is_file():
            return {}, None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigurationError(
            f"配置文件不是合法 JSON：{path}"
            f"（第 {error.lineno} 行第 {error.colno} 列：{error.msg}）"
        ) from error
    except OSError as error:
        raise ConfigurationError(f"配置文件无法读取：{path}（{error.strerror}）") from error

    if not isinstance(raw, dict):
        raise ConfigurationError(f"配置文件顶层必须是 JSON 对象：{path}")

    unknown = sorted(key for key in raw if key not in KNOWN_KEYS)
    if unknown:
        raise ConfigurationError(
            f"配置文件存在未知键：{', '.join(unknown)}"
            f"（可用键：{', '.join(KNOWN_KEYS)}）：{path}"
        )

    settings: dict[str, Any] = {}
    for key in KNOWN_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if value is None:
            settings[key] = None
            continue
        if key == WORKBENCH_KEY:
            settings[key] = _validate_workbench(value, path)
            continue
        if key in {SOURCE_ROOTS_KEY, CONTROLLED_EXTRACTION_ROOTS_KEY}:
            settings[key] = _validate_source_roots(value, path, key=key)
            continue
        if not isinstance(value, str):
            raise ConfigurationError(
                f"配置项 {key} 必须是字符串，实际是 {type(value).__name__}：{path}"
            )
        settings[key] = value
    return settings, path


def _validate_source_roots(value: Any, path: Path, *, key: str = SOURCE_ROOTS_KEY) -> list[str]:
    """校验 `source_roots`：允许登记为来源目录的额外根，字符串数组。

    它只放宽「网页能登记哪些目录」，不注册任何来源；三个只读根
    （`release_note_root` / `controlled_materials_root` / `training_root`）
    始终允许，所以不配置本项时行为与以前一致（那时是三个根 + 任意路径，
    现在只剩三个根——任意路径正是本次修掉的越权）。
    """
    if not isinstance(value, list):
        raise ConfigurationError(
            f"配置项 {key} 必须是字符串数组，实际是 {type(value).__name__}：{path}"
        )
    roots: list[str] = []
    for item in value:
        if item is None or not isinstance(item, str):
            raise ConfigurationError(
                f"配置项 {key} 的每一项都必须是字符串，"
                f"实际出现 {type(item).__name__}：{path}"
            )
        if item.strip():
            roots.append(item)
    return roots


def _validate_workbench(value: Any, path: Path) -> dict[str, bool]:
    """校验 `workbench` 段：只接受已知布尔开关。"""
    if not isinstance(value, dict):
        raise ConfigurationError(
            f"配置项 {WORKBENCH_KEY} 必须是 JSON 对象，实际是 {type(value).__name__}：{path}"
        )

    unknown = sorted(key for key in value if key not in WORKBENCH_KEYS)
    if unknown:
        raise ConfigurationError(
            f"配置项 {WORKBENCH_KEY} 存在未知键：{', '.join(unknown)}"
            f"（可用键：{', '.join(WORKBENCH_KEYS)}）：{path}"
        )

    settings: dict[str, bool] = {}
    for key in WORKBENCH_KEYS:
        if key not in value or value[key] is None:
            continue
        if not isinstance(value[key], bool):
            raise ConfigurationError(
                f"配置项 {WORKBENCH_KEY}.{key} 必须是 true 或 false，"
                f"实际是 {type(value[key]).__name__}：{path}"
            )
        settings[key] = value[key]
    return settings
