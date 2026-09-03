"""Lightweight structural and business-rule checks for the VINNO skill pack."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REQUIRED_RULES = {
    "vinno-registration-ingest": (
        "注册证和差异表",
        "正式版本",
        "是否启用",
        "SKILL_FEEDBACK",
    ),
    "vinno-product-material-ingest": (
        "原文件",
        "Release Note",
        "注册红线",
        "SKILL_FEEDBACK",
    ),
    "vinno-feature-identity-curation": (
        "IPN 是功能身份",
        "【启用】",
        "version_variant",
        "SKILL_FEEDBACK",
    ),
    "vinno-qa-curation": (
        "待确认",
        "未启用",
        "来源",
        "SKILL_FEEDBACK",
    ),
    "vinno-knowledge-audit": (
        "只读",
        "国内产品覆盖",
        "regression_case",
        "SKILL_FEEDBACK",
    ),
    "vinno-model-routing": (
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
        "Sol审核通过不等于获得发布授权",
        "SKILL_FEEDBACK",
    ),
}


def main() -> None:
    failures: list[str] = []
    for skill_name, required_phrases in REQUIRED_RULES.items():
        skill_dir = ROOT / skill_name
        skill_file = skill_dir / "SKILL.md"
        eval_file = skill_dir / "evals" / "evals.json"
        if not skill_file.is_file():
            failures.append(f"{skill_name}: missing SKILL.md")
            continue
        content = skill_file.read_text(encoding="utf-8")
        for phrase in required_phrases:
            if phrase not in content:
                failures.append(f"{skill_name}: missing rule phrase {phrase!r}")
        try:
            payload = json.loads(eval_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            failures.append(f"{skill_name}: invalid eval file ({exc})")
            continue
        if payload.get("skill_name") != skill_name:
            failures.append(f"{skill_name}: eval skill_name mismatch")
        if len(payload.get("evals", [])) < 2:
            failures.append(f"{skill_name}: requires at least two regression prompts")

    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Validated {len(REQUIRED_RULES)} VINNO skills and their regression prompts.")


if __name__ == "__main__":
    main()
