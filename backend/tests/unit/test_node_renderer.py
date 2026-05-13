"""Unit tests for Renderer node.

render_output(state: GraphState, form_bytes: bytes) -> dict
  Packs locked drafts + PII placeholders into HWPX bytes.
  Returns {"rendered_bytes": bytes, "preview_md": str}.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

from backend.app.graph.state import DraftItem, GraphState
from backend.app.hwpx.models import FormDoc, Item, Placeholder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).parent.parent / "fixtures" / "forms" / "sample_form.hwpx"


def _make_item(item_id: str, label: str = "항목", is_pii: bool = False) -> Item:
    return Item(
        item_id=item_id,
        label=label,
        section="Contents/section0.xml",
        kind="paragraph",
        xml_xpath=f"/p[{item_id}]",
        is_pii=is_pii,
    )


def _make_form(
    items: list[Item] | None = None,
    placeholders: list[Placeholder] | None = None,
) -> FormDoc:
    return FormDoc(
        sections=["Contents/section0.xml"],
        items=items or [],
        tables=[],
        placeholders=placeholders or [],
    )


def _make_draft(
    item_id: str,
    text: str = "작성된 내용입니다.",
    locked: bool = True,
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
) -> GraphState:
    return GraphState(
        form_doc=form_doc,
        drafts=drafts or [],
    )


def _minimal_hwpx_bytes() -> bytes:
    """Build a tiny valid HWPX zip for tests that don't need real XML patching."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, b"application/hwp+zip")
        section_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
            ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
            "<hp:p><hp:run><hp:t>연구 목표</hp:t></hp:run></hp:p>"
            "</hs:sec>"
        ).encode()
        z.writestr("Contents/section0.xml", section_xml)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Returns {"rendered_bytes": ..., "preview_md": ...}
# ---------------------------------------------------------------------------


class TestReturnShape:
    def test_returns_dict_with_both_keys(self):
        form = _make_form([_make_item("item1")])
        draft = _make_draft("item1", text="연구 성과")
        state = _make_state(form, [draft])
        form_bytes = _minimal_hwpx_bytes()

        from backend.app.graph.nodes.renderer import render_output

        result = render_output(state, form_bytes)

        assert "rendered_bytes" in result
        assert "preview_md" in result

    def test_rendered_bytes_is_bytes(self):
        form = _make_form([_make_item("item1")])
        state = _make_state(form, [_make_draft("item1")])
        form_bytes = _minimal_hwpx_bytes()

        from backend.app.graph.nodes.renderer import render_output

        result = render_output(state, form_bytes)

        assert isinstance(result["rendered_bytes"], bytes)

    def test_preview_md_is_str(self):
        form = _make_form([_make_item("item1")])
        state = _make_state(form, [_make_draft("item1")])
        form_bytes = _minimal_hwpx_bytes()

        from backend.app.graph.nodes.renderer import render_output

        result = render_output(state, form_bytes)

        assert isinstance(result["preview_md"], str)


# ---------------------------------------------------------------------------
# 2. PII items render the user-typed text when locked (no forced placeholder)
# ---------------------------------------------------------------------------


class TestPiiRendering:
    def test_pii_user_text_is_rendered_when_locked(self):
        pii_item = _make_item("pii1", "성명", is_pii=True)
        form = _make_form([pii_item])
        pii_draft = _make_draft("pii1", text="홍길동", locked=True, status="pii", is_pii=True)
        state = _make_state(form, [pii_draft])

        captured = []

        def spy_apply(src: bytes, drafts):
            captured.extend(drafts)
            return src

        form_bytes = _minimal_hwpx_bytes()
        with patch("backend.app.graph.nodes.renderer.apply_drafts", side_effect=spy_apply):
            from backend.app.graph.nodes.renderer import render_output

            render_output(state, form_bytes)

        rd = next((d for d in captured if d.item_id == "pii1"), None)
        assert rd is not None
        assert rd.text == "홍길동"
        assert rd.is_pii is True

    def test_pii_no_draft_is_skipped(self):
        pii_item = _make_item("pii1", "성명", is_pii=True)
        form = _make_form([pii_item])
        state = _make_state(form, drafts=[])

        captured = []

        def spy_apply(src: bytes, drafts):
            captured.extend(drafts)
            return src

        form_bytes = _minimal_hwpx_bytes()
        with patch("backend.app.graph.nodes.renderer.apply_drafts", side_effect=spy_apply):
            from backend.app.graph.nodes.renderer import render_output

            render_output(state, form_bytes)

        # No locked PII draft → nothing is written for this item.
        assert all(d.item_id != "pii1" for d in captured)

    def test_pii_unlocked_draft_is_skipped(self):
        pii_item = _make_item("pii1", "성명", is_pii=True)
        form = _make_form([pii_item])
        pii_draft = _make_draft("pii1", text="홍길동", locked=False, status="pii", is_pii=True)
        state = _make_state(form, [pii_draft])

        captured = []

        def spy_apply(src: bytes, drafts):
            captured.extend(drafts)
            return src

        form_bytes = _minimal_hwpx_bytes()
        with patch("backend.app.graph.nodes.renderer.apply_drafts", side_effect=spy_apply):
            from backend.app.graph.nodes.renderer import render_output

            render_output(state, form_bytes)

        # Unlocked PII draft → not in output (default include_unlocked=False).
        assert all(d.item_id != "pii1" for d in captured)

    def test_preview_marks_unfilled_pii_item(self):
        pii_item = _make_item("pii1", "성명", is_pii=True)
        form = _make_form([pii_item])
        state = _make_state(form)
        form_bytes = _minimal_hwpx_bytes()

        from backend.app.graph.nodes.renderer import render_output

        result = render_output(state, form_bytes)

        assert "성명" in result["preview_md"]
        assert "직접 입력 필요" in result["preview_md"]


# ---------------------------------------------------------------------------
# 3. Locked drafts are rendered; unlocked drafts are not
# ---------------------------------------------------------------------------


class TestApprovedDraftsRendered:
    def test_locked_draft_included_in_apply_drafts(self):
        item = _make_item("item1", "연구 목표")
        form = _make_form([item])
        draft = _make_draft("item1", text="연구 목표 내용", locked=True)
        state = _make_state(form, [draft])

        captured = []

        def spy_apply(src: bytes, drafts):
            captured.extend(drafts)
            return src

        form_bytes = _minimal_hwpx_bytes()
        with patch("backend.app.graph.nodes.renderer.apply_drafts", side_effect=spy_apply):
            from backend.app.graph.nodes.renderer import render_output

            render_output(state, form_bytes)

        ids = [d.item_id for d in captured]
        assert "item1" in ids

    def test_unlocked_draft_not_rendered(self):
        item = _make_item("item1", "연구 목표")
        form = _make_form([item])
        draft = _make_draft("item1", text="미완성", locked=False)
        state = _make_state(form, [draft])

        captured = []

        def spy_apply(src: bytes, drafts):
            captured.extend(drafts)
            return src

        form_bytes = _minimal_hwpx_bytes()
        with patch("backend.app.graph.nodes.renderer.apply_drafts", side_effect=spy_apply):
            from backend.app.graph.nodes.renderer import render_output

            render_output(state, form_bytes)

        ids = [d.item_id for d in captured]
        assert "item1" not in ids


# ---------------------------------------------------------------------------
# 4. Preview markdown contains item labels and text
# ---------------------------------------------------------------------------


class TestPreviewMarkdown:
    def test_preview_contains_item_label(self):
        item = _make_item("item1", "연구의 필요성")
        form = _make_form([item])
        state = _make_state(form, [_make_draft("item1", text="중요한 연구입니다.")])
        form_bytes = _minimal_hwpx_bytes()

        from backend.app.graph.nodes.renderer import render_output

        result = render_output(state, form_bytes)

        assert "연구의 필요성" in result["preview_md"]

    def test_preview_contains_draft_text(self):
        item = _make_item("item1", "연구 목표")
        form = _make_form([item])
        state = _make_state(form, [_make_draft("item1", text="혁신적인 AI 연구")])
        form_bytes = _minimal_hwpx_bytes()

        from backend.app.graph.nodes.renderer import render_output

        result = render_output(state, form_bytes)

        assert "혁신적인 AI 연구" in result["preview_md"]

    def test_preview_shows_undrafted_item_placeholder(self):
        item = _make_item("item1", "연구 결과")
        form = _make_form([item])
        state = _make_state(form, drafts=[])  # no draft for item1
        form_bytes = _minimal_hwpx_bytes()

        from backend.app.graph.nodes.renderer import render_output

        result = render_output(state, form_bytes)

        assert "연구 결과" in result["preview_md"]
        assert "미작성" in result["preview_md"]


# ---------------------------------------------------------------------------
# 5. Uses apply_drafts from hwpx.renderer
# ---------------------------------------------------------------------------


class TestUsesApplyDrafts:
    def test_apply_drafts_is_called(self):
        form = _make_form([_make_item("item1")])
        state = _make_state(form, [_make_draft("item1")])
        form_bytes = _minimal_hwpx_bytes()

        with patch(
            "backend.app.graph.nodes.renderer.apply_drafts", return_value=b"patched"
        ) as mock_apply:
            from backend.app.graph.nodes.renderer import render_output

            result = render_output(state, form_bytes)

        mock_apply.assert_called_once()
        assert result["rendered_bytes"] == b"patched"


# ---------------------------------------------------------------------------
# 6. State not mutated
# ---------------------------------------------------------------------------


class TestStateMutation:
    def test_state_drafts_not_mutated(self):
        form = _make_form([_make_item("item1")])
        draft = _make_draft("item1", text="원본")
        state = _make_state(form, [draft])
        original_text = state.drafts[0].text
        form_bytes = _minimal_hwpx_bytes()

        from backend.app.graph.nodes.renderer import render_output

        render_output(state, form_bytes)

        assert state.drafts[0].text == original_text


# ---------------------------------------------------------------------------
# 7. Empty form (no items) works
# ---------------------------------------------------------------------------


class TestEmptyForm:
    def test_empty_form_no_crash(self):
        form = _make_form(items=[])
        state = _make_state(form, drafts=[])
        form_bytes = _minimal_hwpx_bytes()

        from backend.app.graph.nodes.renderer import render_output

        result = render_output(state, form_bytes)

        assert "rendered_bytes" in result
        assert "preview_md" in result

    def test_no_form_doc_returns_original_bytes(self):
        state = _make_state(form_doc=None)
        form_bytes = _minimal_hwpx_bytes()

        from backend.app.graph.nodes.renderer import render_output

        result = render_output(state, form_bytes)

        assert result["rendered_bytes"] == form_bytes


# ---------------------------------------------------------------------------
# 8. Both PII placeholder and regular draft items are included
# ---------------------------------------------------------------------------


class TestBothPiiAndRegularItems:
    def test_pii_and_regular_both_in_apply_drafts_when_locked(self):
        pii_item = _make_item("pii1", "성명", is_pii=True)
        regular_item = _make_item("item1", "연구 목표")
        form = _make_form([pii_item, regular_item])
        drafts = [
            _make_draft("pii1", text="홍길동", locked=True, status="pii", is_pii=True),
            _make_draft("item1", text="연구 내용", locked=True),
        ]
        state = _make_state(form, drafts)

        captured = []

        def spy_apply(src: bytes, drafts):
            captured.extend(drafts)
            return src

        form_bytes = _minimal_hwpx_bytes()
        with patch("backend.app.graph.nodes.renderer.apply_drafts", side_effect=spy_apply):
            from backend.app.graph.nodes.renderer import render_output

            render_output(state, form_bytes)

        ids = {d.item_id for d in captured}
        assert "pii1" in ids
        assert "item1" in ids

    def test_pii_draft_has_is_pii_true_flag(self):
        pii_item = _make_item("pii1", "연락처", is_pii=True)
        form = _make_form([pii_item])
        pii_draft = _make_draft(
            "pii1", text="010-1234-5678", locked=True, status="pii", is_pii=True
        )
        state = _make_state(form, [pii_draft])

        captured = []

        def spy_apply(src: bytes, drafts):
            captured.extend(drafts)
            return src

        form_bytes = _minimal_hwpx_bytes()
        with patch("backend.app.graph.nodes.renderer.apply_drafts", side_effect=spy_apply):
            from backend.app.graph.nodes.renderer import render_output

            render_output(state, form_bytes)

        pii_rd = next(d for d in captured if d.item_id == "pii1")
        assert pii_rd.is_pii is True

    def test_regular_draft_has_is_pii_false_flag(self):
        regular_item = _make_item("item1", "연구 목표")
        form = _make_form([regular_item])
        draft = _make_draft("item1", text="목표 내용")
        state = _make_state(form, [draft])

        captured = []

        def spy_apply(src: bytes, drafts):
            captured.extend(drafts)
            return src

        form_bytes = _minimal_hwpx_bytes()
        with patch("backend.app.graph.nodes.renderer.apply_drafts", side_effect=spy_apply):
            from backend.app.graph.nodes.renderer import render_output

            render_output(state, form_bytes)

        regular_rd = next(d for d in captured if d.item_id == "item1")
        assert regular_rd.is_pii is False
