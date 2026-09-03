from pathlib import Path
import runpy

from tools.ai_router import (
    ROLE_MODEL_MAP,
    TaskRole,
    get_execution_model,
    get_role_info,
    identify_role,
)


def test_default_routes_use_only_the_gpt_56_model_family():
    assert set(ROLE_MODEL_MAP.values()) <= {
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
    }


def test_router_selects_model_by_volume_and_business_risk():
    assert get_execution_model("批量盘点文件并核对SHA-256") == "gpt-5.6-luna"
    assert get_execution_model("实现一个普通的查询筛选条件") == "gpt-5.6-terra"
    assert get_execution_model("裁决注册红线冲突并审核正式发布") == "gpt-5.6-sol"


def test_explicit_roles_keep_balanced_defaults():
    assert ROLE_MODEL_MAP[TaskRole.PM] == "gpt-5.6-terra"
    assert ROLE_MODEL_MAP[TaskRole.PROGRAMMER] == "gpt-5.6-terra"
    assert ROLE_MODEL_MAP[TaskRole.ARCHITECT] == "gpt-5.6-sol"


def test_default_and_role_information_are_consistent():
    role, model = identify_role("")
    assert role is TaskRole.DEFAULT
    assert model == "gpt-5.6-terra"
    assert get_role_info("生成知识库验收测试")["role"] == "tester"


def test_command_line_report_lists_the_three_default_models(capsys):
    module_path = Path(__file__).parents[1] / "tools" / "ai_router.py"
    runpy.run_path(str(module_path), run_name="__main__")
    output = capsys.readouterr().out
    assert "gpt-5.6-luna" in output
    assert "gpt-5.6-terra" in output
    assert "gpt-5.6-sol" in output
