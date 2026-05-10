"""Tests for pii.form_detector — flags Items with PII-sensitive labels.

flag_pii_items(doc: FormDoc) -> FormDoc
  Sets item.is_pii = True for items whose label contains PII keywords.
  Returns updated FormDoc; items without PII labels are left as-is.
"""

from backend.app.hwpx.models import FormDoc, Item
from backend.app.pii.form_detector import flag_pii_items


def _make_doc(*items: Item) -> FormDoc:
    return FormDoc(sections=["섹션1"], items=list(items), tables=[], placeholders=[])


def _item(label: str, item_id: str = "i1") -> Item:
    return Item(
        item_id=item_id,
        label=label,
        section="섹션1",
        kind="paragraph",
        xml_xpath=f"/p[{item_id}]",
    )


# ── 성명 / 이름 (name) ────────────────────────────────────────────────────────


def test_flag_pii_item_성명():
    doc = _make_doc(_item("성명"))
    assert flag_pii_items(doc).items[0].is_pii is True


def test_flag_pii_item_이름():
    doc = _make_doc(_item("이름"))
    assert flag_pii_items(doc).items[0].is_pii is True


def test_flag_pii_item_label_with_성명_prefix():
    doc = _make_doc(_item("신청자 성명"))
    assert flag_pii_items(doc).items[0].is_pii is True


# ── 주민등록번호 (resident registration) ─────────────────────────────────────


def test_flag_pii_item_주민등록번호():
    doc = _make_doc(_item("주민등록번호"))
    assert flag_pii_items(doc).items[0].is_pii is True


def test_flag_pii_item_주민번호():
    doc = _make_doc(_item("주민번호"))
    assert flag_pii_items(doc).items[0].is_pii is True


# ── 연락처 / 전화번호 (phone) ─────────────────────────────────────────────────


def test_flag_pii_item_연락처():
    doc = _make_doc(_item("연락처"))
    assert flag_pii_items(doc).items[0].is_pii is True


def test_flag_pii_item_전화번호():
    doc = _make_doc(_item("전화번호"))
    assert flag_pii_items(doc).items[0].is_pii is True


def test_flag_pii_item_전화():
    doc = _make_doc(_item("전화"))
    assert flag_pii_items(doc).items[0].is_pii is True


# ── 주소 (address) ────────────────────────────────────────────────────────────


def test_flag_pii_item_주소():
    doc = _make_doc(_item("주소"))
    assert flag_pii_items(doc).items[0].is_pii is True


def test_flag_pii_item_거주지주소():
    doc = _make_doc(_item("거주지주소"))
    assert flag_pii_items(doc).items[0].is_pii is True


# ── 계좌 (bank account) ───────────────────────────────────────────────────────


def test_flag_pii_item_계좌번호():
    doc = _make_doc(_item("계좌번호"))
    assert flag_pii_items(doc).items[0].is_pii is True


def test_flag_pii_item_계좌():
    doc = _make_doc(_item("계좌"))
    assert flag_pii_items(doc).items[0].is_pii is True


# ── 학번 / 사번 (ID numbers) ─────────────────────────────────────────────────


def test_flag_pii_item_학번():
    doc = _make_doc(_item("학번"))
    assert flag_pii_items(doc).items[0].is_pii is True


def test_flag_pii_item_사번():
    doc = _make_doc(_item("사번"))
    assert flag_pii_items(doc).items[0].is_pii is True


def test_flag_pii_item_직원번호():
    doc = _make_doc(_item("직원번호"))
    assert flag_pii_items(doc).items[0].is_pii is True


# ── 이메일 (email) ────────────────────────────────────────────────────────────


def test_flag_pii_item_이메일():
    doc = _make_doc(_item("이메일"))
    assert flag_pii_items(doc).items[0].is_pii is True


def test_flag_pii_item_이메일주소():
    doc = _make_doc(_item("이메일주소"))
    assert flag_pii_items(doc).items[0].is_pii is True


# ── 카드번호 / 외국인등록번호 ─────────────────────────────────────────────────


def test_flag_pii_item_카드번호():
    doc = _make_doc(_item("카드번호"))
    assert flag_pii_items(doc).items[0].is_pii is True


def test_flag_pii_item_외국인등록번호():
    doc = _make_doc(_item("외국인등록번호"))
    assert flag_pii_items(doc).items[0].is_pii is True


# ── 비PII 항목 (non-PII items must not be flagged) ───────────────────────────


def test_no_flag_연구의필요성():
    doc = _make_doc(_item("연구의 필요성"))
    assert flag_pii_items(doc).items[0].is_pii is False


def test_no_flag_연구목표():
    doc = _make_doc(_item("연구 목표"))
    assert flag_pii_items(doc).items[0].is_pii is False


def test_no_flag_소속기관():
    doc = _make_doc(_item("소속기관"))
    assert flag_pii_items(doc).items[0].is_pii is False


def test_no_flag_연구기간():
    doc = _make_doc(_item("연구기간"))
    assert flag_pii_items(doc).items[0].is_pii is False


# ── 복합 (mixed items — only PII ones flagged) ────────────────────────────────


def test_flag_only_pii_items_in_mixed_doc():
    items = [
        _item("성명", "i1"),
        _item("연구 목표", "i2"),
        _item("계좌번호", "i3"),
        _item("연구의 필요성", "i4"),
        _item("주민등록번호", "i5"),
    ]
    doc = _make_doc(*items)
    result = flag_pii_items(doc)
    flags = {it.item_id: it.is_pii for it in result.items}
    assert flags["i1"] is True
    assert flags["i2"] is False
    assert flags["i3"] is True
    assert flags["i4"] is False
    assert flags["i5"] is True


# ── 불변성 (original doc items are not mutated) ───────────────────────────────


def test_original_doc_not_mutated():
    item = _item("성명")
    doc = _make_doc(item)
    result = flag_pii_items(doc)
    assert result.items[0].is_pii is True
    # Original item should not be mutated (FormDoc uses model_copy internally)
    assert item.is_pii is False


# ── 빈 FormDoc (empty FormDoc handled gracefully) ─────────────────────────────


def test_empty_doc():
    doc = FormDoc(sections=[], items=[], tables=[], placeholders=[])
    result = flag_pii_items(doc)
    assert result.items == []
