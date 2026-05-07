"""Dump readable text from a .hwpx file.

Usage:
  uv run python tools/dump_hwpx.py <path.hwpx>          # text only
  uv run python tools/dump_hwpx.py <path.hwpx> --tree   # item id + label + PII flag
  uv run python tools/dump_hwpx.py <path.hwpx> --xml    # raw section XML
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

from lxml import etree

from backend.app.hwpx.parser import parse_hwpx
from backend.app.pii.form_detector import flag_pii_items

NS_P = "{http://www.hancom.co.kr/hwpml/2011/paragraph}p"


def _ensure_utf8_stdout() -> None:
    """On Windows + cp949 console, force UTF-8 so Korean prints don't crash."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def dump_text(path: Path) -> None:
    with zipfile.ZipFile(path) as z:
        sections = sorted(n for n in z.namelist() if n.startswith("Contents/section"))
        for name in sections:
            tree = etree.fromstring(z.read(name))
            for p in tree.iter(NS_P):
                text = "".join(p.itertext()).strip()
                if text:
                    print(text)


def dump_tree(path: Path) -> None:
    doc = flag_pii_items(parse_hwpx(path.read_bytes()))
    print(f"== {path.name} | items={len(doc.items)} tables={len(doc.tables)} ==")
    for it in doc.items:
        pii = "  [PII]" if it.is_pii else ""
        print(f"  {it.item_id:<32}  {it.label}{pii}")
    if doc.tables:
        print("-- tables --")
        for t in doc.tables:
            print(f"  {t.table_id:<32}  headers={t.headers}  rows={t.row_count}")


def dump_xml(path: Path) -> None:
    with zipfile.ZipFile(path) as z:
        for name in sorted(z.namelist()):
            print(f"### {name}")
            if name.endswith(".xml") or name.endswith(".hpf"):
                print(z.read(name).decode("utf-8"))
            else:
                print(f"<binary, {len(z.read(name))} bytes>")
            print()


def main() -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--tree", action="store_true", help="show item IDs + PII flags")
    parser.add_argument("--xml", action="store_true", help="dump raw XML for every entry")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"파일을 찾을 수 없습니다: {args.path}", file=sys.stderr)
        return 1

    if args.xml:
        dump_xml(args.path)
    elif args.tree:
        dump_tree(args.path)
    else:
        dump_text(args.path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
