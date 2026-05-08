"""Planner node — analyze form items and materials to build a writing plan.

Calls Solar with build_planner_messages; returns list[ItemPlan].
PII items always get a fixed placeholder plan (no Solar needed).
Zero LangGraph imports per module purity rules.
"""

from __future__ import annotations

from backend.app.graph.state import GraphState, ItemPlan
from backend.app.llm import solar as _solar_mod
from backend.app.llm.prompts import build_planner_messages

_PII_PLACEHOLDER_EVIDENCE = "pii_placeholder"


def _solar_complete(messages: list[dict]) -> object:
    """Thin wrapper so tests can patch a single symbol."""
    return _solar_mod.complete(messages, json_mode=True)


def plan_items(state: GraphState) -> dict:
    """Build an ItemPlan for every item in state.form_doc.

    PII items receive a fixed plan. Non-PII items are planned by Solar.
    Returns {"plans": list[ItemPlan]}.
    """
    if state.form_doc is None:
        return {"plans": [], "errors": ["form_doc이 없습니다."]}

    items = state.form_doc.items
    pii_ids = {item.item_id for item in items if item.is_pii}

    plans: list[ItemPlan] = []

    # PII items — fixed plan, no Solar call
    pii_plans: dict[str, ItemPlan] = {
        item.item_id: ItemPlan(
            item_id=item.item_id,
            source_evidence=[_PII_PLACEHOLDER_EVIDENCE],
            confidence=1.0,
            needs_question=False,
            question=None,
        )
        for item in items
        if item.is_pii
    }

    # Non-PII, fillable items — ask Solar
    non_pii_items = [item for item in items if not item.is_pii and item.fillable]
    solar_plans: dict[str, ItemPlan] = {}

    if non_pii_items:
        messages = build_planner_messages(state.form_doc, state.materials.docs)
        try:
            response = _solar_complete(messages)
            if not isinstance(response, list):
                # Solar wraps the array under different keys depending on the call:
                # plans / items / itemPlans / item_plans / data ... — accept any
                # known wrapper, and fall back to the first list-valued field.
                if isinstance(response, dict):
                    for key in (
                        "plans",
                        "items",
                        "itemPlans",
                        "ItemPlan",
                        "ItemPlans",
                        "item_plans",
                        "data",
                    ):
                        if isinstance(response.get(key), list):
                            response = response[key]
                            break
                    else:
                        response = next(
                            (v for v in response.values() if isinstance(v, list)),
                            [],
                        )
                else:
                    response = []

            for raw in response:
                if not isinstance(raw, dict):
                    continue
                item_id = raw.get("item_id")
                if item_id is None or item_id in pii_ids:
                    continue
                try:
                    plan = ItemPlan(
                        item_id=item_id,
                        source_evidence=raw.get("source_evidence", []),
                        confidence=float(raw.get("confidence", 0.5)),
                        needs_question=bool(raw.get("needs_question", False)),
                        question=raw.get("question"),
                    )
                    solar_plans[item_id] = plan
                except (ValueError, TypeError):
                    continue

        except Exception as exc:
            return {"plans": [], "errors": [f"Planner Solar 오류: {exc}"]}

    # Merge: PII plans + Solar plans + defaults for any missing fillable non-PII items
    for item in items:
        if not item.fillable:
            continue
        if item.is_pii:
            plans.append(pii_plans[item.item_id])
        elif item.item_id in solar_plans:
            plans.append(solar_plans[item.item_id])
        else:
            # Default plan for items Solar did not return
            plans.append(
                ItemPlan(
                    item_id=item.item_id,
                    source_evidence=[],
                    confidence=0.0,
                    needs_question=True,
                    question="해당 항목 작성을 위한 추가 정보가 필요합니다. 관련 내용을 알려주세요.",
                )
            )

    return {"plans": plans}
