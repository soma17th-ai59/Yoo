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

                p_idx = 0
                for p in tree.iter(f"{_HP}p"):
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
                        )
                    )
                    p_idx += 1

                for tidx, tbl in enumerate(tree.iter(f"{_HP}tbl")):
                    rows = list(tbl.iter(f"{_HP}tr"))
                    headers = (
                        ["".join(c.itertext()).strip() for c in rows[0].iter(f"{_HP}tc")]
                        if rows
                        else []
                    )
                    tables.append(
                        Table(
                            table_id=f"{name}:tbl{tidx}",
                            headers=headers,
                            row_count=len(rows),
                            xml_xpath=root_tree.getpath(tbl),
                        )
                    )
    except (zipfile.BadZipFile, RuntimeError, etree.XMLSyntaxError) as e:
        raise ValueError("HWPX file appears to be encrypted or corrupted") from e

    sections = section_names if section_names else ["main"]
    return FormDoc(sections=sections, items=items, tables=tables, placeholders=[])
