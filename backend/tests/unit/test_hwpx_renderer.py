import io
import zipfile
from pathlib import Path

from backend.app.hwpx.parser import parse_hwpx
from backend.app.hwpx.renderer import DraftItem, apply_drafts

FIXTURE = Path("backend/tests/fixtures/forms/sample_form.hwpx")


def test_apply_drafts_inserts_text():
    src = FIXTURE.read_bytes()
    doc = parse_hwpx(src)
    target = doc.items[0]
    out = apply_drafts(src, [DraftItem(item_id=target.item_id, text="새 본문 내용")])
    new_doc = parse_hwpx(out)
    assert any("새 본문 내용" in i.label for i in new_doc.items)


def test_apply_drafts_pii_uses_placeholder():
    src = FIXTURE.read_bytes()
    doc = parse_hwpx(src)
    target = doc.items[0]
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
    out = apply_drafts(src, [DraftItem(item_id=doc.items[0].item_id, text="변경")])

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
