"""Repack .hwpx bytes with edited paragraph or table-cell text."""

import copy
import io
import re
import zipfile

from lxml import etree
from pydantic import BaseModel

NS_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HP = "{" + NS_HP + "}"

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
        # Editing the section invalidates any digital signature on the file,
        # so we drop signature manifests rather than ship a forged-looking copy.
        if name.startswith("META-INF/") and ("signature" in name.lower() or "rsa" in name.lower()):
            continue
        raw = src_zip.read(name)
        if name.startswith("Contents/section") and name.endswith(".xml") and name in draft_map:
            raw = _patch_section(raw, draft_map[name])
        # Preserve the original ZipInfo (compression method, external attrs, extras)
        # — Hangul rejects HWPX whose internal compression mode drifts from spec.
        src_info = src_zip.getinfo(name)
        out_info = zipfile.ZipInfo(filename=src_info.filename, date_time=src_info.date_time)
        out_info.compress_type = src_info.compress_type
        out_info.external_attr = src_info.external_attr
        out_info.internal_attr = src_info.internal_attr
        out_info.create_system = src_info.create_system
        zout.writestr(out_info, raw)

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
        _insert_draft_after_label(non_empty_paragraphs[idx], draft)


def _apply_cell_drafts(tree, cell_drafts: dict[tuple[int, int, int], DraftItem]) -> None:
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


def _direct_text_elements(paragraph) -> list:
    """<hp:t> descendants of paragraph that are NOT inside a nested table/cell."""
    out: list = []
    for t in paragraph.iter(f"{_HP}t"):
        anc = t.getparent()
        nested = False
        while anc is not None and anc is not paragraph:
            if anc.tag in (f"{_HP}tbl", f"{_HP}tc", f"{_HP}subList"):
                nested = True
                break
            anc = anc.getparent()
        if not nested:
            out.append(t)
    return out


def _strip_layout_cache(paragraph) -> None:
    """Remove <hp:linesegarray> children — Hangul recomputes them on open.

    Leaving the cache in place after a text change makes Hangul render the
    OLD layout (segments sized for the original text), which is what causes
    the "글자가 좁은 공간에 겹쳐서 써있는" symptom even when the text content
    is fine.
    """
    for lsa in list(paragraph.findall(f"{_HP}linesegarray")):
        paragraph.remove(lsa)


def _set_paragraph_text(paragraph, text: str) -> None:
    t_elements = _direct_text_elements(paragraph)
    if not t_elements:
        return
    t_elements[0].text = text
    for t in t_elements[1:]:
        t.text = ""
    _strip_layout_cache(paragraph)


def _write_text_into_paragraph(paragraph, draft: DraftItem) -> None:
    raw = draft.text
    lines = raw.split("\n") if raw else [""]

    _set_paragraph_text(paragraph, lines[0])

    if len(lines) <= 1:
        return

    # Each subsequent line becomes its own <hp:p> sibling — clones the original
    # paragraph so paraPrIDRef / charPrIDRef and other formatting carry over.
    parent = paragraph.getparent()
    if parent is None:
        return
    siblings = list(parent)
    my_idx = siblings.index(paragraph)
    for offset, line in enumerate(lines[1:], start=1):
        cloned = copy.deepcopy(paragraph)
        _set_paragraph_text(cloned, line)
        parent.insert(my_idx + offset, cloned)


def _insert_draft_after_label(label_paragraph, draft: DraftItem) -> None:
    """Top-level paragraph items use the paragraph's own text as their label,
    so writing the draft into that paragraph would erase the label. Mirror the
    table-cell rule (write to the adjacent slot, never overwrite the label) by
    leaving the label paragraph intact and inserting the draft as new sibling
    paragraph(s) immediately after it — one per "\\n"-separated line."""
    raw = draft.text
    lines = raw.split("\n") if raw else [""]

    parent = label_paragraph.getparent()
    if parent is None:
        return
    base_idx = list(parent).index(label_paragraph)
    for offset, line in enumerate(lines, start=1):
        cloned = copy.deepcopy(label_paragraph)
        _set_paragraph_text(cloned, line)
        parent.insert(base_idx + offset, cloned)
