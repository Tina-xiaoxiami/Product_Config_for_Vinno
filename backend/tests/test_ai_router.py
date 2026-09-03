from tools.ai_router import ROLE_MODEL_MAP, TaskRole, get_execution_model


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
