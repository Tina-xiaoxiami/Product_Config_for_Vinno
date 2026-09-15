from __future__ import annotations

from pathlib import Path
import re

from app.services.controlled_material_import import CONTROLLED_MATERIALS_ROOT


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
