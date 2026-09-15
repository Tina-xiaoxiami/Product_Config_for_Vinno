"""海外跟踪表的四种写法口径：注解清洗、系列展开、机型:探头、探头列「/」。

这些不是"格式洁癖"：只有零问题码的行才生成关系，所以口径不到位，
对应国家的这部分数据在海外注册查询里完全查不到（秘鲁只有 4 行进了查询）。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.services.overseas_registration_preview import (
    resolve_overseas_row_cells,
)
from app.services.overseas_series_mappings import (
    delete_overseas_series_mapping,
    list_overseas_series_mappings,
    save_overseas_series_mapping,
)

_R_SERIES = {"r series": ("R300", "R500", "R600", "R700")}


def _models_pairs(resolved):
    return dict(resolved.model_probes)


def test_annotation_is_cleaned_but_the_raw_cell_stays_as_evidence():
    resolved = resolve_overseas_row_cells("S300-新地址", "X2-6C、F2-5C")

    assert resolved.models == ("S300",)
    assert resolved.model_text == "S300"
    assert resolved.applied_rules == ("annotation:新地址",)
    assert resolved.unresolved_rules == ()


def test_annotation_cleaning_handles_oem_and_wireless_markers():
    assert resolve_overseas_row_cells("Sg12--- S300:OEM", "F2-5C").unresolved_rules == (
        "model",
    )
    assert resolve_overseas_row_cells("SG88-R500:OEM", "G1-4P").model_text == "SG88-R500"
    resolved = resolve_overseas_row_cells(
        "P系列+无线认证", "/", series_mappings={"p系列": ("P3", "P5")}
    )
    assert resolved.models == ("P3", "P5")
    assert "annotation:无线认证" in resolved.applied_rules


def test_series_is_expanded_once_through_the_mapping():
    resolved = resolve_overseas_row_cells(
        "R series", "G1-4P、G2-5C", series_mappings=_R_SERIES
    )

    assert resolved.models == ("R300", "R500", "R600", "R700")
    assert resolved.probes == ("G1-4P", "G2-5C")
    assert resolved.unresolved_rules == ()
    assert "series:R series" in resolved.applied_rules
    assert _models_pairs(resolved)["R600"] == ("G1-4P", "G2-5C")


def test_unmapped_series_still_needs_a_human():
    resolved = resolve_overseas_row_cells("R series", "G1-4P")

    # 没展开的原写法原样留着，界面要让人看见「R series 还没展开」
    assert resolved.models == ("R series",)
    assert resolved.unresolved_rules == ("series",)


def test_colon_notation_keeps_each_models_own_probe_list():
    resolved = resolve_overseas_row_cells(
        "E30, G86, X1, X2",
        "E30:G2-5C, F2-5C G86:G2-5C, S1-8C X1/X2:F2-5C, F2-5CE",
    )

    assert resolved.unresolved_rules == ()
    assert "notation:model_probe" in resolved.applied_rules
    assert _models_pairs(resolved) == {
        "E30": ("G2-5C", "F2-5C"),
        "G86": ("G2-5C", "S1-8C"),
        "X1": ("F2-5C", "F2-5CE"),
        "X2": ("F2-5C", "F2-5CE"),
    }


def test_colon_notation_supports_comma_separated_and_missing_slash_markers():
    resolved = resolve_overseas_row_cells(
        "E35, G55, G65, M86, G86",
        "E35/G55:G1-4P, G2-5C S1-6PX G65, M86, G86:F2-5C, S1-8C",
    )

    assert resolved.unresolved_rules == ()
    pairs = _models_pairs(resolved)
    # 「S1-6PX」紧跟在下一个标记前，属于前一组（A57 原文就是这样）
    assert pairs["E35"] == ("G1-4P", "G2-5C", "S1-6PX")
    assert pairs["G55"] == ("G1-4P", "G2-5C", "S1-6PX")
    assert pairs["G65"] == ("F2-5C", "S1-8C")
    assert pairs["M86"] == ("F2-5C", "S1-8C")
    assert pairs["G86"] == ("F2-5C", "S1-8C")


def test_slash_inside_the_notation_means_that_model_has_no_probes():
    """哥伦比亚 A56 原文末尾就是「P:/」——同一写法内部印证「/」= 没有探头。"""

    resolved = resolve_overseas_row_cells(
        "P series, R series, 9E, V10",
        "9E:S1-8C V10:S2-9C R:G1-4P P:/",
        series_mappings={"p series": ("P3", "P5"), "r series": ("R300", "R500")},
    )

    assert resolved.unresolved_rules == ()
    pairs = _models_pairs(resolved)
    assert pairs["9E"] == ("S1-8C",)
    assert pairs["V10"] == ("S2-9C",)
    # 「R:」「P:」指的是本行的系列写法
    assert pairs["R300"] == ("G1-4P",)
    assert pairs["R500"] == ("G1-4P",)
    assert pairs["P3"] == ()
    assert pairs["P5"] == ()


def test_colon_notation_adds_models_named_only_in_the_probe_cell():
    """菲律宾 A53：机型列只有 X2，探头列写 A5/A6:…（用户裁定：自动处理）。

    第一个标记之前的探头清单归"没有被标记点名的机型"（这里就是 X2）；
    标记点到的机型即使不在机型列里也补进来。
    """

    resolved = resolve_overseas_row_cells(
        "X2", "F2-5C, G2-5C E3-8T A5/A6:A2-5C, A4-9E"
    )

    assert resolved.unresolved_rules == ()
    assert resolved.models == ("X2", "A5", "A6")
    pairs = _models_pairs(resolved)
    assert pairs["X2"] == ("F2-5C", "G2-5C", "E3-8T")
    assert pairs["A5"] == ("A2-5C", "A4-9E")
    assert pairs["A6"] == ("A2-5C", "A4-9E")


def test_colon_notation_matches_a_marker_by_family_when_the_row_has_that_family():
    """越南 A172：「E20:」对机型列里的 E10、E35（用户裁定：E20 同 E10、E35），
    「R:」对 R300、R700；没有被点名的机型本行不给探头（同国别的行已覆盖）。"""

    resolved = resolve_overseas_row_cells(
        "VINNO X1, E10, E35, G65, R300, R700, S100, S200, S300",
        "R:G1-4P、G2-5C E20:F2-5C、D3-6C G65:S1-8C、S2-9C",
    )

    assert resolved.unresolved_rules == ()
    pairs = _models_pairs(resolved)
    assert pairs["R300"] == ("G1-4P", "G2-5C")
    assert pairs["R700"] == ("G1-4P", "G2-5C")
    assert pairs["E10"] == ("F2-5C", "D3-6C")
    assert pairs["E35"] == ("F2-5C", "D3-6C")
    assert pairs["G65"] == ("S1-8C", "S2-9C")
    for uncovered in ("VINNO X1", "S100", "S200", "S300"):
        assert pairs[uncovered] == ()
    assert any(rule.startswith("notation:partial") for rule in resolved.applied_rules)


def test_slash_means_no_probe_relation_but_an_empty_cell_does_not():
    slash = resolve_overseas_row_cells("Q5-7L, Q5-3C, Q5-2P", "/")

    assert slash.models == ("Q5-7L", "Q5-3C", "Q5-2P")
    assert slash.probes == ()
    assert slash.unresolved_rules == ()
    assert slash.applied_rules == ("probe:none",)
    assert _models_pairs(slash) == {"Q5-7L": (), "Q5-3C": (), "Q5-2P": ()}

    blank = resolve_overseas_row_cells("V8", "")
    assert blank.unresolved_rules == ("probe_blank",)


def test_a_bare_number_inherits_the_prefix_of_the_previous_model():
    """用户裁定：缩写续写一律展开，含埃及的 75 → G75。"""

    cases = {
        "Ultimus 7P,7E,8P,8E,9P,9E": (
            "Ultimus 7P",
            "Ultimus 7E",
            "Ultimus 8P",
            "Ultimus 8E",
            "Ultimus 9P",
            "Ultimus 9E",
        ),
        "ULTIMUS 9E,9": ("ULTIMUS 9E", "ULTIMUS 9"),
        "G65, 75, M86, G86": ("G65", "G75", "M86", "G86"),
        "R300,500,700": ("R300", "R500", "R700"),
    }
    for raw, expected in cases.items():
        resolved = resolve_overseas_row_cells(raw, "S1-8C")
        assert resolved.models == expected, raw
        assert resolved.unresolved_rules == (), raw
        assert any(rule.startswith("prefix:") for rule in resolved.applied_rules), raw


def test_probe_aliases_and_typo_separators_are_split_not_dropped():
    """用户裁定：斜杠两边都登记；`.` 和 `and` 按分隔符处理。"""

    resolved = resolve_overseas_row_cells(
        "V5, V6",
        "X6-16LG/X6-16L, D2-7C.S1-6PS, S1-8C and S2-9C",
    )

    assert resolved.probes == (
        "X6-16LG",
        "X6-16L",
        "D2-7C",
        "S1-6PS",
        "S1-8C",
        "S2-9C",
    )
    assert resolved.unresolved_rules == ()


def test_series_mapping_round_trips_through_the_database(tmp_path):
    database_path = tmp_path / "product_config.db"
    sqlite3.connect(database_path).close()
    from app.services.overseas_registration_history import (
        migrate_overseas_registration_history_schema,
    )

    migrate_overseas_registration_history_schema(database_path)
    save_overseas_series_mapping(
        database_path,
        source_name="R series",
        target_models=("R300", "R500", "R600", "R700"),
        confirmed_by="口径确认",
        change_note="表内 R700, R600, R500, R300 自证",
    )
    save_overseas_series_mapping(
        database_path,
        source_name="r  SERIES",
        target_models=("R300", "R500"),
        confirmed_by="口径确认",
    )

    mappings = list_overseas_series_mappings(database_path)
    assert len(mappings) == 1
    assert mappings[0].source_name == "r  SERIES"
    assert mappings[0].target_models == ("R300", "R500")
    assert dict(
        (item.source_name.casefold(), item.target_models) for item in mappings
    ) == {"r  series": ("R300", "R500")}

    assert delete_overseas_series_mapping(database_path, source_name="R SERIES")
    assert list_overseas_series_mappings(database_path) == ()


def test_series_mapping_rejects_an_empty_model_list(tmp_path):
    database_path = tmp_path / "product_config.db"
    sqlite3.connect(database_path).close()
    from app.services.overseas_registration_history import (
        migrate_overseas_registration_history_schema,
    )

    migrate_overseas_registration_history_schema(database_path)

    with pytest.raises(ValueError):
        save_overseas_series_mapping(
            database_path,
            source_name="R series",
            target_models=(),
            confirmed_by="口径确认",
        )
