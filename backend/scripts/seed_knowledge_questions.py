"""Preview or import a controlled batch of knowledge questions for review."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import async_session, init_db  # noqa: E402
from app.services.knowledge_question_seed import (  # noqa: E402
    SeedQuestionSpec,
    seed_pending_questions,
)


def load_manifest(path: Path) -> tuple[str, list[SeedQuestionSpec]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取问题批次：{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("问题批次必须是JSON对象")
    batch = str(payload.get("batch") or "").strip()
    raw_questions = payload.get("questions")
    if not batch:
        raise ValueError("问题批次缺少batch")
    if not isinstance(raw_questions, list):
        raise ValueError("问题批次缺少questions数组")
    specs: list[SeedQuestionSpec] = []
    for index, item in enumerate(raw_questions, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第{index}个问题必须是对象")
        specs.append(
            SeedQuestionSpec(
                category=str(item.get("category") or ""),
                question=str(item.get("question") or ""),
            )
        )
    return batch, specs


async def run(path: Path, *, apply: bool) -> dict:
    batch, specs = load_manifest(path)
    await init_db()
    started = time.perf_counter()
    async with async_session() as session:
        report = await seed_pending_questions(session, specs, apply=apply)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "batch": batch,
        "mode": "apply" if apply else "dry-run",
        "elapsed_ms": elapsed_ms,
        **report,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="问题批次JSON")
    parser.add_argument("--apply", action="store_true", help="写入待确认问题")
    args = parser.parse_args()
    try:
        report = asyncio.run(run(args.input, apply=args.apply))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
