"""海外注册状态口径：明确结论不是待办事项。

「不需要注册」「未注册成功」「暂停/停止注册」是表格作者已经给出的结论——
这类行只留记录、不进正式数据，但也不该在界面上被显示成"还有问题要修"。
「进行中」「新地址登记」是过程状态，仍然保留写法问题，因为将来可能转为正式数据。
"""

from __future__ import annotations

from app.services.data_review import _non_formal_note, _overseas_review_status
from app.services.overseas_registration_preview import (
    OverseasRegistrationRecord,
    _status,
    build_overseas_relations,
    evaluate_overseas_row_issues,
)


def _record(status: str, **overrides) -> OverseasRegistrationRecord:
    payload = dict(
        sheet_name="已完成注册",
        source_row=2,
        source_ref="已完成注册!A2:C2",
        jurisdiction_raw="孟加拉",
        jurisdiction_name="孟加拉",
        jurisdiction_code="BD",
        authority=None,
        registration_status=status,
        address_version="unspecified",
        model_raw="销售反馈不需要注册,可直接销售",
        probe_raw="",
        models=("销售反馈不需要注册",),
        probes=(),
        ready_for_import=False,
        issue_codes=(),
    )
    payload.update(overrides)
    return OverseasRegistrationRecord(**payload)


def _codes(status: str, **overrides) -> tuple[str, ...]:
    record = _record(status, **overrides)
    return evaluate_overseas_row_issues(
        jurisdiction_code=record.jurisdiction_code,
        status=record.registration_status,
        model_raw=record.model_raw,
        probe_raw=record.probe_raw,
        models=record.models,
        probes=record.probes,
        unresolved_rules=record.unresolved_rules,
    )


def test_no_registration_required_is_reported_as_a_conclusion():
    """「不需要注册」是结论，不该再顺带报一堆写法问题。"""

    assert _codes("not_required") == ("registration_not_required",)


def test_failed_and_suspended_get_their_own_codes():
    assert _codes("failed") == ("registration_failed",)
    assert _codes("suspended") == ("registration_suspended",)


def test_pending_statuses_keep_their_writing_issues():
    codes = _codes(
        "in_progress",
        model_raw="VINNO10",
        models=("VINNO10",),
        probe_raw="S2-9C",
        probes=("S2-9C",),
    )

    assert codes == ("non_final_status",)


def test_status_markers_are_recognised_from_the_sheet_wording():
    assert _status("completed", "销售反馈不需要注册,可直接销售") == "not_required"
    assert _status("completed", "韩国兽用-销售反馈不注册,不与代理商合作") == "not_required"
    assert _status("completed", "未注册成功") == "failed"
    assert _status("completed", "暂停注册") == "suspended"
    assert _status("completed", "泰国 V5 S2-9C") == "completed"


def test_needing_no_extra_registration_is_not_the_same_as_not_required():
    """坦桑尼亚原话是「已经注册了 V5 和 X1，后续机型都可以进口，不需要再额外注册」。"""

    text = "注册证上实际只注册了V5和X1,后续这些机器型号都可以进口,不需要再额外注册。"

    assert _status("in_progress", text) == "in_progress"


def test_exclusion_note_explains_the_actual_reason():
    for status, keyword in (
        ("not_required", "无需注册"),
        ("failed", "未成功"),
        ("suspended", "暂停"),
        ("in_progress", "进行中"),
        ("new_address_scope", "新地址"),
    ):
        note = _non_formal_note(status)
        assert keyword in note
        assert "自动排除" in note
        assert "不作为正式数据" in note


def test_conclusive_rows_stay_out_of_relations_and_out_of_the_review_queue():
    record = _record("not_required")
    assert _overseas_review_status(record) == "excluded"
    assert build_overseas_relations((record,)) == ()


def test_pending_rows_also_stay_out_of_relations():
    record = _record(
        "in_progress",
        model_raw="VINNO10",
        models=("VINNO10",),
        probe_raw="S2-9C",
        probes=("S2-9C",),
    )

    assert _overseas_review_status(record) == "excluded"
    assert build_overseas_relations((record,)) == ()
