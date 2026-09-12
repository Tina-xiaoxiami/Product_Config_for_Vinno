"""
时间工具函数
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """返回不带时区信息的 UTC 当前时间（等价于旧 datetime.utcnow()，但非弃用）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)
