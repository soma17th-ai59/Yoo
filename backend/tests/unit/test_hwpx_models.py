from backend.app.hwpx.models import FormDoc, Item


def test_formdoc_round_trip_dict():
    item = Item(
        item_id="i1",
        label="연구의 필요성",
        section="연구개요",
        expected_chars=600,
        kind="paragraph",
        xml_xpath="//hp:p[3]",
    )
    doc = FormDoc(sections=["연구개요"], items=[item], tables=[], placeholders=[])
    assert doc.items[0].kind == "paragraph"
    assert doc.model_dump()["items"][0]["item_id"] == "i1"
