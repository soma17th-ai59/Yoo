"""Tests for GraphState and related models in backend.app.graph.state."""

from backend.app.graph.state import (
    DraftItem,
    GraphState,
    ItemPlan,
    append_turn,
)
from backend.app.hwpx.models import FormDoc, Item, Placeholder, Table

# ---------------------------------------------------------------------------
# 1. Default empty state
# ---------------------------------------------------------------------------


def test_graph_state_default_empty():
    state = GraphState()
    assert state.session_id is None
    assert state.form_doc is None
    assert state.materials.docs == []
    assert state.plans == []
    assert state.drafts == []
    assert state.history == []
    assert state.errors == []


# ---------------------------------------------------------------------------
# 2. model_dump produces expected dict shape
# ---------------------------------------------------------------------------


def test_graph_state_model_dump_shape():
    state = GraphState()
    d = state.model_dump()
    assert set(d.keys()) == {
        "session_id",
        "form_doc",
        "materials",
        "plans",
        "drafts",
        "history",
        "errors",
    }
    assert d["materials"] == {"docs": []}
    assert d["plans"] == []
    assert d["drafts"] == []
    assert d["history"] == []
    assert d["errors"] == []


# ---------------------------------------------------------------------------
# 3. Round-trip serialization
# ---------------------------------------------------------------------------


def test_graph_state_round_trip():
    state = GraphState(
        errors=["테스트 오류"],
    )
    restored = GraphState.model_validate(state.model_dump())
    assert restored == state


# ---------------------------------------------------------------------------
# 4. ItemPlan serializes/deserializes correctly
# ---------------------------------------------------------------------------


def test_item_plan_round_trip():
    plan = ItemPlan(
        item_id="sec0:p1",
        source_evidence=["mat_001", "mat_002"],
        confidence=0.92,
        needs_question=False,
    )
    restored = ItemPlan.model_validate(plan.model_dump())
    assert restored == plan


def test_item_plan_with_question():
    plan = ItemPlan(
        item_id="sec0:p2",
        source_evidence=[],
        confidence=0.3,
        needs_question=True,
        question="연구 목표를 설명해 주세요.",
    )
    restored = ItemPlan.model_validate(plan.model_dump())
    assert restored.question == "연구 목표를 설명해 주세요."


# ---------------------------------------------------------------------------
# 5. DraftItem serializes/deserializes correctly
# ---------------------------------------------------------------------------


def test_draft_item_round_trip():
    draft = DraftItem(
        item_id="sec0:p0",
        text="이 연구는 …",
        citations=["mat_001:p3", "mat_002:p1"],
        locked=True,
    )
    restored = DraftItem.model_validate(draft.model_dump())
    assert restored == draft


def test_draft_item_defaults():
    draft = DraftItem(item_id="sec0:p0", text="내용", citations=[])
    assert draft.locked is False


# ---------------------------------------------------------------------------
# 6. append_turn basic
# ---------------------------------------------------------------------------


def test_append_turn_adds_entry():
    state = GraphState()
    new_state = append_turn(state, "user", "안녕")
    assert len(new_state.history) == 1
    assert new_state.history[0] == {"role": "user", "content": "안녕"}


def test_append_turn_multiple():
    state = GraphState()
    state = append_turn(state, "user", "안녕")
    state = append_turn(state, "assistant", "반갑습니다")
    assert len(state.history) == 2
    assert state.history[1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# 7. append_turn with 12 turns keeps only last 10
# ---------------------------------------------------------------------------


def test_append_turn_truncation():
    state = GraphState()
    for i in range(12):
        state = append_turn(state, "user", f"메시지 {i}")
    assert len(state.history) == 10
    # oldest two (메시지 0, 메시지 1) must be gone
    contents = [t["content"] for t in state.history]
    assert "메시지 0" not in contents
    assert "메시지 1" not in contents
    assert "메시지 11" in contents
    assert "메시지 2" in contents


# ---------------------------------------------------------------------------
# 8. Original state is not mutated by append_turn
# ---------------------------------------------------------------------------


def test_append_turn_immutable():
    original = GraphState()
    _ = append_turn(original, "user", "변경 없음")
    assert original.history == []


def test_append_turn_does_not_share_dict_references():
    original = GraphState(history=[{"role": "user", "content": "원본"}])
    new_state = append_turn(original, "assistant", "응답")
    new_state.history[0]["content"] = "변경됨"
    assert original.history[0]["content"] == "원본"


# ---------------------------------------------------------------------------
# 9. GraphState with form_doc round-trip
# ---------------------------------------------------------------------------


def test_graph_state_with_form_doc_round_trip():
    form_doc = FormDoc(
        sections=["Contents/section0.xml"],
        items=[
            Item(
                item_id="Contents/section0.xml:p0",
                label="연구 목표",
                section="Contents/section0.xml",
                kind="paragraph",
                xml_xpath="//hp:p[1]",
            )
        ],
        tables=[
            Table(
                table_id="Contents/section0.xml:t0",
                headers=["항목", "내용"],
                row_count=3,
                xml_xpath="//hp:tbl[1]",
            )
        ],
        placeholders=[
            Placeholder(
                item_id="Contents/section0.xml:p0",
                placeholder_text="연구 목표를 입력하세요.",
            )
        ],
    )
    state = GraphState(form_doc=form_doc)
    restored = GraphState.model_validate(state.model_dump())
    assert restored == state
    assert restored.form_doc is not None
    assert restored.form_doc.items[0].label == "연구 목표"
