from pathlib import Path
import sqlite3

from openpyxl import Workbook

from app.services.overseas_registration_preview import (
    build_overseas_registration_preview,
    match_overseas_registration_master_data,
    write_overseas_registration_preview,
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
    assert preview.summary["source_rows"] == 6
    assert preview.summary["ready_rows"] == 1
    assert preview.summary["review_rows"] == 5

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
    assert preview.summary["source_rows"] == 6


def test_preview_does_not_expand_abbreviated_model_lists_silently(tmp_path):
    workbook_path = tmp_path / "tracking.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "已完成注册"
    sheet.append(["国家/地区", "机型", "探头"])
    sheet.append(["阿根廷", "Ultimus 7P,7E,8P", "S2-9C,F2-5C"])
    sheet.append(["埃及", "G65,75", "S2-9C,F2-5C"])
    workbook.save(workbook_path)

    preview = build_overseas_registration_preview(workbook_path)

    assert all(record.ready_for_import is False for record in preview.records)
    assert all(
        "model_name_requires_review" in record.issue_codes
        for record in preview.records
    )
    assert preview.summary["normalized_relations"] == 0


def test_preview_writes_reviewable_json_and_csv_without_database_changes(tmp_path):
    workbook_path = tmp_path / "tracking.xlsx"
    _write_tracking_workbook(workbook_path)
    preview = build_overseas_registration_preview(workbook_path)

    outputs = write_overseas_registration_preview(preview, tmp_path / "preview")

    assert outputs["json"].is_file()
    assert outputs["review_csv"].is_file()
    assert '"source_rows": 6' in outputs["json"].read_text(encoding="utf-8")
    review_text = outputs["review_csv"].read_text(encoding="utf-8-sig")
    assert "source_ref,jurisdiction_raw" in review_text
    assert "沙特-未注册成功" in review_text
    assert "泰国,V10" not in review_text


def test_master_data_match_separates_direct_alias_typo_and_registration_only(tmp_path):
    workbook_path = tmp_path / "tracking.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "已完成注册"
    sheet.append(["国家/地区", "机型", "探头"])
    sheet.append(["泰国", "VINNO 10", "S2-9C"])
    sheet.append(["巴西", "V10", "X4-0E"])
    sheet.append(["埃及", "A3", "A2-5C"])
    sheet.append(["阿根廷", "V10 series", "F2-5C"])
    workbook.save(workbook_path)

    database_path = tmp_path / "product_config.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE product_series (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE product_models (
            id INTEGER PRIMARY KEY,
            series_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            config_group TEXT
        );
        CREATE TABLE probe_models (
            id INTEGER PRIMARY KEY,
            model_number TEXT NOT NULL
        );
        INSERT INTO product_series VALUES (1, 'R&V10 series-Oversea');
        INSERT INTO product_models VALUES (10, 1, 'VINNO 10', NULL);
        INSERT INTO probe_models VALUES (20, 'S2-9C');
        INSERT INTO probe_models VALUES (21, 'X4-9E');
        INSERT INTO probe_models VALUES (22, 'F2-5C');
        """
    )
    connection.commit()
    before = connection.total_changes
    connection.close()

    preview = build_overseas_registration_preview(workbook_path)
    matches = match_overseas_registration_master_data(preview, database_path)

    by_model = {item.source_name: item for item in matches.models}
    assert by_model["VINNO 10"].match_status == "direct"
    assert by_model["V10"].match_status == "alias_candidate"
    assert by_model["V10"].candidate_names == ("VINNO 10",)
    assert by_model["A3"].match_status == "registration_only_candidate"
    assert by_model["V10 series"].match_status == "source_review_required"

    by_probe = {item.source_name: item for item in matches.probes}
    assert by_probe["S2-9C"].match_status == "direct"
    assert by_probe["X4-0E"].match_status == "typo_candidate"
    assert by_probe["X4-0E"].candidate_names == ("X4-9E",)
    assert by_probe["A2-5C"].match_status == "registration_only_candidate"

    connection = sqlite3.connect(database_path)
    assert connection.total_changes == before
    assert connection.execute("SELECT COUNT(*) FROM product_models").fetchone()[0] == 1
    connection.close()
