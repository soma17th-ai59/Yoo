"""Question node — interrupt/resume flow for items that need user clarification.

ask_question: surfaces the first unanswered ItemPlan to the user.
resume_with_answer: folds the user's answer back into the plan and clears the interrupt.
Zero LangGraph imports per module purity rules.
"""

from __future__ import annotations

from backend.app.graph.state import GraphState, ItemPlan, PendingQuestion


def ask_question(state: GraphState) -> dict:
    """Return the first needs_question plan that has no draft yet.

    Returns {"pending_question": PendingQuestion} if found,
    or {"pending_question": None} if no questions remain.
    """
    drafted_ids = {d.item_id for d in state.drafts}

    for plan in state.plans:
        if plan.needs_question and plan.item_id not in drafted_ids:
            question_text = plan.question or "추가 정보를 입력해 주세요."
            return {
                "pending_question": PendingQuestion(item_id=plan.item_id, question=question_text)
            }

    return {"pending_question": None}


def resume_with_answer(state: GraphState, answer: str) -> dict:
    """Fold user's answer into the pending plan and clear the interrupt.

    Updates the matching ItemPlan: sets needs_question=False and appends
    the answer string to source_evidence.
    Returns {"pending_question": None, "plans": updated_plans}.
    """
    if state.pending_question is None:
        return {"pending_question": None, "plans": list(state.plans)}

    target_id = state.pending_question.item_id
    updated_plans: list[ItemPlan] = []

    for plan in state.plans:
        if plan.item_id == target_id:
            updated_evidence = list(plan.source_evidence) + [answer]
            updated_plans.append(
                plan.model_copy(
                    update={
                        "needs_question": False,
                        "source_evidence": updated_evidence,
                        "question": None,
                    }
                )
            )
        else:
            updated_plans.append(plan)

    return {"pending_question": None, "plans": updated_plans}
