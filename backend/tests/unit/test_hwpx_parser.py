from pathlib import Path

import pytest

from backend.app.hwpx.parser import parse_hwpx

FIXTURE = Path("backend/tests/fixtures/forms/sample_form.hwpx")


def test_parse_extracts_items_and_table():
    doc = parse_hwpx(FIXTURE.read_bytes())
    assert len(doc.items) >= 2
    assert any(i.kind == "paragraph" for i in doc.items)
    assert len(doc.tables) == 1
    assert doc.tables[0].headers  # at least one header detected


def test_sections_match_actual_section_paths():
    """Regression: parser used to hardcode sections=['main'], breaking the
    UI form-tree expander which groups items by `item.section`. Now sections
    come from the actual ZIP entries so item.section ∈ doc.sections."""
    doc = parse_hwpx(FIXTURE.read_bytes())
    assert "Contents/section0.xml" in doc.sections
    assert all(it.section in doc.sections for it in doc.items)


def test_parse_paragraph_labels_are_korean():
    doc = parse_hwpx(FIXTURE.read_bytes())
    labels = [i.label for i in doc.items if i.kind == "paragraph"]
    assert "연구의 필요성" in labels
    assert "예상 결과" in labels


def test_parse_table_structure():
    doc = parse_hwpx(FIXTURE.read_bytes())
    tbl = doc.tables[0]
    assert tbl.row_count == 2
    assert tbl.headers == ["연도", "내용", "비고"]
    assert tbl.xml_xpath  # non-empty XPath


def test_parse_item_has_xpath():
    doc = parse_hwpx(FIXTURE.read_bytes())
    for item in doc.items:
        assert item.xml_xpath, f"Item {item.item_id} missing xml_xpath"


# Edge case: empty paragraphs are skipped
def test_empty_paragraphs_skipped():
    import io
    import zipfile

    section_xml = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:p><hp:run><hp:t>real text</hp:t></hp:run></hp:p>
  <hp:p><hp:run><hp:t></hp:t></hp:run></hp:p>
  <hp:p/>
</hs:sec>
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, b"application/hwp+zip")
        z.writestr("Contents/section0.xml", section_xml)
    doc = parse_hwpx(buf.getvalue())
    assert len(doc.items) == 1
    assert doc.items[0].label == "real text"


# Edge case: table with a merged cell (colSpan attribute) must not crash
def test_merged_cell_table_does_not_crash():
    import io
    import zipfile

    section_xml = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:tbl>
    <hp:tr>
      <hp:tc colSpan="2"><hp:subList><hp:p><hp:run><hp:t>merged</hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>col3</hp:t></hp:run></hp:p></hp:subList></hp:tc>
    </hp:tr>
    <hp:tr>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>a</hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>b</hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>c</hp:t></hp:run></hp:p></hp:subList></hp:tc>
    </hp:tr>
  </hp:tbl>
</hs:sec>
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, b"application/hwp+zip")
        z.writestr("Contents/section0.xml", section_xml)
    doc = parse_hwpx(buf.getvalue())
    assert len(doc.tables) == 1
    assert doc.tables[0].headers == ["merged", "col3"]
    assert doc.tables[0].row_count == 2


# Edge case: malformed/encrypted input raises ValueError
def test_bad_input_raises_value_error():
    with pytest.raises(ValueError, match="encrypted or corrupted"):
        parse_hwpx(b"not a zip")


# Edge case: ZIP whose section XML is malformed raises ValueError
def test_malformed_xml_raises_value_error():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, b"application/hwp+zip")
        z.writestr("Contents/section0.xml", b"<not valid xml")
    with pytest.raises(ValueError, match="encrypted or corrupted"):
        parse_hwpx(buf.getvalue())


def _section_with_2col_label_value_table() -> bytes:
    import io
    import zipfile

    section_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:tbl>
    <hp:tr>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>자기소개</hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t></hp:t></hp:run></hp:p></hp:subList></hp:tc>
    </hp:tr>
    <hp:tr>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>연구계획</hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t></hp:t></hp:run></hp:p></hp:subList></hp:tc>
    </hp:tr>
  </hp:tbl>
</hs:sec>
""".encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, b"application/hwp+zip")
        z.writestr("Contents/section0.xml", section_xml)
    return buf.getvalue()


class TestTwoColLabelValuePairs:
    def test_value_cells_are_fillable_table_cells(self):
        doc = parse_hwpx(_section_with_2col_label_value_table())
        value_cells = [it for it in doc.items if it.fillable and it.kind == "table_cell"]
        assert len(value_cells) == 2
        assert {it.label for it in value_cells} == {"자기소개", "연구계획"}

    def test_label_cells_are_non_fillable_table_cells(self):
        doc = parse_hwpx(_section_with_2col_label_value_table())
        label_cells = [it for it in doc.items if not it.fillable and it.kind == "table_cell"]
        assert len(label_cells) == 2
        assert {it.label for it in label_cells} == {"자기소개", "연구계획"}

    def test_value_cell_item_id_encodes_table_row_col(self):
        doc = parse_hwpx(_section_with_2col_label_value_table())
        ids = [it.item_id for it in doc.items if it.fillable and it.kind == "table_cell"]
        assert any("tbl0:r0c1" in i for i in ids)
        assert any("tbl0:r1c1" in i for i in ids)

    def test_no_paragraph_items_inside_table(self):
        doc = parse_hwpx(_section_with_2col_label_value_table())
        paragraph_items = [it for it in doc.items if it.kind == "paragraph"]
        assert paragraph_items == []


class TestHeaderRowPattern:
    def test_header_row_then_empty_data_row_emits_value_cells(self):
        doc = parse_hwpx(FIXTURE.read_bytes())
        header_cells = [it for it in doc.items if it.kind == "table_cell" and not it.fillable]
        assert {it.label for it in header_cells} == {"연도", "내용", "비고"}
        data_cells = [it for it in doc.items if it.kind == "table_cell" and it.fillable]
        assert len(data_cells) == 3
        assert {it.label for it in data_cells} == {"연도", "내용", "비고"}
