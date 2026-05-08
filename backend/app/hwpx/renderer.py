"""Repack .hwpx bytes with edited paragraph text."""

import io
import zipfile

from lxml import etree
from pydantic import BaseModel

NS_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HP = "{" + NS_HP + "}"

_PII_PLACEHOLDER = "[본인 직접 입력]"


class DraftItem(BaseModel):
    item_id: str
    text: str
    is_pii: bool = False


def apply_drafts(src: bytes, drafts: list[DraftItem]) -> bytes:
    # Hard rule: is_pii=True drafts always render as PII placeholder, never user text.
    draft_map: dict[str, dict[str, DraftItem]] = {}
    for d in drafts:
        section, _, p_key = d.item_id.partition(":")
        draft_map.setdefault(section, {})[p_key] = d

    src_zip = zipfile.ZipFile(io.BytesIO(src), "r")
    out_buf = io.BytesIO()
    zout = zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED)

    zout.writestr(
        zipfile.ZipInfo("mimetype"), b"application/hwp+zip", compress_type=zipfile.ZIP_STORED
    )

    for name in src_zip.namelist():
        if name == "mimetype":
            continue
        raw = src_zip.read(name)
        if name.startswith("Contents/section") and name.endswith(".xml") and name in draft_map:
            raw = _patch_section(raw, draft_map[name])
        zinfo = src_zip.getinfo(name)
        zout.writestr(zinfo.filename, raw)

    zout.close()
    src_zip.close()
    return out_buf.getvalue()


def _patch_section(raw: bytes, section_drafts: dict[str, DraftItem]) -> bytes:
    tree = etree.fromstring(raw)

    non_empty_paragraphs: list[etree._Element] = []
    for p in tree.iter(f"{_HP}p"):
        text = "".join(p.itertext()).strip()
        if text:
            non_empty_paragraphs.append(p)

    for p_key, draft in section_drafts.items():
        if not p_key.startswith("p"):
            continue
        try:
            idx = int(p_key[1:])
        except ValueError:
            continue
        if idx >= len(non_empty_paragraphs):
            continue

        paragraph = non_empty_paragraphs[idx]
        t_elements = list(paragraph.iter(f"{_HP}t"))
        if not t_elements:
            continue

        replacement = _PII_PLACEHOLDER if draft.is_pii else draft.text

        t_elements[0].text = replacement
        for t in t_elements[1:]:
            t.text = ""

    return etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
