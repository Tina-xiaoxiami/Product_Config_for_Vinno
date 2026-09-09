from pathlib import Path

from openpyxl import Workbook

from app.services.overseas_registration_preview import (
    build_overseas_registration_preview,
)


def _write_tracking_workbook(path: Path) -> None:
    workbook = Workbook()

    completed = workbook.active
    completed.title = "已完成注册"
    completed.append(["国家/地区", "机型", "探头"])
    completed.append(["泰国", "V10,V10E", "S2-9C，F2-5C"])
    completed.append(["孟加拉", "销售反馈不需要注册，可直接销售", None])

    in_progress = workbook.create_sheet("进行中-暂未收到销售反馈")
    in_progress.append(["国家/地区", "机型", "探头"])
    in_progress.append(["沙特-未注册成功", "G65", "F2-5C,G2-5C"])
    in_progress.append(["乌兹别克斯坦(A3 X1暂停注册)", "V10", "S2-9C"])

    new_address = workbook.create_sheet("新地址注册")
    new_address.append(["国家/地区", "机型", "探头"])
    new_address.append(["墨西哥", "V10 series", "S2-9C,F2-5C"])
    new_address.append(["巴拿马", "P series", "/"])

    workbook.save(path)


def test_preview_keeps_registration_status_and_address_version_separate(tmp_path):
    workbook_path = tmp_path / "超声小国家（地区）注册跟踪表-20260819.xlsx"
    _write_tracking_workbook(workbook_path)

    preview = build_overseas_registration_preview(workbook_path)

    assert preview.snapshot_date == "2026-08-19"
    assert preview.summary["source_rows"] == 7
    assert preview.summary["ready_rows"] == 1
    assert preview.summary["review_rows"] == 6

    thailand = preview.records[0]
    assert thailand.jurisdiction_code == "TH"
    assert thailand.registration_status == "completed"
    assert thailand.address_version == "unspecified"
    assert thailand.models == ("V10", "V10E")
    assert thailand.probes == ("S2-9C", "F2-5C")

    saudi = next(record for record in preview.records if record.jurisdiction_code == "SA")
    assert saudi.registration_status == "failed"
    assert saudi.ready_for_import is False

    uzbekistan = next(
        record
        for record in preview.records
        if record.jurisdiction_code == "UZ"
    )
    assert uzbekistan.registration_status == "suspended"

    mexico = next(record for record in preview.records if record.jurisdiction_code == "MX")
    assert mexico.registration_status == "new_address_scope"
    assert mexico.address_version == "new"
    assert "model_scope_requires_expansion" in mexico.issue_codes

    panama = next(record for record in preview.records if record.jurisdiction_code == "PA")
    assert "probe_scope_not_explicit" in panama.issue_codes
    assert panama.ready_for_import is False


def test_preview_does_not_treat_not_required_as_completed(tmp_path):
    workbook_path = tmp_path / "tracking.xlsx"
    _write_tracking_workbook(workbook_path)

    preview = build_overseas_registration_preview(workbook_path)

    bangladesh = next(
        record
        for record in preview.records
        if record.jurisdiction_code == "BD"
    )
    assert bangladesh.registration_status == "not_required"
    assert bangladesh.ready_for_import is False
    assert "narrative_rule_requires_review" in bangladesh.issue_codes


def test_preview_supports_legacy_xls_through_temporary_conversion(
    tmp_path, monkeypatch
):
    legacy_path = tmp_path / "tracking-20260819.xls"
    legacy_path.write_bytes(b"legacy-xls-placeholder")
    converted_path = tmp_path / "converted.xlsx"
    _write_tracking_workbook(converted_path)

    monkeypatch.setattr(
        "app.services.overseas_registration_preview._convert_legacy_xls",
        lambda _path, _directory: converted_path,
    )

    preview = build_overseas_registration_preview(legacy_path)

    assert preview.source_file == str(legacy_path.resolve())
    assert preview.summary["source_rows"] == 7

