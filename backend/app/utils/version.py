"""
版本号工具函数
"""


def generate_next_version(last_version_number: str = None) -> str:
    """
    生成下一个版本号

    Args:
        last_version_number: 上一个版本号，如 "v1.0.0"

    Returns:
        新版本号，如 "v1.0.1"
    """
    if not last_version_number:
        return "v1.0.0"

    try:
        # 移除v前缀并按.分割
        version_str = last_version_number.lstrip('vV')

        # 处理预发布版本（如 1.0.0-beta）
        if '-' in version_str:
            version_str = version_str.split('-')[0]

        parts = version_str.split('.')

        # 解析各部分，默认为0
        major = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 1
        minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0

        return f"v{major}.{minor}.{patch + 1}"
    except (ValueError, IndexError):
        # 解析失败，返回默认版本号
        return "v1.0.0"