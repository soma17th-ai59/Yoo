"""Parse .hwpx (ZIP+XML) bytes into a FormDoc."""

import io
import zipfile

from lxml import etree

from .models import FormDoc, Item, Table

NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
}

_HP = "{" + NS["hp"] + "}"


def _cell_text(tc: etree._Element) -> str:
    """Joined text content of a table cell."""
    return "".join(tc.itertext()).strip()


def _label_for_cell(grid: list[list[str]], r: int, c: int) -> str:
    """Heuristic for empty-cell labels:
    1. nearest non-empty cell ABOVE in same column (header-row pattern is the
       most common shape; users filling row N+1 should not start labelling
       its right-side empties with row N+1's own filled-in text)
    2. nearest non-empty neighbor on the LEFT in same row (2-col label/value
       pairs with no header row above)
    3. fallback '(표 셀 r{R}c{C})'
    """
    for rr in range(r - 1, -1, -1):
        if c < len(grid[rr]) and grid[rr][c]:
            return grid[rr][c]
    for cc in range(c - 1, -1, -1):
        if grid[r][cc]:
            return grid[r][cc]
    return f"(표 셀 r{r}c{c})"


def _is_inside_table(p: etree._Element) -> bool:
    """Return True if <hp:p> has a <hp:tbl> ancestor."""
    node = p.getparent()
    while node is not None:
        if node.tag == f"{_HP}tbl":
            return True
        node = node.getparent()
    return False


def _emit_table_items(
    tbl: etree._Element,
    section_name: str,
    tidx: int,
) -> tuple[list[Item], Table]:
    """Walk a table cell-by-cell. Returns (items, table_meta)."""
    rows = list(tbl.iter(f"{_HP}tr"))
    table_meta = Table(
        table_id=f"{section_name}:tbl{tidx}",
        headers=[],
        row_count=0,
        xml_xpath=tbl.getroottree().getpath(tbl),
    )

    if not rows:
        return [], table_meta

    grid: list[list[str]] = []
    cell_elements: list[list[etree._Element]] = []
    for tr in rows:
        cols = list(tr.iter(f"{_HP}tc"))
        grid.append([_cell_text(tc) for tc in cols])
        cell_elements.append(cols)

    def _has_empty_neighbor(r: int, c: int) -> bool:
        for cc in range(c + 1, len(grid[r])):
            if not grid[r][cc]:
                return True
        for rr in range(r + 1, len(grid)):
            if c < len(grid[rr]) and not grid[rr][c]:
                return True
        return False

    items: list[Item] = []
    for r, row in enumerate(grid):
        for c, txt in enumerate(row):
            cell_id = f"{section_name}:tbl{tidx}:r{r}c{c}"
            tc_elem = cell_elements[r][c]
            xpath = tc_elem.getroottree().getpath(tc_elem)
            if not txt:
                items.append(
                    Item(
                        item_id=cell_id,
                        label=_label_for_cell(grid, r, c),
                        section=section_name,
                        kind="table_cell",
                        xml_xpath=xpath,
                        fillable=True,
                    )
                )
            else:
                fillable = not _has_empty_neighbor(r, c)
                items.append(
                    Item(
                        item_id=cell_id,
                        label=txt,
                        section=section_name,
                        kind="table_cell",
                        xml_xpath=xpath,
                        fillable=fillable,
                    )
                )

    headers = grid[0] if grid else []
    table_meta = Table(
        table_id=f"{section_name}:tbl{tidx}",
        headers=headers,
        row_count=len(rows),
        xml_xpath=tbl.getroottree().getpath(tbl),
    )
    return items, table_meta


def parse_hwpx(data: bytes) -> FormDoc:
    items: list[Item] = []
    tables: list[Table] = []
    section_names: list[str] = []

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            section_names = sorted(n for n in zf.namelist() if n.startswith("Contents/section"))
            for name in section_names:
                raw = zf.read(name)
                tree = etree.fromstring(raw)
                root_tree = tree.getroottree()

                for tidx, tbl in enumerate(tree.iter(f"{_HP}tbl")):
                    cell_items, table_meta = _emit_table_items(tbl, name, tidx)
                    items.extend(cell_items)
                    tables.append(table_meta)

                p_idx = 0
                for p in tree.iter(f"{_HP}p"):
                    if _is_inside_table(p):
                        continue
                    # HWPX wraps tables inside <hp:p>. Such a wrapper paragraph
                    # would itertext() out every cell's text, mislabel the
                    # paragraph, and — worse — let the renderer overwrite all
                    # nested table cells when it writes a draft here. The cells
                    # are enumerated separately via _emit_table_items, so skip.
                    if p.find(f".//{_HP}tbl") is not None:
                        continue
                    text = "".join(p.itertext()).strip()
                    if not text:
                        continue
                    items.append(
                        Item(
                            item_id=f"{name}:p{p_idx}",
                            label=text[:40],
                            section=name,
                            kind="paragraph",
                            xml_xpath=root_tree.getpath(p),
                            fillable=True,
                        )
                    )
                    p_idx += 1
    except (zipfile.BadZipFile, RuntimeError, etree.XMLSyntaxError) as e:
        raise ValueError("HWPX file appears to be encrypted or corrupted") from e

    sections = section_names if section_names else ["main"]
    return FormDoc(sections=sections, items=items, tables=tables, placeholders=[])
