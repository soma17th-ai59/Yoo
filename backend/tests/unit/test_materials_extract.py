from pathlib import Path

import pytest

from backend.app.materials.extract import extract_text

FIXTURES = Path("backend/tests/fixtures/materials")
FORMS = Path("backend/tests/fixtures/forms")


def test_extract_txt_korean_utf8():
    path = FIXTURES / "notes.txt"
    text = extract_text(path)
    assert text == path.read_text(encoding="utf-8")
    assert "연구 노트" in text
    assert "가설" in text


def test_extract_docx_paragraphs_and_tables():
    path = FIXTURES / "plan.docx"
    text = extract_text(path)
    assert "연구 계획" in text
    assert "1년차에는 데이터셋 구축에 집중한다." in text
    assert "단계" in text
    assert "목표" in text
    assert "1단계" in text
    assert "데이터 수집" in text


def test_extract_pdf_korean():
    path = FIXTURES / "cv.pdf"
    text = extract_text(path)
    assert "김연구" in text or "머신러닝" in text


def test_extract_hwpx_reuses_parser():
    path = FORMS / "sample_form.hwpx"
    text = extract_text(path)
    assert text.strip()
    assert "연구의 필요성" in text


def test_extract_unsupported_format_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        extract_text(Path("report.bin"))


def test_extract_corrupt_pdf_raises_value_error(tmp_path):
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"not a pdf at all garbage bytes")
    with pytest.raises(ValueError):
        extract_text(bad_pdf)


def test_extract_txt_accepts_string_path():
    path = str(FIXTURES / "notes.txt")
    text = extract_text(path)
    assert "연구 노트" in text


def test_extract_docx_returns_string():
    text = extract_text(FIXTURES / "plan.docx")
    assert isinstance(text, str)


def test_extract_pdf_returns_string():
    text = extract_text(FIXTURES / "cv.pdf")
    assert isinstance(text, str)
