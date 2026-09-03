"""VINNO工作流的模型建议路由器。

实际模型切换由调用此模块的执行器负责；本模块只返回推荐模型。

使用方式：
    from tools.ai_router import identify_role, get_execution_model

    role, model = identify_role("请帮我实现版本对比功能的代码")
    # → role: PROGRAMMER, model: gpt-5.6-terra
"""

import re
from typing import Tuple
from enum import Enum
import os


class TaskRole(Enum):
    """任务角色枚举"""
    DEFAULT = "default"       # 默认对话理解
    PM = "pm"                 # 产品经理
    ARCHITECT = "architect"   # 架构设计师
    PROGRAMMER = "programmer" # 程序员
    TESTER = "tester"         # 测试工程师
    BATCH = "batch"           # 批量确定性处理
    HIGH_RISK = "high_risk"   # 注册红线和高风险审核


# 任务关键词映射（正则表达式模式）
ROLE_PATTERNS = {
    TaskRole.HIGH_RISK: [
        r"(注册红线|注册冲突|红线冲突|正式发布|发布审核|正式库迁移|批量覆盖正式数据)",
    ],
    TaskRole.BATCH: [
        r"(批量盘点|文件盘点|哈希核对|sha-?256|确定性提取|表格规范化)",
    ],
    TaskRole.PM: [
        r"(需求|文档|功能描述|用户故事|prd|需求文档|specification|产品|功能说明)",
    ],
    TaskRole.ARCHITECT: [
        r"(架构|架构设计|api设计|数据库设计|技术方案|技术架构|系统设计|设计方案)",
    ],
    TaskRole.PROGRAMMER: [
        r"(代码|实现|bug|修复|功能开发|api接口|写代码|编码|开发|编程|函数|类|模块|脚本)",
    ],
    TaskRole.TESTER: [
        r"(测试|测试用例|测试脚本|代码审查|qa|测试方案|单元测试|集成测试|验收测试|测试报告)",
    ],
}

# 角色对应的推荐模型（可通过环境变量覆盖）
ROLE_MODEL_MAP = {
    TaskRole.DEFAULT: os.getenv("AI_MODEL_DEFAULT", "gpt-5.6-terra"),
    TaskRole.PM: os.getenv("AI_MODEL_PM", "gpt-5.6-terra"),
    TaskRole.ARCHITECT: os.getenv("AI_MODEL_ARCHITECT", "gpt-5.6-sol"),
    TaskRole.PROGRAMMER: os.getenv("AI_MODEL_PROGRAMMER", "gpt-5.6-terra"),
    TaskRole.TESTER: os.getenv("AI_MODEL_TESTER", "gpt-5.6-terra"),
    TaskRole.BATCH: os.getenv("AI_MODEL_BATCH", "gpt-5.6-luna"),
    TaskRole.HIGH_RISK: os.getenv("AI_MODEL_HIGH_RISK", "gpt-5.6-sol"),
}

# 角色描述（用于日志和展示）
ROLE_DESCRIPTIONS = {
    TaskRole.DEFAULT: "默认对话理解",
    TaskRole.PM: "产品经理 - 需求文档、功能描述",
    TaskRole.ARCHITECT: "架构设计师 - 技术方案、架构设计",
    TaskRole.PROGRAMMER: "程序员 - 代码实现、功能开发",
    TaskRole.TESTER: "测试工程师 - 测试用例、代码审查",
    TaskRole.BATCH: "批量处理 - 文件盘点、哈希和确定性提取",
    TaskRole.HIGH_RISK: "高风险审核 - 注册红线、迁移和正式发布",
}


def identify_role(user_input: str) -> Tuple[TaskRole, str]:
    """
    根据用户输入识别角色和推荐模型

    Args:
        user_input: 用户输入的请求内容

    Returns:
        (角色, 推荐模型)
    """
    if not user_input:
        return TaskRole.DEFAULT, ROLE_MODEL_MAP[TaskRole.DEFAULT]

    input_lower = user_input.lower()

    # 检查各角色的关键词模式
    for role, patterns in ROLE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, input_lower):
                return role, ROLE_MODEL_MAP[role]

    # 未识别到特定任务，使用默认模型
    return TaskRole.DEFAULT, ROLE_MODEL_MAP[TaskRole.DEFAULT]


def get_execution_model(user_input: str) -> str:
    """
    获取执行任务应使用的模型

    Returns:
        模型名称字符串
    """
    role, model = identify_role(user_input)
    return model


def get_role_info(user_input: str) -> dict:
    """
    获取详细的角色信息

    Returns:
        {
            "role": "programmer",
            "role_name": "程序员",
            "model": "deepseek-coder",
            "description": "程序员 - 代码实现、功能开发"
        }
    """
    role, model = identify_role(user_input)

    role_names = {
        TaskRole.DEFAULT: "默认",
        TaskRole.PM: "产品经理",
        TaskRole.ARCHITECT: "架构设计师",
        TaskRole.PROGRAMMER: "程序员",
        TaskRole.TESTER: "测试工程师",
        TaskRole.BATCH: "批量处理",
        TaskRole.HIGH_RISK: "高风险审核",
    }

    return {
        "role": role.value,
        "role_name": role_names[role],
        "model": model,
        "description": ROLE_DESCRIPTIONS[role],
    }


def print_role_mapping():
    """打印角色-模型映射表"""
    print("=" * 60)
    print("AI角色-模型映射配置")
    print("=" * 60)
    print()
    print(f"{'角色':<15} {'模型':<20} {'适用任务'}")
    print("-" * 60)

    for role in TaskRole:
        model = ROLE_MODEL_MAP[role]
        desc = ROLE_DESCRIPTIONS[role]
        role_name = {
            TaskRole.DEFAULT: "默认",
            TaskRole.PM: "产品经理",
            TaskRole.ARCHITECT: "架构设计师",
            TaskRole.PROGRAMMER: "程序员",
            TaskRole.TESTER: "测试工程师",
            TaskRole.BATCH: "批量处理",
            TaskRole.HIGH_RISK: "高风险审核",
        }[role]
        print(f"{role_name:<15} {model:<20} {desc}")

    print("=" * 60)


# 使用示例和测试
if __name__ == "__main__":
    print_role_mapping()
    print()

    print("任务识别测试：")
    print("-" * 60)

    test_cases = [
        "请帮我实现版本对比功能的代码",
        "设计用户管理模块的API架构",
        "写一个需求文档描述配置管理功能",
        "生成版本管理功能的测试用例",
        "修复登录页面的bug",
        "代码审查一下这个模块",
        "数据库设计需要优化",
        "今天进度怎么样",  # 默认对话
        "帮我写一个脚本",
    ]

    for example in test_cases:
        info = get_role_info(example)
        print(f"输入: {example}")
        print(f"  → 角色: {info['role_name']}")
        print(f"  → 模型: {info['model']}")
        print(f"  → 描述: {info['description']}")
        print()
