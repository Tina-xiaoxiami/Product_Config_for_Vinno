#!/usr/bin/env python3
"""
把受控材料登记路径从旧目录迁到当前 Obsidian 库（默认干跑，不改任何数据）

只改数据库里的登记路径，不复制、不移动、不删除任何文件。
安全前提：目标文件必须已存在且 sha256 与登记值一致，否则该条一律跳过。

用法：
    python3 migrate_controlled_material_paths.py            # 干跑，只打印
    python3 migrate_controlled_material_paths.py --apply    # 真正写库（建议先备份 product_config.db）
"""
import argparse
import sys

sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

from app.services.knowledge_document_path_migration import (
    migrate_knowledge_document_paths,
    migrate_registration_artifact_paths,
)

DATABASE = "/Users/xiami/Documents/项目/产品配置管理系统/backend/product_config.db"
SOURCE_ROOT = "/Users/xiami/Documents/Obsidian/产品配置管理系统/受控材料"
TARGET_ROOT = "/Users/xiami/Documents/Obsidian Vault/产品配置管理系统/受控材料"

STATUS_NOTES = {
    "hash_mismatch": "新库文件内容与登记 sha256 不符",
    "target_missing": "新库缺少对应文件",
    "outside_source_root": "登记路径不在旧受控目录下",
    "missing_sha256": "登记记录缺少 sha256，无法校验",
    "unsupported_type": "该资料类型没有目标目录映射",
}


def _report(title: str, result) -> None:
    print(f"\n=== {title} ===")
    print(f"  模式: {'执行 (apply)' if result.apply else '干跑 (dry-run)'}")
    for key in sorted(result.counts):
        print(f"  {key:<20} {result.counts[key]}")

    skipped = [
        item for item in result.items
        if item.status not in {"ready", "updated", "already_migrated"}
    ]
    if skipped:
        print("  未处理条目：")
        for item in skipped:
            kind = getattr(item, "artifact_type", None) or getattr(item, "document_type", "")
            print(f"    [{item.status}] {kind} {item.file_name}"
                  f" —— {STATUS_NOTES.get(item.status, '')}")
            print(f"        {item.source_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="真正写库（默认只干跑）")
    parser.add_argument("--database", default=DATABASE)
    parser.add_argument("--source-root", default=SOURCE_ROOT)
    parser.add_argument("--target-root", default=TARGET_ROOT)
    args = parser.parse_args()

    for title, migrate in (
        ("知识库文档 (knowledge_documents)", migrate_knowledge_document_paths),
        ("注册包原件 (registration_package_versions)", migrate_registration_artifact_paths),
    ):
        result = migrate(
            args.database,
            source_root=args.source_root,
            target_root=args.target_root,
            apply=args.apply,
        )
        _report(title, result)

    print("\n提示：本脚本只改数据库登记路径，不复制 / 移动 / 删除任何文件。")


if __name__ == "__main__":
    main()
