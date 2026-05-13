"""Unit tests for Verifier node.

verify_drafts(state: GraphState) -> dict
  Calls Solar per draft; applies verdict text markers.
  Returns {"drafts": list[DraftItem]}. locked is never mutated.
"""

from __future__ import annotations

from unittest.mock import patch

from backend.app.graph.state import DraftItem, GraphState, MaterialBundle
from backend.app.hwpx.models import FormDoc, Item

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
    return FormDoc(
        sections=["Contents/section1.xml"], items=list(items), tables=[], placeholders=[]
    )


def _make_draft(
    item_id: str,
    text: str = "초안 내용입니다.",
    locked: bool = False,
    status: str = "ok",
    is_pii: bool = False,
) -> DraftItem:
    return DraftItem(
        item_id=item_id,
        text=text,
        citations=["cv.pdf"],
        locked=locked,
        status=status,
        is_pii=is_pii,
    )


def _make_state(
    form_doc: FormDoc | None = None,
    drafts: list[DraftItem] | None = None,
    docs: list[dict] | None = None,
) -> GraphState:
    return GraphState(
        form_doc=form_doc,
        drafts=drafts or [],
        materials=MaterialBundle(docs=docs or []),
    )


# ---------------------------------------------------------------------------
# 1. ok verdict → status=ok, text/locked unchanged
# ---------------------------------------------------------------------------


class TestOkVerdict:
    def test_ok_locked_unchanged(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "ok", "reason": "내용이 적절합니다."},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].locked is False

    def test_ok_text_unchanged_and_status_ok(self):
        form = _make_form(_make_item("item1"))
        original_text = "원본 내용입니다."
        draft = _make_draft("item1", text=original_text)
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "ok", "reason": "OK"},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].text == original_text
        assert result["drafts"][0].status == "ok"


# ---------------------------------------------------------------------------
# 2. retry verdict → status="needs_review", text unchanged
# ---------------------------------------------------------------------------


class TestRetryVerdict:
    def test_retry_sets_status_and_leaves_text(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1", text="초안")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "retry", "reason": "수정 필요"},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].status == "needs_review"
        assert result["drafts"][0].text == "초안"

    def test_retry_locked_unchanged(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "retry", "reason": "수정 필요"},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].locked is False


# ---------------------------------------------------------------------------
# 3. soft_fail verdict → status="needs_check", text unchanged
# ---------------------------------------------------------------------------


class TestSoftFailVerdict:
    def test_soft_fail_sets_status_and_leaves_text(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1", text="초안")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "soft_fail", "reason": "경고"},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].status == "needs_check"
        assert result["drafts"][0].text == "초안"

    def test_soft_fail_locked_unchanged(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "soft_fail", "reason": "경고"},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].locked is False


# ---------------------------------------------------------------------------
# 4. Invalid Solar response → status="needs_check"
# ---------------------------------------------------------------------------


class TestInvalidSolarResponse:
    def test_solar_exception_marks_needs_check(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1", text="초안")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            side_effect=RuntimeError("Solar error"),
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].status == "needs_check"
        assert result["drafts"][0].locked is False

    def test_unknown_verdict_marks_needs_check(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1", text="초안")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "unknown_verdict", "reason": "?"},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].status == "needs_check"


# ---------------------------------------------------------------------------
# 5. Empty drafts returns empty list
# ---------------------------------------------------------------------------


class TestEmptyDrafts:
    def test_empty_drafts_returns_empty(self):
        form = _make_form(_make_item("item1"))
        state = _make_state(form, drafts=[])

        from backend.app.graph.nodes.verifier import verify_drafts

        result = verify_drafts(state)

        assert result["drafts"] == []


# ---------------------------------------------------------------------------
# 6. Multiple drafts all processed
# ---------------------------------------------------------------------------


class TestMultipleDrafts:
    def test_all_drafts_processed(self):
        form = _make_form(_make_item("item1"), _make_item("item2"), _make_item("item3"))
        drafts = [
            _make_draft("item1", text="내용1"),
            _make_draft("item2", text="내용2"),
            _make_draft("item3", text="내용3"),
        ]
        state = _make_state(form, drafts)

        verdicts = [
            {"verdict": "ok", "reason": "OK"},
            {"verdict": "retry", "reason": "수정"},
            {"verdict": "soft_fail", "reason": "경고"},
        ]

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            side_effect=verdicts,
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert len(result["drafts"]) == 3


# ---------------------------------------------------------------------------
# 7. State not mutated
# ---------------------------------------------------------------------------


class TestStateMutation:
    def test_state_drafts_not_mutated(self):
        form = _make_form(_make_item("item1"))
        original_text = "원본"
        draft = _make_draft("item1", text=original_text)
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "soft_fail", "reason": "경고"},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            verify_drafts(state)

        # State's original draft is unchanged
        assert state.drafts[0].text == original_text
        assert state.drafts[0].locked is False


# ---------------------------------------------------------------------------
# 8. locked stays False after verify_drafts (only user action sets it)
# ---------------------------------------------------------------------------


class TestPlaceholderPassthrough:
    def test_locked_stays_false_after_verify(self):
        form = _make_form(_make_item("item1"), _make_item("item2"))
        drafts = [_make_draft("item1"), _make_draft("item2")]
        state = _make_state(form, drafts)

        verdicts = [
            {"verdict": "ok", "reason": "OK"},
            {"verdict": "retry", "reason": "수정"},
        ]

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            side_effect=verdicts,
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert all(not d.locked for d in result["drafts"])

    def test_needs_info_draft_passed_through_unchanged(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1", text="", status="needs_info")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            side_effect=AssertionError("should not call Solar"),
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].status == "needs_info"
        assert result["drafts"][0].text == ""
        assert result["drafts"][0].locked is False

    def test_pii_draft_passed_through_unchanged(self):
        form = _make_form(_make_item("item1", "성명"))
        draft = _make_draft("item1", text="홍길동", status="pii", is_pii=True)
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            side_effect=AssertionError("should not call Solar for PII"),
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].status == "pii"
        assert result["drafts"][0].text == "홍길동"
        assert result["drafts"][0].is_pii is True
