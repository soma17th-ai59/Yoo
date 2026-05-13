"""Unit tests for Generator node.

generate_drafts(state: GraphState) -> dict
  For each ItemPlan where is_pii=False and needs_question=False:
    Calls Solar, runs output guard, retries up to 2× on PII detection.
  Returns {"drafts": list[DraftItem]}.
"""

from __future__ import annotations

from unittest.mock import patch

from backend.app.graph.state import DraftItem, GraphState, ItemPlan, MaterialBundle
from backend.app.hwpx.models import FormDoc, Item

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(item_id: str, label: str = "항목", is_pii: bool = False) -> Item:
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


def _make_plan(
    item_id: str,
    needs_question: bool = False,
    source_evidence: list[str] | None = None,
    question: str | None = None,
) -> ItemPlan:
    return ItemPlan(
        item_id=item_id,
        source_evidence=source_evidence or [],
        confidence=0.8,
        needs_question=needs_question,
        question=question,
    )


def _make_state(
    form_doc: FormDoc | None = None,
    plans: list[ItemPlan] | None = None,
    docs: list[dict] | None = None,
) -> GraphState:
    return GraphState(
        form_doc=form_doc,
        plans=plans or [],
        materials=MaterialBundle(docs=docs or []),
    )


_CLEAN_RESPONSE = {
    "text": "우수한 연구 성과를 바탕으로 작성된 내용입니다.",
    "citations": ["cv.pdf"],
}
_PII_RESPONSE = {"text": "홍길동 주민번호 901231-1234567 연구자입니다.", "citations": []}


def _scan_always_clean(text: str):
    return True, text


def _scan_always_pii(text: str):
    return False, "[MASKED]"


# ---------------------------------------------------------------------------
# 1. Returns {"drafts": [...]} dict
# ---------------------------------------------------------------------------


class TestReturnShape:
    def test_returns_dict_with_drafts_key(self):
        form = _make_form(_make_item("item1"))
        state = _make_state(form, [_make_plan("item1")])

        with (
            patch(
                "backend.app.graph.nodes.generator._solar_complete", return_value=_CLEAN_RESPONSE
            ),
            patch("backend.app.graph.nodes.generator.scan", side_effect=_scan_always_clean),
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            result = generate_drafts(state)

        assert "drafts" in result
        assert isinstance(result["drafts"], list)


# ---------------------------------------------------------------------------
# 2. DraftItem has text, citations, item_id, locked=False
# ---------------------------------------------------------------------------


class TestDraftItemFields:
    def test_draft_item_is_draft_item_instance(self):
        form = _make_form(_make_item("item1"))
        state = _make_state(form, [_make_plan("item1")])

        with (
            patch(
                "backend.app.graph.nodes.generator._solar_complete", return_value=_CLEAN_RESPONSE
            ),
            patch("backend.app.graph.nodes.generator.scan", side_effect=_scan_always_clean),
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            result = generate_drafts(state)

        assert all(isinstance(d, DraftItem) for d in result["drafts"])

    def test_draft_locked_false_by_default(self):
        form = _make_form(_make_item("item1"))
        state = _make_state(form, [_make_plan("item1")])

        with (
            patch(
                "backend.app.graph.nodes.generator._solar_complete", return_value=_CLEAN_RESPONSE
            ),
            patch("backend.app.graph.nodes.generator.scan", side_effect=_scan_always_clean),
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            result = generate_drafts(state)

        assert result["drafts"][0].locked is False

    def test_draft_has_correct_item_id(self):
        form = _make_form(_make_item("goal_item"))
        state = _make_state(form, [_make_plan("goal_item")])

        with (
            patch(
                "backend.app.graph.nodes.generator._solar_complete", return_value=_CLEAN_RESPONSE
            ),
            patch("backend.app.graph.nodes.generator.scan", side_effect=_scan_always_clean),
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            result = generate_drafts(state)

        assert result["drafts"][0].item_id == "goal_item"

    def test_draft_has_text_and_citations(self):
        form = _make_form(_make_item("item1"))
        state = _make_state(form, [_make_plan("item1")])

        with (
            patch(
                "backend.app.graph.nodes.generator._solar_complete", return_value=_CLEAN_RESPONSE
            ),
            patch("backend.app.graph.nodes.generator.scan", side_effect=_scan_always_clean),
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            result = generate_drafts(state)

        d = result["drafts"][0]
        assert d.text == _CLEAN_RESPONSE["text"]
        assert d.citations == _CLEAN_RESPONSE["citations"]


# ---------------------------------------------------------------------------
# 3. PII items get empty drafts with status="pii", no Solar call
# ---------------------------------------------------------------------------


class TestPiiItemsGetEmptyDraft:
    def test_pii_item_emits_empty_pii_draft(self):
        form = _make_form(_make_item("pii1", "성명", is_pii=True), _make_item("item1"))
        pii_plan = ItemPlan(
            item_id="pii1",
            source_evidence=["pii_placeholder"],
            confidence=1.0,
            needs_question=False,
        )
        normal_plan = _make_plan("item1")
        state = _make_state(form, [pii_plan, normal_plan])

        solar_calls: list = []

        def _spy(messages):
            solar_calls.append(messages)
            return _CLEAN_RESPONSE

        with (
            patch("backend.app.graph.nodes.generator._solar_complete", side_effect=_spy),
            patch("backend.app.graph.nodes.generator.scan", side_effect=_scan_always_clean),
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            result = generate_drafts(state)

        ids = [d.item_id for d in result["drafts"]]
        assert "pii1" in ids
        assert "item1" in ids

        pii_draft = next(d for d in result["drafts"] if d.item_id == "pii1")
        assert pii_draft.text == ""
        assert pii_draft.citations == []
        assert pii_draft.status == "pii"
        assert pii_draft.is_pii is True
        assert pii_draft.locked is False

        # Solar must NOT have been called for the PII plan (only for item1).
        assert len(solar_calls) == 1


# ---------------------------------------------------------------------------
# 4. needs_question items are skipped
# ---------------------------------------------------------------------------


class TestNeedsQuestionPlaceholder:
    """Generator emits an empty-text placeholder draft with status="needs_info"
    for plans whose needs_question=True. Status flags are carried in the
    status field, not embedded in text."""

    def test_needs_question_item_gets_empty_needs_info_draft(self):
        form = _make_form(_make_item("q_item"), _make_item("item1"))
        plans = [
            _make_plan("q_item", needs_question=True, question="강점이 무엇인가요?"),
            _make_plan("item1"),
        ]
        state = _make_state(form, plans)

        with (
            patch(
                "backend.app.graph.nodes.generator._solar_complete", return_value=_CLEAN_RESPONSE
            ),
            patch("backend.app.graph.nodes.generator.scan", side_effect=_scan_always_clean),
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            result = generate_drafts(state)

        ids = [d.item_id for d in result["drafts"]]
        assert "q_item" in ids
        assert "item1" in ids

        q_draft = next(d for d in result["drafts"] if d.item_id == "q_item")
        assert q_draft.text == ""
        assert q_draft.status == "needs_info"
        assert q_draft.citations == []

    def test_needs_question_no_question_text_still_emits_needs_info(self):
        form = _make_form(_make_item("q_item"))
        plans = [_make_plan("q_item", needs_question=True, question=None)]
        state = _make_state(form, plans)

        with patch(
            "backend.app.graph.nodes.generator._solar_complete", return_value=_CLEAN_RESPONSE
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            result = generate_drafts(state)

        assert len(result["drafts"]) == 1
        assert result["drafts"][0].status == "needs_info"
        assert result["drafts"][0].text == ""


# ---------------------------------------------------------------------------
# 5. Output guard retry: PII twice then clean → final draft has clean text
# ---------------------------------------------------------------------------


class TestOutputGuardRetry:
    def test_retry_on_pii_then_clean(self):
        """Solar returns PII text twice, then clean text on 3rd attempt."""
        form = _make_form(_make_item("item1"))
        state = _make_state(form, [_make_plan("item1")])

        solar_responses = [_PII_RESPONSE, _PII_RESPONSE, _CLEAN_RESPONSE]
        scan_results = [
            (False, "[MASKED]"),  # 1st attempt PII detected
            (False, "[MASKED]"),  # 2nd attempt PII detected
            (True, _CLEAN_RESPONSE["text"]),  # 3rd attempt clean
        ]

        with (
            patch("backend.app.graph.nodes.generator._solar_complete", side_effect=solar_responses),
            patch("backend.app.graph.nodes.generator.scan", side_effect=scan_results),
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            result = generate_drafts(state)

        assert result["drafts"][0].text == _CLEAN_RESPONSE["text"]


# ---------------------------------------------------------------------------
# 6. After 3 PII-tainted outputs, draft text is "[확인 필요]"
# ---------------------------------------------------------------------------


class TestFallbackAfterMaxRetries:
    def test_all_pii_results_in_empty_text_with_needs_check(self):
        form = _make_form(_make_item("item1"))
        state = _make_state(form, [_make_plan("item1")])

        with (
            patch("backend.app.graph.nodes.generator._solar_complete", return_value=_PII_RESPONSE),
            patch("backend.app.graph.nodes.generator.scan", return_value=(False, "[MASKED]")),
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            result = generate_drafts(state)

        # leaked PII must NOT reach the UI — text is wiped and status flags it.
        assert result["drafts"][0].text == ""
        assert result["drafts"][0].status == "needs_check"

    def test_fallback_has_empty_citations(self):
        form = _make_form(_make_item("item1"))
        state = _make_state(form, [_make_plan("item1")])

        with (
            patch("backend.app.graph.nodes.generator._solar_complete", return_value=_PII_RESPONSE),
            patch("backend.app.graph.nodes.generator.scan", return_value=(False, "[MASKED]")),
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            result = generate_drafts(state)

        assert result["drafts"][0].citations == []


# ---------------------------------------------------------------------------
# 7. Empty plans returns empty drafts
# ---------------------------------------------------------------------------


class TestEmptyPlans:
    def test_empty_plans_returns_empty_drafts(self):
        form = _make_form(_make_item("item1"))
        state = _make_state(form, plans=[])

        from backend.app.graph.nodes.generator import generate_drafts

        result = generate_drafts(state)

        assert result["drafts"] == []

    def test_no_form_doc_returns_empty_drafts(self):
        state = _make_state(form_doc=None, plans=[_make_plan("item1")])

        from backend.app.graph.nodes.generator import generate_drafts

        result = generate_drafts(state)

        assert result["drafts"] == []


# ---------------------------------------------------------------------------
# 8. State not mutated
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 9. Non-fillable (label) cells produce no draft (defense-in-depth)
# ---------------------------------------------------------------------------


def test_generator_skips_non_fillable_items(monkeypatch):
    """Defensive: even if a plan exists for a non-fillable item, generator skips it."""
    from backend.app.graph.nodes.generator import generate_drafts
    from backend.app.graph.state import GraphState, ItemPlan
    from backend.app.hwpx.models import FormDoc, Item

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
        plans=[
            ItemPlan(
                item_id="s:tbl0:r0c0", source_evidence=[], confidence=0.5, needs_question=False
            ),
            ItemPlan(
                item_id="s:tbl0:r0c1", source_evidence=[], confidence=0.5, needs_question=False
            ),
        ],
    )

    monkeypatch.setattr(
        "backend.app.graph.nodes.generator._solar_complete",
        lambda messages: {"text": "본문", "citations": []},
    )

    result = generate_drafts(state)
    draft_ids = {d.item_id for d in result["drafts"]}
    assert "s:tbl0:r0c0" not in draft_ids
    assert "s:tbl0:r0c1" in draft_ids


class TestStateMutation:
    def test_state_plans_not_mutated(self):
        form = _make_form(_make_item("item1"))
        plans = [_make_plan("item1")]
        state = _make_state(form, plans)
        original_plans = list(state.plans)

        with (
            patch(
                "backend.app.graph.nodes.generator._solar_complete", return_value=_CLEAN_RESPONSE
            ),
            patch("backend.app.graph.nodes.generator.scan", side_effect=_scan_always_clean),
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            generate_drafts(state)

        assert state.plans == original_plans

    def test_state_drafts_not_mutated(self):
        form = _make_form(_make_item("item1"))
        state = _make_state(form, [_make_plan("item1")])
        original_drafts = list(state.drafts)

        with (
            patch(
                "backend.app.graph.nodes.generator._solar_complete", return_value=_CLEAN_RESPONSE
            ),
            patch("backend.app.graph.nodes.generator.scan", side_effect=_scan_always_clean),
        ):
            from backend.app.graph.nodes.generator import generate_drafts

            generate_drafts(state)

        assert state.drafts == original_drafts
