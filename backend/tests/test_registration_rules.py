from pathlib import Path

from openpyxl import Workbook
import pytest

from app.services.registration_rules import (
    evaluate_probe_availability,
    parse_domestic_registration_workbook,
)


def _write_registration_workbook(
    path: Path,
    *,
    unsupported_for_vinno_10e: str = "F2-5C",
) -> None:
    workbook = Workbook()
    matrix = workbook.active
    matrix.title = "0729"
    matrix["A1"] = "型号差异表-国内支持"
    matrix["A2"] = "支持探头\n共3把"
    matrix["B2"] = "F2-5C，G1-4P，F4-9E"
    matrix.append(["序号", "型号", "不支持探头", "通道数"])
    matrix.append([1, "VINNO 10", "探头全适用", 128])
    matrix.append([2, "VINNO 10E", unsupported_for_vinno_10e, 128])
    matrix.append([3, "VINNO 9", "F4-9E、G1-4P", 128])

    probes = workbook.create_sheet("Sheet1")
    probes.append([None, None, None])
    probes.append(["F2-5C", 1000530, 1000530])
    probes.append(["G1-4P", 1000744, 1000744])
    probes.append(["F4-9E", 1000784, 1000784])
    workbook.save(path)


def test_registration_workbook_parser_preserves_models_probes_and_exclusions(tmp_path):
    workbook_path = tmp_path / "registration.xlsx"
    _write_registration_workbook(workbook_path)

    parsed = parse_domestic_registration_workbook(workbook_path)

    assert [(probe.model, probe.ipn) for probe in parsed.probes] == [
        ("F2-5C", "1000530"),
        ("G1-4P", "1000744"),
        ("F4-9E", "1000784"),
    ]
    assert [model.model_name for model in parsed.models] == [
        "VINNO 10",
        "VINNO 10E",
        "VINNO 9",
    ]
    assert parsed.models[0].unsupported_probes == ()
    assert parsed.models[1].unsupported_probes == ("F2-5C",)
    assert parsed.models[2].unsupported_probes == ("F4-9E", "G1-4P")
    assert parsed.models[1].channel_count == 128


def test_registration_workbook_rejects_an_unknown_excluded_probe(tmp_path):
    workbook_path = tmp_path / "registration.xlsx"
    _write_registration_workbook(
        workbook_path,
        unsupported_for_vinno_10e="UNKNOWN-PROBE",
    )

    with pytest.raises(ValueError, match="UNKNOWN-PROBE"):
        parse_domestic_registration_workbook(workbook_path)


@pytest.mark.parametrize(
    (
        "registered",
        "selection_config",
        "current_config",
        "effective_status",
        "status_source",
        "is_formal",
    ),
    [
        (False, "X", "X", "#", "registration_redline", True),
        (True, "O", "X", "O", "selection_config", True),
        (True, "未定义", "Δ", "Δ", "current_config_aux", False),
        (True, "", "#", "未定义", "missing", False),
    ],
)
def test_registration_redline_precedes_formal_and_auxiliary_product_strategy(
    registered,
    selection_config,
    current_config,
    effective_status,
    status_source,
    is_formal,
):
    result = evaluate_probe_availability(
        registered=registered,
        selection_config=selection_config,
        current_config=current_config,
    )

    assert result.effective_status == effective_status
    assert result.status_source == status_source
    assert result.is_formal is is_formal
