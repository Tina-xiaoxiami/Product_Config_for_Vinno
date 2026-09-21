"""在本机打开受控原件。

后端就跑在用户的机器上（本工具是本机服务），所以可以调用系统默认程序打开原件。
安全前提有两条，两者都必须成立：

1. 只接受来自本机的请求（非本机一律 403）；
2. 路径只能由服务端按登记记录解析，绝不接受前端传入的任意路径。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class LocalOpenError(ValueError):
    """原件无法在本机打开。"""


_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}


def is_local_host(host: str | None) -> bool:
    """判断请求是否来自本机。"""

    return str(host or "").strip() in _LOCAL_HOSTS


def open_local_path(path: str | Path, *, reveal: bool = False) -> None:
    """用系统默认程序打开原件；reveal 为真时改为在访达中定位。"""

    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(target)
    if sys.platform != "darwin":
        raise LocalOpenError("仅支持在 macOS 本机打开受控原件")
    command = ["open", "-R", str(target)] if reveal else ["open", str(target)]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LocalOpenError("本机打开受控原件失败") from exc
