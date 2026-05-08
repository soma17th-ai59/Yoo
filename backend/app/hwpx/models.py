from typing import Literal

from pydantic import BaseModel

ItemKind = Literal["paragraph", "table_cell", "table_row_template", "pii"]


class Item(BaseModel):
    item_id: str
    label: str
    section: str
    expected_chars: int | None = None
    kind: ItemKind
    xml_xpath: str
    is_pii: bool = False
    fillable: bool = True


class Table(BaseModel):
    table_id: str
    headers: list[str]
    row_count: int
    xml_xpath: str


class Placeholder(BaseModel):
    item_id: str
    placeholder_text: str


class FormDoc(BaseModel):
    sections: list[str]
    items: list[Item]
    tables: list[Table]
    placeholders: list[Placeholder]
