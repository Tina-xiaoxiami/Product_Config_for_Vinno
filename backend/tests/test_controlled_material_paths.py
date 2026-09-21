from __future__ import annotations

import importlib.util
from pathlib import Path
import re

import pytest

from app.services.controlled_material_import import (
    CONTROLLED_MATERIALS_ROOT,
    ControlledMaterialsRootError,
    validate_controlled_materials_root,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent

#: 迁移时误建的旁支目录写法：`~/Documents/Obsidian/...`（缺 " Vault"）。
#: 曾有三处各自硬编码受控材料根目录、其中两处用这种写法，把登记写进了旁支目录，
#: 留下 knowledge_documents id=19/21 两条指向不存在文件的记录（已清理）。
DIVERGENT_ROOT_PATTERNS = (
    re.compile(r"Documents/Obsidian/"),
    re.compile(r'Obsidian" */ *"产品配置管理系统'),
)


def test_canonical_root_points_at_the_real_vault() -> None:
    """规范根目录必须是真实 Obsidian 库，而不是迁移误建的旁支目录。"""

    assert CONTROLLED_MATERIALS_ROOT.name == "受控材料"
    assert "Obsidian Vault" in CONTROLLED_MATERIALS_ROOT.parts
    assert CONTROLLED_MATERIALS_ROOT == (
        Path.home() / "Documents" / "Obsidian Vault" / "产品配置管理系统" / "受控材料"
    )


def test_no_source_hardcodes_a_divergent_obsidian_root() -> None:
    """受控材料根目录只能由 CONTROLLED_MATERIALS_ROOT 派生，不得各自硬编码。"""

    offenders: list[str] = []
    sources = sorted(BACKEND_ROOT.rglob("*.py"))
    sources += sorted((REPOSITORY_ROOT / ".agents").rglob("*.md"))
    guard = Path(__file__).resolve()
    for path in sources:
        if "__pycache__" in path.parts or path.resolve() == guard:
            # 本文件为说明隐患必须写出该写法本身，跳过自检。
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in DIVERGENT_ROOT_PATTERNS:
            for match in pattern.finditer(text):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(REPOSITORY_ROOT)}:{line}")

    assert offenders == [], (
        "以下位置硬编码了缺 \" Vault\" 的 Obsidian 路径，应改用 "
        f"CONTROLLED_MATERIALS_ROOT：{offenders}"
    )


def test_scripts_derive_their_defaults_from_the_canonical_root() -> None:
    """登记与迁移脚本的默认根目录必须来自同一常量，避免再次各自漂移。"""

    for script in (
        BACKEND_ROOT / "scripts" / "import_controlled_materials.py",
        BACKEND_ROOT / "scripts" / "migrate_knowledge_document_paths.py",
    ):
        text = script.read_text(encoding="utf-8")
        assert "CONTROLLED_MATERIALS_ROOT" in text, script.name


def _load_script(name: str):
    path = BACKEND_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_probe_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sibling_tree(root: Path) -> Path:
    """造出迁移时误建的那种旁支目录：结构合法，但没有 `.obsidian/`。"""

    sibling = root / "Obsidian" / "产品配置管理系统" / "受控材料"
    sibling.mkdir(parents=True)
    return sibling


def test_validation_accepts_a_tree_inside_an_obsidian_vault(tmp_path: Path) -> None:
    vault = tmp_path / "Obsidian Vault"
    (vault / ".obsidian").mkdir(parents=True)
    root = vault / "产品配置管理系统" / "受控材料"
    root.mkdir(parents=True)

    assert validate_controlled_materials_root(root) == root


def test_validation_rejects_a_tree_that_is_not_in_a_vault(tmp_path: Path) -> None:
    """旁支目录有完全合法的目录结构，只有 `.obsidian/` 能把它识别出来。"""

    with pytest.raises(ControlledMaterialsRootError) as error:
        validate_controlled_materials_root(_sibling_tree(tmp_path))

    assert "Vault" in str(error.value)


def test_validation_rejects_a_missing_root(tmp_path: Path) -> None:
    with pytest.raises(ControlledMaterialsRootError):
        validate_controlled_materials_root(tmp_path / "不存在")


def test_shipped_root_passes_validation_where_the_vault_exists() -> None:
    """随代码发布的默认根目录本身必须合法；本机没有库时不做断言。"""

    if not CONTROLLED_MATERIALS_ROOT.is_dir():
        pytest.skip("本机没有 Obsidian 库")
    assert (
        validate_controlled_materials_root(CONTROLLED_MATERIALS_ROOT)
        == CONTROLLED_MATERIALS_ROOT
    )


def test_import_script_stops_loudly_on_a_root_outside_the_vault(tmp_path: Path) -> None:
    """扫错树必须显式失败，而不是静默扫完再报成功。"""

    module = _load_script("import_controlled_materials")

    exit_code = module.main(
        [
            "--database",
            str(tmp_path / "product_config.db"),
            "--controlled-root",
            str(_sibling_tree(tmp_path)),
        ]
    )

    assert exit_code == 2
    assert not (tmp_path / "product_config.db").exists()


def test_migrate_script_stops_loudly_on_a_target_outside_the_vault(
    tmp_path: Path,
) -> None:
    module = _load_script("migrate_knowledge_document_paths")

    exit_code = module.main(
        [
            "--database",
            str(tmp_path / "product_config.db"),
            "--target-root",
            str(_sibling_tree(tmp_path)),
        ]
    )

    assert exit_code == 2
    assert not (tmp_path / "product_config.db").exists()
