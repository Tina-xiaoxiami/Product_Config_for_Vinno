"""两种"来自文档/结论"的数据：整行结论，和按文档补录的探头清单。

- 澳洲那行的机型列写的是「只要有了证书，我们所有机型都可以卖」——结论性说明，
  只留记录，不产生机型-探头关系，也不该在待确认里排队；
- 沙特那行的探头列写的是「DOC——Rev10中对应机型适配探头」——数据不在原件里，
  按受控文档（MDR-DOC Rev.10）登记的清单补录，可追溯、可撤销。
"""

from __future__ import annotations

import sqlite3

from app.services.data_review import _non_formal_note, _overseas_review_status
from app.services.overseas_registration_preview import (
    OverseasRegistrationPreview,
    OverseasRegistrationRecord,
    build_overseas_relations,
    evaluate_overseas_row_issues,
)
from app.services.overseas_row_overrides import (
    delete_row_probe_override,
    list_row_probe_overrides,
    row_probe_overrides_by_source,
    save_row_probe_override,
)


def _codes(**overrides) -> tuple[str, ...]:
    payload = dict(
        jurisdiction_code="AU",
        status="completed",
        model_raw="销售反馈:在澳洲就是只要有了证书, 我们所有的机型(包括新机型)都可以卖",
        probe_raw="",
        models=("销售反馈:在澳洲就是只要有了证书", "我们所有的机型(包括新机型)都可以卖"),
        probes=(),
        unresolved_rules=("probe_blank", "model"),
    )
    payload.update(overrides)
    return evaluate_overseas_row_issues(**payload)


def test_a_policy_statement_row_is_a_conclusion_not_a_defect():
    assert _codes() == ("narrative_conclusion",)


def test_a_prose_row_with_real_models_still_needs_review():
    """机型列里有真机型时不能当成结论行——那多半是写法问题。"""

    codes = _codes(
        model_raw="V5,V6 销售反馈:已拿证",
        models=("V5", "V6"),
        unresolved_rules=(),
    )

    assert "narrative_conclusion" not in codes
    assert "narrative_rule_requires_review" in codes


def test_conclusion_rows_are_recorded_but_excluded():
    record = OverseasRegistrationRecord(
        sheet_name="已完成注册",
        source_row=18,
        source_ref="已完成注册!A18:C18",
        jurisdiction_raw="澳洲",
        jurisdiction_name="澳洲",
        jurisdiction_code="AU",
        authority=None,
        registration_status="completed",
        address_version="unspecified",
        model_raw="销售反馈:在澳洲就是只要有了证书, 我们所有的机型(包括新机型)都可以卖",
        probe_raw="",
        models=("销售反馈:在澳洲就是只要有了证书",),
        probes=(),
        ready_for_import=False,
        issue_codes=("narrative_conclusion",),
    )

    assert _overseas_review_status(record) == "excluded"
    assert build_overseas_relations((record,)) == ()
    assert "结论" in _non_formal_note("completed", ("narrative_conclusion",))


def _preview(sha: str) -> OverseasRegistrationPreview:
    return OverseasRegistrationPreview(
        source_file="/tmp/tracking.xls",
        source_sha256=sha,
        snapshot_date="2026-08-19",
        records=(
            OverseasRegistrationRecord(
                sheet_name="已完成注册",
                source_row=177,
                source_ref="已完成注册!A177:C177",
                jurisdiction_raw="沙特",
                jurisdiction_name="沙特",
                jurisdiction_code="SA",
                authority=None,
                registration_status="completed",
                address_version="unspecified",
                model_raw="G80,M80,A5",
                probe_raw="DOC——Rev10中对应机型适配探头",
                models=("G80", "M80", "A5"),
                probes=("DOC——Rev10中对应机型适配探头",),
                ready_for_import=False,
                issue_codes=("probe_name_requires_review",),
                model_probes=(("G80", ()), ("M80", ()), ("A5", ())),
            ),
        ),
        relations=(),
        summary={"source_rows": 1, "ready_rows": 0, "review_rows": 1},
    )


def test_row_probe_override_round_trips_and_is_keyed_by_document(tmp_path):
    database_path = tmp_path / "product_config.db"
    sqlite3.connect(database_path).close()

    save_row_probe_override(
        database_path,
        document_sha256="a" * 64,
        source_ref="已完成注册!A177:C177",
        model_name="G80",
        probes=("G2-5C", "X2-6C"),
        source_note="MDR-DOC Rev.10 第4页",
        confirmed_by="口径确认",
    )
    save_row_probe_override(
        database_path,
        document_sha256="b" * 64,
        source_ref="已完成注册!A177:C177",
        model_name="M80",
        probes=("G2-5C",),
        source_note="MDR-DOC Rev.10 第4页",
        confirmed_by="口径确认",
    )

    index = row_probe_overrides_by_source(database_path, "a" * 64)
    assert index == {"已完成注册!A177:C177": {"G80": ("G2-5C", "X2-6C")}}
    # 换一份原件（sha 不同）不会套用别人登记的清单
    assert row_probe_overrides_by_source(database_path, "c" * 64) == {}

    assert list_row_probe_overrides(database_path, document_sha256="a" * 64)
    assert delete_row_probe_override(
        database_path,
        document_sha256="a" * 64,
        source_ref="已完成注册!A177:C177",
        model_name="G80",
    )
    assert row_probe_overrides_by_source(database_path, "a" * 64) == {}


def test_locating_the_source_document_of_a_controlled_file(tmp_path):
    from app.services.overseas_row_overrides import document_sha256

    target = tmp_path / "MDR-DOC  Rev.10.pdf"
    target.write_bytes(b"controlled document")

    assert len(document_sha256(target)) == 64


def test_preview_applies_row_overrides_and_traces_the_source(tmp_path):
    from app.services.overseas_registration_preview import apply_row_probe_overrides

    records = apply_row_probe_overrides(
        _preview("a" * 64).records,
        {"已完成注册!A177:C177": {"G80": ("G2-5C", "X2-6C")}},
        source_note="MDR-DOC Rev.10 第4页",
    )
    row = records[0]

    assert dict(row.model_probes)["G80"] == ("G2-5C", "X2-6C")
    assert any(rule.startswith("override:") for rule in row.applied_rules)
    assert "probe" not in row.unresolved_rules
