"""Unit tests for Question node.

ask_question(state: GraphState) -> dict
  Returns {"pending_question": PendingQuestion} for first unanswered needs_question plan.

resume_with_answer(state: GraphState, answer: str) -> dict
  Clears pending_question, adds answer to source_evidence, sets needs_question=False.
"""

from __future__ import annotations

import pytest

from backend.app.graph.state import GraphState, ItemPlan, DraftItem, PendingQuestion, MaterialBundle
from backend.app.hwpx.models import FormDoc, Item, Placeholder, Table


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(item_id: str, label: str = "항목") -> Item:
    return Item(
        item_id=item_id,
        label=label,
        section="Contents/section1.xml",
        kind="paragraph",
        xml_xpath=f"/p[{item_id}]",
    )


def _make_form(*items: Item) -> FormDoc:
    return FormDoc(sections=["Contents/section1.xml"], items=list(items), tables=[], placeholders=[])


def _make_plan(item_id: str, needs_question: bool = False, question: str | None = None) -> ItemPlan:
    return ItemPlan(
        item_id=item_id,
        source_evidence=["cv.pdf"],
        confidence=0.8,
        needs_question=needs_question,
        question=question,
    )


def _make_draft(item_id: str) -> DraftItem:
    return DraftItem(item_id=item_id, text="drafted", citations=[], approved=True)


def _make_state(
    plans: list[ItemPlan] | None = None,
    drafts: list[DraftItem] | None = None,
    pending_question: PendingQuestion | None = None,
) -> GraphState:
    return GraphState(
        plans=plans or [],
        drafts=drafts or [],
        pending_question=pending_question,
    )


# ---------------------------------------------------------------------------
# 1. ask_question sets pending_question from first needs_question=True plan
# ---------------------------------------------------------------------------


class TestAskQuestion:
    def test_sets_pending_question_for_first_needs_question_plan(self):
        plans = [
            _make_plan("item1", needs_question=True, question="연구 목표를 알려주세요."),
            _make_plan("item2", needs_question=False),
        ]
        state = _make_state(plans=plans)

        from backend.app.graph.nodes.question import ask_question
        result = ask_question(state)

        assert result["pending_question"] is not None
        assert result["pending_question"].item_id == "item1"
        assert result["pending_question"].question == "연구 목표를 알려주세요."

    def test_pending_question_is_pендingquestion_instance(self):
        plans = [_make_plan("q1", needs_question=True, question="질문?")]
        state = _make_state(plans=plans)

        from backend.app.graph.nodes.question import ask_question
        result = ask_question(state)

        assert isinstance(result["pending_question"], PendingQuestion)

    def test_uses_fallback_question_when_plan_question_is_none(self):
        plans = [_make_plan("q1", needs_question=True, question=None)]
        state = _make_state(plans=plans)

        from backend.app.graph.nodes.question import ask_question
        result = ask_question(state)

        assert result["pending_question"] is not None
        assert result["pending_question"].question  # non-empty fallback


# ---------------------------------------------------------------------------
# 2. ask_question returns None if no pending questions
# ---------------------------------------------------------------------------


class TestAskQuestionNoPending:
    def test_returns_none_when_no_needs_question_plans(self):
        plans = [_make_plan("item1", needs_question=False)]
        state = _make_state(plans=plans)

        from backend.app.graph.nodes.question import ask_question
        result = ask_question(state)

        assert result["pending_question"] is None

    def test_returns_none_for_empty_plans(self):
        state = _make_state(plans=[])

        from backend.app.graph.nodes.question import ask_question
        result = ask_question(state)

        assert result["pending_question"] is None

    def test_skips_already_drafted_needs_question_items(self):
        """If a needs_question item already has a draft, skip it."""
        plans = [_make_plan("q1", needs_question=True, question="질문?")]
        drafts = [_make_draft("q1")]
        state = _make_state(plans=plans, drafts=drafts)

        from backend.app.graph.nodes.question import ask_question
        result = ask_question(state)

        assert result["pending_question"] is None


# ---------------------------------------------------------------------------
# 3. resume_with_answer clears pending_question
# ---------------------------------------------------------------------------


class TestResumeWithAnswer:
    def test_clears_pending_question(self):
        plans = [_make_plan("q1", needs_question=True, question="질문?")]
        pq = PendingQuestion(item_id="q1", question="질문?")
        state = _make_state(plans=plans, pending_question=pq)

        from backend.app.graph.nodes.question import resume_with_answer
        result = resume_with_answer(state, "답변입니다.")

        assert result["pending_question"] is None


# ---------------------------------------------------------------------------
# 4. resume_with_answer adds answer to the plan's source_evidence
# ---------------------------------------------------------------------------


class TestResumeAddsEvidence:
    def test_answer_added_to_source_evidence(self):
        plans = [_make_plan("q1", needs_question=True, question="질문?")]
        pq = PendingQuestion(item_id="q1", question="질문?")
        state = _make_state(plans=plans, pending_question=pq)

        from backend.app.graph.nodes.question import resume_with_answer
        result = resume_with_answer(state, "사용자의 답변")

        updated_plan = next(p for p in result["plans"] if p.item_id == "q1")
        assert "사용자의 답변" in updated_plan.source_evidence

    def test_existing_evidence_preserved(self):
        plan = ItemPlan(
            item_id="q1",
            source_evidence=["existing.pdf"],
            confidence=0.5,
            needs_question=True,
            question="질문?",
        )
        pq = PendingQuestion(item_id="q1", question="질문?")
        state = _make_state(plans=[plan], pending_question=pq)

        from backend.app.graph.nodes.question import resume_with_answer
        result = resume_with_answer(state, "새 답변")

        updated_plan = next(p for p in result["plans"] if p.item_id == "q1")
        assert "existing.pdf" in updated_plan.source_evidence
        assert "새 답변" in updated_plan.source_evidence


# ---------------------------------------------------------------------------
# 5. resume_with_answer sets needs_question=False on the plan
# ---------------------------------------------------------------------------


class TestResumeNeedsQuestionFalse:
    def test_needs_question_cleared(self):
        plans = [_make_plan("q1", needs_question=True, question="질문?")]
        pq = PendingQuestion(item_id="q1", question="질문?")
        state = _make_state(plans=plans, pending_question=pq)

        from backend.app.graph.nodes.question import resume_with_answer
        result = resume_with_answer(state, "답변")

        updated_plan = next(p for p in result["plans"] if p.item_id == "q1")
        assert updated_plan.needs_question is False

    def test_other_plans_unchanged(self):
        plans = [
            _make_plan("q1", needs_question=True, question="질문?"),
            _make_plan("item2", needs_question=False),
        ]
        pq = PendingQuestion(item_id="q1", question="질문?")
        state = _make_state(plans=plans, pending_question=pq)

        from backend.app.graph.nodes.question import resume_with_answer
        result = resume_with_answer(state, "답변")

        other_plan = next(p for p in result["plans"] if p.item_id == "item2")
        assert other_plan.needs_question is False
        assert other_plan.source_evidence == ["cv.pdf"]


# ---------------------------------------------------------------------------
# 6. State not mutated
# ---------------------------------------------------------------------------


class TestStateMutation:
    def test_ask_question_does_not_mutate_state(self):
        plans = [_make_plan("q1", needs_question=True, question="질문?")]
        state = _make_state(plans=plans)
        original_pending = state.pending_question

        from backend.app.graph.nodes.question import ask_question
        ask_question(state)

        assert state.pending_question == original_pending

    def test_resume_does_not_mutate_state_plans(self):
        plans = [_make_plan("q1", needs_question=True, question="질문?")]
        pq = PendingQuestion(item_id="q1", question="질문?")
        state = _make_state(plans=plans, pending_question=pq)
        original_needs_question = state.plans[0].needs_question

        from backend.app.graph.nodes.question import resume_with_answer
        resume_with_answer(state, "답변")

        # Original state plan unchanged
        assert state.plans[0].needs_question == original_needs_question
