import io
import zipfile
from pathlib import Path

from backend.app.hwpx.parser import parse_hwpx
from backend.app.hwpx.renderer import DraftItem, apply_drafts

FIXTURE = Path("backend/tests/fixtures/forms/sample_form.hwpx")


def test_apply_drafts_inserts_text():
    src = FIXTURE.read_bytes()
    doc = parse_hwpx(src)
    target = next(it for it in doc.items if it.kind == "paragraph")
    out = apply_drafts(src, [DraftItem(item_id=target.item_id, text="새 본문 내용")])
    new_doc = parse_hwpx(out)
    assert any("새 본문 내용" in i.label for i in new_doc.items)


def test_apply_drafts_pii_uses_placeholder():
    src = FIXTURE.read_bytes()
    doc = parse_hwpx(src)
    target = next(it for it in doc.items if it.kind == "paragraph")
    out = apply_drafts(
        src,
        [DraftItem(item_id=target.item_id, text="민감정보", is_pii=True)],
    )
    new_doc = parse_hwpx(out)
    labels = [i.label for i in new_doc.items]
    assert any("[본인 직접 입력]" in lbl for lbl in labels)
    assert not any("민감정보" in lbl for lbl in labels)


def test_apply_drafts_preserves_non_xml_members():
    src = FIXTURE.read_bytes()
    doc = parse_hwpx(src)
    para = next(it for it in doc.items if it.kind == "paragraph")
    out = apply_drafts(src, [DraftItem(item_id=para.item_id, text="변경")])

    with zipfile.ZipFile(io.BytesIO(src)) as zin, zipfile.ZipFile(io.BytesIO(out)) as zout:
        src_names = set(zin.namelist())
        out_names = set(zout.namelist())
        assert "mimetype" in out_names

        # mimetype must be first and stored uncompressed
        out_infos = zout.infolist()
        assert out_infos[0].filename == "mimetype"
        assert out_infos[0].compress_type == zipfile.ZIP_STORED

        # non-section files are byte-identical
        non_section = [n for n in src_names if not n.startswith("Contents/section")]
        for name in non_section:
            assert zin.read(name) == zout.read(name), f"Mismatch in {name}"


def test_apply_drafts_with_invalid_item_id_is_no_op():
    src = FIXTURE.read_bytes()
    out = apply_drafts(src, [DraftItem(item_id="Contents/section0.xml:p999", text="무시됨")])
    # Should not raise; output still parses correctly
    doc = parse_hwpx(out)
    assert len(doc.items) >= 2
    labels = [i.label for i in doc.items]
    assert not any("무시됨" in lbl for lbl in labels)


def test_apply_drafts_writes_to_table_cell_not_label():
    """Regression: drafts targeting a value cell must update that cell only,
    not the adjacent label cell."""
    src = FIXTURE.read_bytes()
    doc = parse_hwpx(src)
    target = next(
        it for it in doc.items
        if it.kind == "table_cell" and it.fillable and "tbl0:r1c0" in it.item_id
    )
    out = apply_drafts(src, [DraftItem(item_id=target.item_id, text="2024년")])
    new_doc = parse_hwpx(out)
    # Header label still present (r0c0 must still contain '연도')
    assert any(
        it.label == "연도" and it.kind == "table_cell" and "tbl0:r0c0" in it.item_id
        for it in new_doc.items
    ), "Header '연도' was overwritten"
    # The target value cell now has the draft text as its content
    new_target = next(it for it in new_doc.items if it.item_id == target.item_id)
    assert new_target.label == "2024년"


def test_apply_drafts_paragraph_routing_unaffected_by_tables():
    """Paragraph drafts (:pN) must target paragraphs OUTSIDE tables. Index N
    is the Nth non-empty top-level paragraph, ignoring paragraphs inside cells."""
    src = FIXTURE.read_bytes()
    doc = parse_hwpx(src)
    # First paragraph item (outside any table)
    target = next(it for it in doc.items if it.kind == "paragraph")
    out = apply_drafts(src, [DraftItem(item_id=target.item_id, text="새 본문")])
    new_doc = parse_hwpx(out)
    paragraph_labels = [it.label for it in new_doc.items if it.kind == "paragraph"]
    assert any("새 본문" in l for l in paragraph_labels)
    # Header cells unchanged
    assert any(
        it.label == "연도" for it in new_doc.items if it.kind == "table_cell"
    )


def test_apply_drafts_cell_pii_writes_placeholder():
    src = FIXTURE.read_bytes()
    doc = parse_hwpx(src)
    target = next(
        it for it in doc.items
        if it.kind == "table_cell" and it.fillable and "tbl0:r1c1" in it.item_id
    )
    out = apply_drafts(
        src,
        [DraftItem(item_id=target.item_id, text="민감정보", is_pii=True)],
    )
    new_doc = parse_hwpx(out)
    new_target = next(it for it in new_doc.items if it.item_id == target.item_id)
    assert new_target.label == "[본인 직접 입력]"


def test_apply_drafts_invalid_cell_id_is_no_op():
    src = FIXTURE.read_bytes()
    out = apply_drafts(
        src,
        [DraftItem(item_id="Contents/section0.xml:tbl9:r9c9", text="무시됨")],
    )
    doc = parse_hwpx(out)
    assert all("무시됨" not in (it.label or "") for it in doc.items)
