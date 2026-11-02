from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def test_vendored_release_workbench_compiles_on_python_311() -> None:
    interpreter = (
        sys.executable
        if sys.version_info[:2] == (3, 11)
        else shutil.which("python3.11")
    )
    if interpreter is None:
        pytest.skip("Python 3.11 interpreter is unavailable")

    tracker = Path(__file__).resolve().parents[1] / "tracker"
    result = subprocess.run(
        [interpreter, "-m", "compileall", "-q", str(tracker)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
