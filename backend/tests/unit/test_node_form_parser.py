"""Tests for graph/nodes/form_parser — FormParser node.

parse_form(state: GraphState, form_bytes: bytes) -> dict
  Calls hwpx.parser.parse_hwpx, then pii.form_detector.flag_pii_items.
  Returns {"form_doc": FormDoc} with placeholders for every PII item.
  No LLM call.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

from backend.app.graph.nodes.form_parser import parse_form
from backend.app.graph.state import GraphState
from backend.app.hwpx.models import FormDoc, Item

FIXTURE = Path(__file__).parent.parent / "fixtures" / "forms" / "sample_form.hwpx"


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_item(item_id: str, label: str) -> Item:
    return Item(
        item_id=item_id,
        label=label,
        section="s",
        kind="paragraph",
        xml_xpath=f"/p[{item_id}]",
    )


def _make_doc(*items: Item) -> FormDoc:
    return FormDoc(sections=["main"], items=list(items), tables=[], placeholders=[])


def _make_hwpx_bytes(labels: list[str]) -> bytes:
    """Build a minimal HWPX ZIP with one paragraph per label."""
    paragraphs = "".join(
        f"  <hp:p><hp:run><hp:t>{label}</hp:t></hp:run></hp:p>\n" for label in labels
    )
    section_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
        ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">\n'
        f"{paragraphs}"
        "</hs:sec>\n"
    ).encode()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, b"application/hwp+zip")
        z.writestr("Contents/section0.xml", section_xml)
    return buf.getvalue()


# ── return-type contract ──────────────────────────────────────────────────────


def test_returns_dict_with_form_doc_key():
    state = GraphState()
    result = parse_form(state, FIXTURE.read_bytes())
    assert isinstance(result, dict)
    assert "form_doc" in result


def test_form_doc_is_formdoc_instance():
    state = GraphState()
    result = parse_form(state, FIXTURE.read_bytes())
    assert isinstance(result["form_doc"], FormDoc)


def test_form_doc_has_items():
    state = GraphState()
    result = parse_form(state, FIXTURE.read_bytes())
    assert len(result["form_doc"].items) >= 2


# ── PII flagging ──────────────────────────────────────────────────────────────


def test_pii_items_flagged_true():
    """Items whose labels contain PII keywords must have is_pii=True."""
    pii_doc = _make_doc(
        _make_item("i1", "성명"),
        _make_item("i2", "연구의 필요성"),
    )
    state = GraphState()
    with patch("backend.app.graph.nodes.form_parser.parse_hwpx", return_value=pii_doc):
        result = parse_form(state, b"fake-bytes")

    items = {it.item_id: it for it in result["form_doc"].items}
    assert items["i1"].is_pii is True


def test_non_pii_items_flagged_false():
    """Items whose labels do not contain PII keywords must have is_pii=False."""
    pii_doc = _make_doc(
        _make_item("i1", "성명"),
        _make_item("i2", "연구의 필요성"),
    )
    state = GraphState()
    with patch("backend.app.graph.nodes.form_parser.parse_hwpx", return_value=pii_doc):
        result = parse_form(state, b"fake-bytes")

    items = {it.item_id: it for it in result["form_doc"].items}
    assert items["i2"].is_pii is False


# ── Placeholder generation ────────────────────────────────────────────────────


def test_placeholder_created_for_each_pii_item():
    """One Placeholder per PII item must exist in form_doc.placeholders."""
    pii_doc = _make_doc(
        _make_item("i1", "성명"),
        _make_item("i2", "연락처"),
        _make_item("i3", "연구 목표"),
    )
    state = GraphState()
    with patch("backend.app.graph.nodes.form_parser.parse_hwpx", return_value=pii_doc):
        result = parse_form(state, b"fake-bytes")

    placeholders = result["form_doc"].placeholders
    placeholder_ids = {p.item_id for p in placeholders}
    assert "i1" in placeholder_ids
    assert "i2" in placeholder_ids
    assert "i3" not in placeholder_ids


def test_placeholder_text_is_본인직접입력():
    """Every placeholder must carry the canonical replacement text."""
    pii_doc = _make_doc(
        _make_item("i1", "주민등록번호"),
        _make_item("i2", "연구 기간"),
    )
    state = GraphState()
    with patch("backend.app.graph.nodes.form_parser.parse_hwpx", return_value=pii_doc):
        result = parse_form(state, b"fake-bytes")

    for ph in result["form_doc"].placeholders:
        assert ph.placeholder_text == "[본인 직접 입력]"


def test_placeholder_count_equals_pii_item_count():
    """Number of placeholders equals exact number of PII-flagged items."""
    pii_doc = _make_doc(
        _make_item("i1", "성명"),
        _make_item("i2", "이메일"),
        _make_item("i3", "계좌번호"),
        _make_item("i4", "연구의 필요성"),
    )
    state = GraphState()
    with patch("backend.app.graph.nodes.form_parser.parse_hwpx", return_value=pii_doc):
        result = parse_form(state, b"fake-bytes")

    pii_count = sum(1 for it in result["form_doc"].items if it.is_pii)
    assert len(result["form_doc"].placeholders) == pii_count


def test_no_placeholder_when_no_pii_items():
    """FormDoc with no PII items must produce an empty placeholders list."""
    clean_doc = _make_doc(
        _make_item("i1", "연구의 필요성"),
        _make_item("i2", "예상 결과"),
    )
    state = GraphState()
    with patch("backend.app.graph.nodes.form_parser.parse_hwpx", return_value=clean_doc):
        result = parse_form(state, b"fake-bytes")

    assert result["form_doc"].placeholders == []


# ── immutability ──────────────────────────────────────────────────────────────


def test_original_state_not_mutated():
    """parse_form must not mutate the incoming GraphState."""
    state = GraphState(session_id="test-session")
    parse_form(state, FIXTURE.read_bytes())
    assert state.session_id == "test-session"
    assert state.form_doc is None


# ── end-to-end with real fixture ──────────────────────────────────────────────


def test_real_fixture_round_trip():
    """Parse the real sample_form.hwpx; expect non-PII labels, no placeholders."""
    state = GraphState()
    result = parse_form(state, FIXTURE.read_bytes())
    doc = result["form_doc"]

    assert isinstance(doc, FormDoc)
    labels = [it.label for it in doc.items]
    assert "연구의 필요성" in labels
    assert "예상 결과" in labels
    # fixture has no PII labels → no placeholders
    assert doc.placeholders == []


def test_real_fixture_with_pii_labels_in_hwpx():
    """Build a minimal HWPX that includes PII-labelled paragraphs; verify end-to-end."""
    hwpx_bytes = _make_hwpx_bytes(["성명", "연구의 필요성", "이메일", "예상 결과"])
    state = GraphState()
    result = parse_form(state, hwpx_bytes)
    doc = result["form_doc"]

    pii_ids = {it.item_id for it in doc.items if it.is_pii}
    placeholder_ids = {ph.item_id for ph in doc.placeholders}
    assert pii_ids == placeholder_ids
    for ph in doc.placeholders:
        assert ph.placeholder_text == "[본인 직접 입력]"
