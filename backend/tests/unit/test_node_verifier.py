"""Unit tests for Verifier node.

verify_drafts(state: GraphState) -> dict
  Calls Solar per unapproved draft; applies verdict transformation.
  Returns {"drafts": list[DraftItem]} with all approved=True.
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


def _make_draft(item_id: str, text: str = "초안 내용입니다.", approved: bool = False) -> DraftItem:
    return DraftItem(item_id=item_id, text=text, citations=["cv.pdf"], approved=approved)


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
# 1. ok verdict → draft approved=True, text unchanged
# ---------------------------------------------------------------------------


class TestOkVerdict:
    def test_ok_sets_approved_true(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "ok", "reason": "내용이 적절합니다."},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].approved is True

    def test_ok_text_unchanged(self):
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


# ---------------------------------------------------------------------------
# 2. retry verdict → draft text modified with marker
# ---------------------------------------------------------------------------


class TestRetryVerdict:
    def test_retry_adds_prefix_marker(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1", text="초안")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "retry", "reason": "수정 필요"},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].text.startswith("[검토 필요]")

    def test_retry_sets_approved_true(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "retry", "reason": "수정 필요"},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].approved is True


# ---------------------------------------------------------------------------
# 3. soft_fail verdict → draft text modified with [확인 필요]
# ---------------------------------------------------------------------------


class TestSoftFailVerdict:
    def test_soft_fail_adds_suffix_marker(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1", text="초안")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "soft_fail", "reason": "경고"},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert "[확인 필요]" in result["drafts"][0].text

    def test_soft_fail_sets_approved_true(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "soft_fail", "reason": "경고"},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].approved is True


# ---------------------------------------------------------------------------
# 4. Invalid Solar response → draft marked as [확인 필요]
# ---------------------------------------------------------------------------


class TestInvalidSolarResponse:
    def test_solar_exception_marks_soft_fail(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1", text="초안")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            side_effect=RuntimeError("Solar error"),
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert "[확인 필요]" in result["drafts"][0].text
        assert result["drafts"][0].approved is True

    def test_unknown_verdict_marks_soft_fail(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1", text="초안")
        state = _make_state(form, [draft])

        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "unknown_verdict", "reason": "?"},
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert "[확인 필요]" in result["drafts"][0].text


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
        assert state.drafts[0].approved is False


# ---------------------------------------------------------------------------
# 8. All drafts end up approved=True after verify_drafts
# ---------------------------------------------------------------------------


class TestAllApproved:
    def test_all_drafts_approved_after_verify(self):
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

        assert all(d.approved for d in result["drafts"])

    def test_already_approved_drafts_passed_through(self):
        form = _make_form(_make_item("item1"))
        draft = _make_draft("item1", approved=True)
        state = _make_state(form, [draft])

        # Solar should NOT be called for already-approved drafts
        with patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            side_effect=AssertionError("should not call Solar"),
        ):
            from backend.app.graph.nodes.verifier import verify_drafts

            result = verify_drafts(state)

        assert result["drafts"][0].approved is True
