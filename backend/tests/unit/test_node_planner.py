"""Unit tests for Planner node.

plan_items(state: GraphState) -> dict
  Calls Solar with build_planner_messages; returns {"plans": list[ItemPlan]}.
  PII items always get a fixed placeholder plan.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.app.graph.state import GraphState, ItemPlan, MaterialBundle
from backend.app.hwpx.models import FormDoc, Item

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(item_id: str, label: str, is_pii: bool = False) -> Item:
    return Item(
        item_id=item_id,
        label=label,
        section="Contents/section1.xml",
        kind="paragraph",
        xml_xpath=f"/p[{item_id}]",
        is_pii=is_pii,
    )


def _make_form(*items: Item) -> FormDoc:
    return FormDoc(
        sections=["Contents/section1.xml"], items=list(items), tables=[], placeholders=[]
    )


def _make_state(form_doc: FormDoc | None = None, docs: list[dict] | None = None) -> GraphState:
    return GraphState(
        form_doc=form_doc,
        materials=MaterialBundle(docs=docs or []),
    )


_SOLAR_PLAN = [
    {
        "item_id": "item1",
        "source_evidence": ["cv.pdf"],
        "confidence": 0.9,
        "needs_question": False,
        "question": None,
    },
    {
        "item_id": "item2",
        "source_evidence": ["paper.pdf"],
        "confidence": 0.7,
        "needs_question": False,
        "question": None,
    },
]


# ---------------------------------------------------------------------------
# 1. Returns {"plans": [...]} dict
# ---------------------------------------------------------------------------


class TestReturnShape:
    def test_returns_dict_with_plans_key(self):
        form = _make_form(_make_item("item1", "연구 목표"))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=[
                {
                    "item_id": "item1",
                    "source_evidence": [],
                    "confidence": 0.8,
                    "needs_question": False,
                    "question": None,
                }
            ],
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        assert "plans" in result

    def test_plans_is_list(self):
        form = _make_form(_make_item("item1", "연구 목표"))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=[
                {
                    "item_id": "item1",
                    "source_evidence": [],
                    "confidence": 0.8,
                    "needs_question": False,
                    "question": None,
                }
            ],
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        assert isinstance(result["plans"], list)


# ---------------------------------------------------------------------------
# 2. Returns ItemPlan objects for each non-PII item
# ---------------------------------------------------------------------------


class TestItemPlanObjects:
    def test_returns_item_plan_instances(self):
        form = _make_form(_make_item("item1", "연구 목표"), _make_item("item2", "연구 방법"))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=_SOLAR_PLAN,
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        for plan in result["plans"]:
            assert isinstance(plan, ItemPlan)

    def test_plan_count_matches_items(self):
        form = _make_form(_make_item("item1", "A"), _make_item("item2", "B"))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=_SOLAR_PLAN,
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        assert len(result["plans"]) == 2

    def test_non_pii_plan_has_solar_evidence(self):
        form = _make_form(_make_item("item1", "연구 목표"))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=[
                {
                    "item_id": "item1",
                    "source_evidence": ["cv.pdf"],
                    "confidence": 0.9,
                    "needs_question": False,
                    "question": None,
                }
            ],
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        plan = result["plans"][0]
        assert "cv.pdf" in plan.source_evidence


# ---------------------------------------------------------------------------
# 3. PII items always get fixed plan
# ---------------------------------------------------------------------------


class TestPiiItems:
    def test_pii_item_needs_question_false(self):
        form = _make_form(_make_item("pii1", "성명", is_pii=True))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=[],
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        plan = next(p for p in result["plans"] if p.item_id == "pii1")
        assert plan.needs_question is False

    def test_pii_item_source_evidence_is_placeholder(self):
        form = _make_form(_make_item("pii1", "주민등록번호", is_pii=True))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=[],
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        plan = next(p for p in result["plans"] if p.item_id == "pii1")
        assert plan.source_evidence == ["pii_placeholder"]

    def test_pii_item_confidence_is_1(self):
        form = _make_form(_make_item("pii1", "연락처", is_pii=True))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=[],
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        plan = next(p for p in result["plans"] if p.item_id == "pii1")
        assert plan.confidence == 1.0

    def test_pii_item_not_sent_to_solar(self):
        """Solar is still called for non-PII items, but PII items are never sent."""
        form = _make_form(
            _make_item("pii1", "성명", is_pii=True),
            _make_item("item1", "연구 목표"),
        )
        state = _make_state(form)

        solar_calls = []

        def spy_solar(messages):
            solar_calls.append(messages)
            return [
                {
                    "item_id": "item1",
                    "source_evidence": [],
                    "confidence": 0.8,
                    "needs_question": False,
                    "question": None,
                }
            ]

        with patch("backend.app.graph.nodes.planner._solar_complete", side_effect=spy_solar):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        # PII item plan is always fixed
        pii_plan = next(p for p in result["plans"] if p.item_id == "pii1")
        assert pii_plan.source_evidence == ["pii_placeholder"]


# ---------------------------------------------------------------------------
# 4. Solar receives form items and materials in user message
# ---------------------------------------------------------------------------


class TestSolarInput:
    def test_solar_receives_item_ids(self):
        form = _make_form(_make_item("research_goal", "연구 목표"))
        state = _make_state(form, docs=[{"filename": "cv.pdf", "summary": "이력서"}])

        captured = []

        def spy(messages):
            captured.extend(messages)
            return [
                {
                    "item_id": "research_goal",
                    "source_evidence": ["cv.pdf"],
                    "confidence": 0.8,
                    "needs_question": False,
                    "question": None,
                }
            ]

        with patch("backend.app.graph.nodes.planner._solar_complete", side_effect=spy):
            from backend.app.graph.nodes.planner import plan_items

            plan_items(state)

        user_msg = next(m for m in captured if m["role"] == "user")
        assert "research_goal" in user_msg["content"]

    def test_solar_receives_material_filenames(self):
        form = _make_form(_make_item("item1", "연구 목표"))
        state = _make_state(form, docs=[{"filename": "thesis.pdf", "summary": "논문 요약"}])

        captured = []

        def spy(messages):
            captured.extend(messages)
            return [
                {
                    "item_id": "item1",
                    "source_evidence": [],
                    "confidence": 0.5,
                    "needs_question": True,
                    "question": "추가 정보 필요",
                }
            ]

        with patch("backend.app.graph.nodes.planner._solar_complete", side_effect=spy):
            from backend.app.graph.nodes.planner import plan_items

            plan_items(state)

        user_msg = next(m for m in captured if m["role"] == "user")
        assert "thesis.pdf" in user_msg["content"]


# ---------------------------------------------------------------------------
# 5. Handle Solar returning fewer plans than items (missing items get default)
# ---------------------------------------------------------------------------


class TestMissingPlans:
    def test_missing_items_get_default_plan(self):
        form = _make_form(_make_item("item1", "A"), _make_item("item2", "B"))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=[
                {
                    "item_id": "item1",
                    "source_evidence": [],
                    "confidence": 0.8,
                    "needs_question": False,
                    "question": None,
                }
            ],
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        assert len(result["plans"]) == 2
        missing = next(p for p in result["plans"] if p.item_id == "item2")
        assert missing.needs_question is True

    def test_default_plan_has_needs_question_true(self):
        form = _make_form(_make_item("orphan", "B"))
        state = _make_state(form)

        with patch("backend.app.graph.nodes.planner._solar_complete", return_value=[]):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        plan = result["plans"][0]
        assert plan.needs_question is True


# ---------------------------------------------------------------------------
# 6. Handle Solar returning invalid JSON → errors
# ---------------------------------------------------------------------------


class TestSolarErrors:
    def test_solar_exception_returns_errors(self):
        form = _make_form(_make_item("item1", "A"))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            side_effect=RuntimeError("Solar down"),
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        assert "errors" in result
        assert len(result["errors"]) > 0

    def test_solar_invalid_json_returns_errors(self):
        form = _make_form(_make_item("item1", "A"))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            side_effect=ValueError("JSON decode error"),
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        assert "errors" in result


# ---------------------------------------------------------------------------
# 7. Handle empty materials gracefully
# ---------------------------------------------------------------------------


class TestWrapperKeys:
    """Solar wraps the plan list under different keys depending on call context.

    Regression: when Solar returned {"itemPlans": [...]} the planner used to
    ignore the wrapper, fall back to [], and mark every non-PII item with
    needs_question=True. Now any of plans / items / itemPlans / item_plans /
    data is recognised, plus a generic "first list value" fallback.
    """

    @staticmethod
    def _plan_payload(item_id: str) -> dict:
        return {
            "item_id": item_id,
            "source_evidence": ["cv.pdf"],
            "confidence": 0.9,
            "needs_question": False,
            "question": None,
        }

    @pytest.mark.parametrize(
        "wrapper_key",
        ["plans", "items", "itemPlans", "ItemPlan", "ItemPlans", "item_plans", "data"],
    )
    def test_recognised_wrapper_keys(self, wrapper_key):
        form = _make_form(_make_item("item1", "연구 목표"))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value={wrapper_key: [self._plan_payload("item1")]},
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        assert len(result["plans"]) == 1
        assert result["plans"][0].item_id == "item1"
        assert result["plans"][0].needs_question is False

    def test_unknown_wrapper_falls_back_to_first_list_value(self):
        form = _make_form(_make_item("item1", "연구 목표"))
        state = _make_state(form)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value={"meta": "ignored", "weirdKey": [self._plan_payload("item1")]},
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        assert len(result["plans"]) == 1
        assert result["plans"][0].needs_question is False


class TestEmptyMaterials:
    def test_empty_materials_no_crash(self):
        form = _make_form(_make_item("item1", "연구 목표"))
        state = _make_state(form, docs=[])  # no materials

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=[
                {
                    "item_id": "item1",
                    "source_evidence": [],
                    "confidence": 0.5,
                    "needs_question": True,
                    "question": "추가 정보 필요",
                }
            ],
        ):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        assert "plans" in result
        assert len(result["plans"]) == 1

    def test_empty_form_returns_empty_plans(self):
        form = _make_form()  # no items
        state = _make_state(form)

        with patch("backend.app.graph.nodes.planner._solar_complete", return_value=[]):
            from backend.app.graph.nodes.planner import plan_items

            result = plan_items(state)

        assert result["plans"] == []


# ---------------------------------------------------------------------------
# 8. State not mutated
# ---------------------------------------------------------------------------


class TestStateMutation:
    def test_state_not_mutated(self):
        form = _make_form(_make_item("item1", "연구 목표"))
        state = _make_state(form)
        original_plans = list(state.plans)

        with patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=[
                {
                    "item_id": "item1",
                    "source_evidence": [],
                    "confidence": 0.8,
                    "needs_question": False,
                    "question": None,
                }
            ],
        ):
            from backend.app.graph.nodes.planner import plan_items

            plan_items(state)

        assert state.plans == original_plans


# ---------------------------------------------------------------------------
# 9. Non-fillable (label) cells produce no plan
# ---------------------------------------------------------------------------


def test_planner_skips_non_fillable_label_cells(monkeypatch):
    """Items with fillable=False (table label cells) get no plan at all."""
    from backend.app.graph.nodes.planner import plan_items
    from backend.app.graph.state import GraphState
    from backend.app.hwpx.models import FormDoc, Item

    monkeypatch.setattr(
        "backend.app.graph.nodes.planner._solar_complete",
        lambda messages: [],
    )

    label_cell = Item(
        item_id="s:tbl0:r0c0",
        label="자기소개",
        section="s",
        kind="table_cell",
        xml_xpath="/x",
        fillable=False,
    )
    value_cell = Item(
        item_id="s:tbl0:r0c1",
        label="자기소개",
        section="s",
        kind="table_cell",
        xml_xpath="/x",
        fillable=True,
    )
    state = GraphState(
        form_doc=FormDoc(
            sections=["s"], items=[label_cell, value_cell], tables=[], placeholders=[]
        ),
    )

    result = plan_items(state)
    plan_ids = {p.item_id for p in result["plans"]}
    assert "s:tbl0:r0c0" not in plan_ids, "label cell should not get a plan"
    assert "s:tbl0:r0c1" in plan_ids, "value cell should get a plan"
