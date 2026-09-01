"""产品负责人已确认的衍生型号注册基础型号。"""

from __future__ import annotations


CONFIRMED_DERIVED_MODEL_BASES: dict[str, str] = {
    "VINNO 9_Private": "VINNO 9",
    "VINNO 9 综合版": "VINNO 9",
}


def confirmed_derived_model_bases() -> dict[str, str]:
    return dict(CONFIRMED_DERIVED_MODEL_BASES)

