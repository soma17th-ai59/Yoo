# 표 셀 단위 fill — Implementation Plan

**Goal:** 표(`hp:tbl`)의 빈 값 셀을 1셀당 1개 `Item`으로 노출해 라벨 셀이 덮어써지지 않게 하고, Generator가 빈 셀에 정확히 채울 수 있게 한다.

**Architecture:** Parser는 표 내부 `<hp:p>`를 paragraph item으로 emit하지 않고, 표를 셀 단위로 순회해 `kind="table_cell"` Item을 만든다. 빈 셀은 `fillable=True`, 텍스트가 있고 빈 이웃을 가진 라벨 셀은 `fillable=False`. Renderer는 `item_id`의 prefix로 paragraph 라우팅과 cell 라우팅을 분기한다.

**Tech stack:** Python 3.11 · lxml · Pydantic v2 · pytest. 변경 없는 외부 의존.

**Branch:** `fix/table-cell-fill` (worktree at `D:/Projects/hwp-editor/.worktrees/table-cell-fill/`).

---

## Design summary (already approved)

- `Item.fillable: bool = True` 필드 추가.
- `item_id` 형식:
  - paragraph: `<section>:p<idx>` (기존)
  - table cell (신규): `<section>:tbl<tidx>:r<row>c<col>`
- 라벨 휴리스틱 (빈 셀):
  1. 같은 행 왼쪽으로 가장 가까운 non-empty 셀 텍스트
  2. 같은 열 위쪽으로 가장 가까운 non-empty 셀 텍스트
  3. fallback: `"(표 셀 r{R}c{C})"`
- 라벨 셀 (텍스트 있고 빈 이웃 존재): `fillable=False`로 emit (UI에 보이지만 Generator skip).
- 값-있는 셀 (텍스트 있고 빈 이웃 없음): `fillable=True` 그대로 (사용자가 수정 가능).
- 표 외부 paragraph는 그대로 `kind="paragraph"`, `fillable=True`.
- Out of scope (V1.5+): merged cell의 colSpan/rowSpan, 중첩 테이블, 행 동적 추가.

---

## File structure

| 파일 | 변경 |
|---|---|
| `backend/app/hwpx/models.py` | `Item.fillable: bool = True` 추가 |
| `backend/app/hwpx/parser.py` | 표 처리 분기 — 표 내 `hp:p`는 paragraph item으로 emit 안 하고 셀 단위로 새 헬퍼 호출 |
| `backend/app/hwpx/renderer.py` | `apply_drafts`에서 `item_id` prefix 분기. 셀 텍스트 주입 헬퍼 추가 |
| `backend/app/graph/nodes/planner.py` | `if not item.fillable: skip` |
| `backend/app/graph/nodes/generator.py` | 동일하게 skip |
| `backend/tests/unit/test_hwpx_parser.py` | 기존 어서션 갱신 (헤더는 더 이상 paragraph 아님) + 표 셀 케이스 단위 테스트 추가 |
| `backend/tests/unit/test_hwpx_renderer.py` | 셀 라우팅 단위 테스트 추가 |
| `backend/tests/unit/test_node_planner.py` | fillable skip 어서션 |
| `backend/tests/unit/test_node_generator.py` | 동일 |

---

## Bundle 1 — `Item.fillable` + parser cell emission

**Files:**
- Modify: `backend/app/hwpx/models.py`
- Modify: `backend/app/hwpx/parser.py`
- Modify: `backend/tests/unit/test_hwpx_parser.py`

### Step 1: TDD — 새 단위 테스트 추가 (실패 상태)

`backend/tests/unit/test_hwpx_parser.py` 끝에 추가:

```python
def _section_with_2col_label_value_table() -> bytes:
    import io
    import zipfile

    section_xml = b"""\
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
"""
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
        # 값 셀 (오른쪽 빈 칸 2개)이 fillable table_cell로 등장
        value_cells = [it for it in doc.items if it.fillable and it.kind == "table_cell"]
        assert len(value_cells) == 2
        labels = {it.label for it in value_cells}
        assert labels == {"자기소개", "연구계획"}

    def test_label_cells_are_non_fillable_table_cells(self):
        doc = parse_hwpx(_section_with_2col_label_value_table())
        label_cells = [it for it in doc.items if not it.fillable and it.kind == "table_cell"]
        assert len(label_cells) == 2
        assert {it.label for it in label_cells} == {"자기소개", "연구계획"}

    def test_value_cell_item_id_encodes_table_row_col(self):
        doc = parse_hwpx(_section_with_2col_label_value_table())
        ids = [it.item_id for it in doc.items if it.fillable and it.kind == "table_cell"]
        # 두 값 셀: r0c1, r1c1
        assert any("tbl0:r0c1" in i for i in ids)
        assert any("tbl0:r1c1" in i for i in ids)

    def test_no_paragraph_items_inside_table(self):
        doc = parse_hwpx(_section_with_2col_label_value_table())
        # 표 내부 paragraph는 paragraph item으로 emit되지 않음
        paragraph_items = [it for it in doc.items if it.kind == "paragraph"]
        assert paragraph_items == []


class TestHeaderRowPattern:
    def test_header_row_then_empty_data_row_emits_value_cells(self):
        # sample_form 픽스처가 정확히 이 패턴 (연도/내용/비고 + 빈 행)
        from pathlib import Path
        doc = parse_hwpx(Path("backend/tests/fixtures/forms/sample_form.hwpx").read_bytes())
        # 헤더 셀들은 fillable=False
        header_cells = [it for it in doc.items
                        if it.kind == "table_cell" and not it.fillable]
        assert {it.label for it in header_cells} == {"연도", "내용", "비고"}
        # 데이터 행 빈 셀들은 fillable=True, 라벨은 헤더 따라감
        data_cells = [it for it in doc.items
                      if it.kind == "table_cell" and it.fillable]
        assert len(data_cells) == 3
        assert {it.label for it in data_cells} == {"연도", "내용", "비고"}
```

기존 어서션도 갱신:

- `test_parse_paragraph_labels_are_korean`은 그대로 유지 (`연구의 필요성`, `예상 결과`는 표 외부 paragraph라 paragraph kind 유지).
- 픽스처 기반의 어떤 어서션이 "헤더가 paragraph로 등장"을 가정한다면 (`test_parse_extracts_items_and_table` 등) 표 외부 paragraph 2개만 paragraph kind이고 표 셀은 table_cell로 분리됨을 반영하도록 갱신.

### Step 2: 실패 확인

```bash
cd D:/Projects/hwp-editor/.worktrees/table-cell-fill
uv run pytest backend/tests/unit/test_hwpx_parser.py -v
```

Expected: 새 클래스 4개 테스트는 실패 (`Item.fillable` 없음 또는 `kind="table_cell"` item이 없음).

### Step 3: 모델 갱신

`backend/app/hwpx/models.py`:

```python
class Item(BaseModel):
    item_id: str
    label: str
    section: str
    expected_chars: int | None = None
    kind: ItemKind
    xml_xpath: str
    is_pii: bool = False
    fillable: bool = True
```

### Step 4: 파서 재작성

`backend/app/hwpx/parser.py` 전체를 다음 형태로:

```python
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
    """Heuristic: nearest non-empty neighbor on the LEFT in same row,
    else nearest non-empty cell ABOVE in same column,
    else fallback '(표 셀 r{R}c{C})'."""
    for cc in range(c - 1, -1, -1):
        if grid[r][cc]:
            return grid[r][cc]
    for rr in range(r - 1, -1, -1):
        if grid[rr][c]:
            return grid[rr][c]
    return f"(표 셀 r{r}c{c})"


def _emit_table_items(
    tbl: etree._Element,
    section_name: str,
    tidx: int,
    paragraphs_inside_table: set[int],
) -> tuple[list[Item], Table]:
    """Walk a table and emit Item per cell (label cell -> fillable=False,
    empty value cell -> fillable=True with heuristic label, populated cell ->
    fillable=True with own text as label).

    Returns (items, table_meta). Also adds the id() of every <hp:p> inside
    the table to paragraphs_inside_table so the top-level paragraph loop
    can skip them.
    """
    rows = list(tbl.iter(f"{_HP}tr"))
    if not rows:
        return [], Table(
            table_id=f"{section_name}:tbl{tidx}",
            headers=[],
            row_count=0,
            xml_xpath=tbl.getroottree().getpath(tbl),
        )

    # Build a row-major text grid (colSpan ignored for V1).
    grid: list[list[str]] = []
    cell_elements: list[list[etree._Element]] = []
    for tr in rows:
        cols = list(tr.iter(f"{_HP}tc"))
        grid.append([_cell_text(tc) for tc in cols])
        cell_elements.append(cols)

    # Track every <hp:p> inside this table so the top-level paragraph loop
    # doesn't double-emit them.
    for p in tbl.iter(f"{_HP}p"):
        paragraphs_inside_table.add(id(p))

    # Has-empty-neighbor check: a cell with text qualifies as a "label cell"
    # if there is at least one empty cell to its right in the same row OR
    # below it in the same column.
    def _has_empty_neighbor(r: int, c: int) -> bool:
        for cc in range(c + 1, len(grid[r])):
            if not grid[r][cc]:
                return True
        for rr in range(r + 1, len(grid)):
            if c < len(grid[rr]) and not grid[rr][c]:
                return True
        return False

    items: list[Item] = []
    headers = grid[0] if grid else []
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
            section_names = sorted(
                n for n in zf.namelist() if n.startswith("Contents/section")
            )
            for name in section_names:
                raw = zf.read(name)
                tree = etree.fromstring(raw)
                root_tree = tree.getroottree()

                paragraphs_inside_table: set[int] = set()

                for tidx, tbl in enumerate(tree.iter(f"{_HP}tbl")):
                    cell_items, table_meta = _emit_table_items(
                        tbl, name, tidx, paragraphs_inside_table
                    )
                    items.extend(cell_items)
                    tables.append(table_meta)

                p_idx = 0
                for p in tree.iter(f"{_HP}p"):
                    if id(p) in paragraphs_inside_table:
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
```

### Step 5: 단위 테스트 통과 확인 + 영향 받는 테스트 갱신

```bash
uv run pytest backend/tests/unit/test_hwpx_parser.py -v
```

기존 어서션 중 표 안 텍스트가 paragraph로 등장한다고 가정하는 게 있다면 갱신:

- `test_parse_extracts_items_and_table`: `len(doc.items) >= 2` 그대로 유지 (이제 2개 paragraph + 6개 table_cell = 8개), `any(i.kind == "paragraph" for i in doc.items)` OK.
- 다른 테스트 파일에서 sample_form을 쓰는 곳도 확인해서 영향 점검. 특히 `test_node_form_parser.py`, `test_node_planner.py`, `test_pii_form_detector.py`.

### Step 6: Commit

```
feat(hwpx): emit table-cell items with fillable flag

Parser now walks each <hp:tbl> as a 2-D cell grid, emitting one
table_cell Item per cell. Empty value cells become fillable items
with labels inferred from the nearest non-empty neighbor (left or
above). Label cells (with empty neighbors) are emitted with
fillable=False so downstream nodes know not to overwrite them.
Top-level paragraphs inside a table are no longer double-emitted.
```

---

## Bundle 2 — Renderer cell routing

**Files:**
- Modify: `backend/app/hwpx/renderer.py`
- Modify: `backend/tests/unit/test_hwpx_renderer.py`

### Step 1: 테스트 추가

```python
def test_apply_drafts_writes_to_table_cell_not_label():
    """Regression: drafts targeting :tblT:rRcC must update that exact cell,
    not the adjacent label cell."""
    src = FIXTURE.read_bytes()
    doc = parse_hwpx(src)
    # 데이터 행의 첫 셀 (연도 컬럼, 빈 셀)
    target = next(
        it for it in doc.items
        if it.kind == "table_cell" and it.fillable and "tbl0:r1c0" in it.item_id
    )
    out = apply_drafts(src, [DraftItem(item_id=target.item_id, text="2024년")])
    new_doc = parse_hwpx(out)
    # 헤더는 그대로, 데이터 셀에는 텍스트 들어감
    assert any(it.label == "연도" and not it.fillable for it in new_doc.items)
    assert any("2024년" in (it.label or "") for it in new_doc.items)


def test_apply_drafts_paragraph_routing_unchanged():
    src = FIXTURE.read_bytes()
    doc = parse_hwpx(src)
    target = next(it for it in doc.items if it.kind == "paragraph")
    out = apply_drafts(src, [DraftItem(item_id=target.item_id, text="새 본문")])
    new_doc = parse_hwpx(out)
    assert any("새 본문" in (it.label or "") for it in new_doc.items)
```

### Step 2: 실패 확인

```bash
uv run pytest backend/tests/unit/test_hwpx_renderer.py::test_apply_drafts_writes_to_table_cell_not_label -v
```

Expected: 실패 (현재 renderer는 `:tblT:rRcC` 패턴을 모름).

### Step 3: Renderer 갱신

`backend/app/hwpx/renderer.py`:

```python
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

    zout.writestr(zipfile.ZipInfo("mimetype"), b"application/hwp+zip", compress_type=zipfile.ZIP_STORED)

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

    paragraph_drafts: dict[int, DraftItem] = {}
    cell_drafts: dict[tuple[int, int, int], DraftItem] = {}
    for key, draft in section_drafts.items():
        if key.startswith("p"):
            try:
                paragraph_drafts[int(key[1:])] = draft
            except ValueError:
                continue
        else:
            m = _CELL_KEY_RE.match(key)
            if m:
                cell_drafts[(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = draft

    if paragraph_drafts:
        _apply_paragraph_drafts(tree, paragraph_drafts)
    if cell_drafts:
        _apply_cell_drafts(tree, cell_drafts)

    return etree.tostring(tree, encoding="UTF-8", xml_declaration=True)


def _apply_paragraph_drafts(tree, paragraph_drafts: dict[int, DraftItem]) -> None:
    """Same logic as before. Filters non-empty paragraphs, but only outside tables."""
    paragraphs_inside_table: set[int] = set()
    for tbl in tree.iter(f"{_HP}tbl"):
        for p in tbl.iter(f"{_HP}p"):
            paragraphs_inside_table.add(id(p))

    non_empty_paragraphs: list[etree._Element] = []
    for p in tree.iter(f"{_HP}p"):
        if id(p) in paragraphs_inside_table:
            continue
        text = "".join(p.itertext()).strip()
        if text:
            non_empty_paragraphs.append(p)

    for idx, draft in paragraph_drafts.items():
        if idx >= len(non_empty_paragraphs):
            continue
        _write_text_into_paragraph(non_empty_paragraphs[idx], draft)


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


def _write_text_into_paragraph(paragraph, draft: DraftItem) -> None:
    t_elements = list(paragraph.iter(f"{_HP}t"))
    if not t_elements:
        return
    replacement = _PII_PLACEHOLDER if draft.is_pii else draft.text
    t_elements[0].text = replacement
    for t in t_elements[1:]:
        t.text = ""
```

### Step 4: 통과 확인 + 기존 테스트 회귀 확인

```bash
uv run pytest backend/tests/unit/test_hwpx_renderer.py -v
```

특히 `test_apply_drafts_inserts_text` (paragraph 타깃)는 그대로 통과해야 함.

### Step 5: Commit

```
feat(hwpx): renderer routes :tblT:rRcC items to specific cells

apply_drafts now distinguishes paragraph drafts (legacy :pN keys) from
table-cell drafts (:tblT:rRcC keys). Cell drafts are written into the
exact <hp:p> inside the targeted <hp:tc>. Paragraph drafts only count
non-empty paragraphs OUTSIDE tables — fixing the prior bug where they
indexed cells too.
```

---

## Bundle 3 — Graph nodes honor `fillable=False`

**Files:**
- Modify: `backend/app/graph/nodes/planner.py`
- Modify: `backend/app/graph/nodes/generator.py`
- Modify: `backend/tests/unit/test_node_planner.py`
- Modify: `backend/tests/unit/test_node_generator.py`

### Step 1: 테스트 추가

`test_node_planner.py`에 추가:

```python
def test_planner_skips_non_fillable_label_cells(monkeypatch):
    from backend.app.graph.nodes.planner import plan_items
    from backend.app.graph.state import GraphState
    from backend.app.hwpx.models import FormDoc, Item, Table

    monkeypatch.setattr(
        "backend.app.graph.nodes.planner._solar_complete",
        lambda messages: [],
    )

    label = Item(
        item_id="s:tbl0:r0c0",
        label="자기소개",
        section="s",
        kind="table_cell",
        xml_xpath="/x",
        fillable=False,
    )
    value = Item(
        item_id="s:tbl0:r0c1",
        label="자기소개",
        section="s",
        kind="table_cell",
        xml_xpath="/x",
        fillable=True,
    )
    state = GraphState(
        form_doc=FormDoc(sections=["s"], items=[label, value], tables=[], placeholders=[]),
    )

    result = plan_items(state)
    plan_ids = {p.item_id for p in result["plans"]}
    assert "s:tbl0:r0c0" not in plan_ids  # 라벨 셀은 plan 안 만듦
    assert "s:tbl0:r0c1" in plan_ids       # 값 셀은 plan 만듦
```

`test_node_generator.py`에도 동일 패턴으로 generator 스킵 테스트 추가 (단, generator 스킵은 Planner가 이미 plan을 안 만들었으니 자동 — 그러나 Direct test 차원에서 `fillable=False`인 plan이 들어와도 generator가 안 호출되도록 안전망).

### Step 2: 실패 확인

```bash
uv run pytest backend/tests/unit/test_node_planner.py::test_planner_skips_non_fillable_label_cells -v
```

### Step 3: Planner 갱신

`backend/app/graph/nodes/planner.py`의 `plan_items` 안에서, `non_pii_items` 필터에 `fillable` 조건 추가:

```python
non_pii_items = [
    item for item in items
    if not item.is_pii and item.fillable and item.item_id not in skipped_ids
]
```

또한 fillable=False 항목을 `skipped_ids`처럼 다루어 default plan이 만들어지지 않게 한다. 메인 루프 (각 item에 대해 plan을 결정하는 부분)도 갱신:

```python
for item in items:
    if item.item_id in skipped_ids:
        continue
    if not item.fillable:
        continue
    # ...
```

### Step 4: Generator 갱신

`backend/app/graph/nodes/generator.py`:

```python
for plan in state.plans:
    if plan.item_id in pii_item_ids:
        continue
    item = next((it for it in state.form_doc.items if it.item_id == plan.item_id), None)
    if item is not None and not item.fillable:
        continue
    # ...
```

(또는 더 단순히, planner가 이미 fillable 조건을 거르므로 generator는 그대로 두고 통합 테스트로만 확인. 그러나 안전망 차원에서 추가 권장.)

### Step 5: 통과 확인

```bash
uv run pytest backend/tests/unit/test_node_planner.py backend/tests/unit/test_node_generator.py -v
```

### Step 6: Commit

```
feat(graph): planner/generator skip non-fillable label cells

Items with fillable=False (table label cells) are no longer turned
into ItemPlans, and Generator double-checks the flag in case a plan
sneaks in. PII filtering remains independent.
```

---

## Bundle 4 — Final verification

- `uv run pytest backend/tests/ -q` — 전체 통과
- `uv run ruff check . && uv run ruff format --check .` — 깔끔
- 수동: 위 sample_form 픽스처로 reproduction 시나리오 다시 돌려서 라벨이 보존되고 데이터 셀에 들어가는지 확인

---

## Out of scope (V1.5+)

- merged cell의 colSpan/rowSpan 처리 (현재 colSpan은 무시)
- 중첩 테이블
- 행 동적 추가 (`table_row_template` kind 미사용 그대로)
- Streamlit UI에서 표 셀 카드를 표 형태(grid)로 시각화 — 일단 다른 카드와 동일한 list 표현
