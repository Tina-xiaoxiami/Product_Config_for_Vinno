"""I06 answer routing and source revalidation for the local workbench."""

from __future__ import annotations

from typing import Any

from tracker.database import Database
from tracker.services.joint_answer import joint_answer, structured_signature
from tracker.services.product_strategy import ProductStrategyReader


def revalidate_structured_answers(database: Database, reader: ProductStrategyReader) -> int:
    changed = 0
    signatures: dict[tuple[str, str], str] = {}
    for answer in database.list_qa_answers(status="published"):
        scope = (answer["country_code"], answer["model_name"])
        if scope not in signatures:
            signatures[scope] = structured_signature(database, reader, country=scope[0], model=scope[1])
        current = signatures[scope]
        if current != answer["structured_signature"]:
            changed += int(database.mark_qa_for_structured_review(answer["id"], answer["structured_signature"]))
    return changed


def find_answer(
    database: Database,
    question: str,
    *,
    market: str,
    country: str,
    model: str,
    reader: ProductStrategyReader | None = None,
    probe: str = "",
    item: str = "",
) -> dict[str, Any]:
    if not question.strip():
        raise ValueError("请填写问题。")
    market, country, model = market.strip().casefold(), country.strip().upper(), model.strip()
    missing = [key for key, value in (("market", market), ("country", country), ("model", model)) if not value.strip()]
    if missing:
        return {"state": "needs_clarification", "missing": missing}
    if probe.strip() or item.strip():
        if reader is None:
            raise ValueError("结构化来源未配置。")
        return {"state": "joint", "joint": joint_answer(database, reader, market=market, country=country, model=model, probe=probe, item=item)}
    if market == "domestic" and country != "CN":
        return {"state": "needs_clarification", "missing": ["market_country_match"]}
    if market != "domestic" or country != "CN":
        return {
            "state": "unanswered",
            "reason": "当前试点仅有中国国内版资料；该范围尚无可用正式答案。",
        }
    matches = database.search_published_qa(question, market, country, model)
    if reader is not None:
        current = structured_signature(database, reader, country=country, model=model)
        if matches and matches[0]["structured_signature"] != current:
            return {"state": "unanswered", "reason": "结构化注册或策略数据已变化，原答案等待重新审核。", "reason_code": "source_changed"}
    if len(matches) != 1:
        return {
            "state": "unanswered",
            "reason": "当前范围没有唯一且有效的正式答案，请提交待处理问题。",
        }
    return {"state": "answered", "answer": matches[0]}
