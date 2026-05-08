"""Repack .hwpx bytes with edited paragraph or table-cell text."""

import io
import re
import zipfile

from lxml import etree
from pydantic import BaseModel

NS_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HP = "{" + NS_HP + "}"

_PII_PLACEHOLDER = "[본인 직접 입력]"
_CELL_KEY_RE = re.compile(r"^tbl(\d+):r(\d+)c(\d+)$")


class DraftItem(BaseModel):
    item_id: str
    text: str
    is_pii: bool = False


def apply_drafts(src: bytes, drafts: list[DraftItem]) -> bytes:
    draft_map: dict[str, dict[str, DraftItem]] = {}
    for d in drafts:
        section, _, key = d.item_id.partition(":")
        draft_map.setdefault(section, {})[key] = d

    src_zip = zipfile.ZipFile(io.BytesIO(src), "r")
    out_buf = io.BytesIO()
    zout = zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED)

    zout.writestr(
        zipfile.ZipInfo("mimetype"),
        b"application/hwp+zip",
        compress_type=zipfile.ZIP_STORED,
    )

    for name in src_zip.namelist():
        if name == "mimetype":
            continue
        raw = src_zip.read(name)
        if (
            name.startswith("Contents/section")
            and name.endswith(".xml")
            and name in draft_map
        ):
            raw = _patch_section(raw, draft_map[name])
        zinfo = src_zip.getinfo(name)
        zout.writestr(zinfo.filename, raw)

    zout.close()
    src_zip.close()
    return out_buf.getvalue()


def _is_inside_table(p: etree._Element) -> bool:
    parent = p.getparent()
    while parent is not None:
        if parent.tag == f"{_HP}tbl":
            return True
        parent = parent.getparent()
    return False


def _patch_section(raw: bytes, section_drafts: dict[str, DraftItem]) -> bytes:
    tree = etree.fromstring(raw)

    paragraph_drafts: dict[int, DraftItem] = {}
    cell_drafts: dict[tuple[int, int, int], DraftItem] = {}
    for key, draft in section_drafts.items():
        if key.startswith("p"):
            try:
                paragraph_drafts[int(key[1:])] = draft
            except ValueError:
                continue
            continue
        m = _CELL_KEY_RE.match(key)
        if m:
            cell_drafts[(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = draft

    if paragraph_drafts:
        _apply_paragraph_drafts(tree, paragraph_drafts)
    if cell_drafts:
        _apply_cell_drafts(tree, cell_drafts)

    return etree.tostring(tree, encoding="UTF-8", xml_declaration=True)


def _apply_paragraph_drafts(tree, paragraph_drafts: dict[int, DraftItem]) -> None:
    """Index = Nth non-empty paragraph OUTSIDE any table."""
    non_empty_paragraphs: list[etree._Element] = []
    for p in tree.iter(f"{_HP}p"):
        if _is_inside_table(p):
            continue
        text = "".join(p.itertext()).strip()
        if text:
            non_empty_paragraphs.append(p)

    for idx, draft in paragraph_drafts.items():
        if idx >= len(non_empty_paragraphs):
            continue
        _write_text_into_paragraph(non_empty_paragraphs[idx], draft)


def _apply_cell_drafts(
    tree, cell_drafts: dict[tuple[int, int, int], DraftItem]
) -> None:
    tables = list(tree.iter(f"{_HP}tbl"))
    for (tidx, r, c), draft in cell_drafts.items():
        if tidx >= len(tables):
            continue
        rows = list(tables[tidx].iter(f"{_HP}tr"))
        if r >= len(rows):
            continue
        cols = list(rows[r].iter(f"{_HP}tc"))
        if c >= len(cols):
            continue
        ps = list(cols[c].iter(f"{_HP}p"))
        if not ps:
            continue
        _write_text_into_paragraph(ps[0], draft)


def _write_text_into_paragraph(paragraph, draft: DraftItem) -> None:
    t_elements = list(paragraph.iter(f"{_HP}t"))
    if not t_elements:
        return
    replacement = _PII_PLACEHOLDER if draft.is_pii else draft.text
    t_elements[0].text = replacement
    for t in t_elements[1:]:
        t.text = ""
