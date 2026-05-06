"""Integration tests for LangGraph graph adaptive routing.

Each test builds the compiled graph with a mock SessionProvider, patches Solar
calls so no real LLM is invoked, then asserts on final state shape to verify
that the correct nodes ran for each intent.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.app.graph.graph import build_compiled_graph, SessionProvider
from backend.app.graph.state import GraphState, MaterialBundle, ItemPlan, DraftItem
from backend.app.hwpx.models import FormDoc, Item, Placeholder, Table


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(item_id: str, label: str, is_pii: bool = False) -> Item:
    return Item(
        item_id=item_id,
        label=label,
        section="Contents/section0.xml",
        kind="paragraph",
        xml_xpath=f"/hp:p[{item_id}]",
        is_pii=is_pii,
    )


def _minimal_form_doc(*items: Item) -> FormDoc:
    return FormDoc(
        sections=["Contents/section0.xml"],
        items=list(items),
        tables=[],
        placeholders=[],
    )


_SINGLE_ITEM_FORM = _minimal_form_doc(_make_item("s0:p0", "연구의 필요성"))


class _MockSession:
    """Minimal SessionProvider for tests."""

    def get_form_bytes(self, sid: str) -> bytes:
        return b"fake-form-bytes"

    def get_material_files(self, sid: str) -> list[tuple[str, bytes]]:
        return [("cv.txt", b"test material content")]

    def put_rendered_bytes(self, sid: str, data: bytes) -> None:
        pass


_SESSION = _MockSession()

# Solar mock return values
_ROUTER_START_FILL = {"intent": "start_fill", "confidence": 0.95}
_ROUTER_REWRITE = {"intent": "rewrite_item", "confidence": 0.95}
_ROUTER_GENERAL_QA = {"intent": "general_qa", "confidence": 0.95}
_ROUTER_ADD_MATERIAL = {"intent": "add_material", "confidence": 0.95}
_ROUTER_UPLOAD_FORM = {"intent": "upload_form", "confidence": 0.95}

_PLANNER_RESPONSE = [
    {
        "item_id": "s0:p0",
        "source_evidence": ["m1"],
        "confidence": 0.9,
        "needs_question": False,
        "question": None,
    }
]
_GENERATOR_RESPONSE = {"text": "테스트 내용입니다.", "citations": ["m1"]}
_VERIFIER_OK = {"verdict": "ok"}


def _build_graph():
    return build_compiled_graph(_SESSION)


# ---------------------------------------------------------------------------
# Test 1: start_fill → full pipeline → form_doc and drafts set
# ---------------------------------------------------------------------------


def test_start_fill_route():
    """start_fill intent runs FormParser + Generator; final state has form_doc and drafts."""
    graph = _build_graph()
    initial = GraphState(user_message="양식을 채워주세요", session_id="s1")

    with (
        patch(
            "backend.app.graph.nodes.router._solar_complete",
            return_value=_ROUTER_START_FILL,
        ),
        patch(
            "backend.app.graph.nodes.form_parser.parse_hwpx",
            return_value=_SINGLE_ITEM_FORM,
        ),
        patch(
            "backend.app.graph.nodes.material_ingestor.extract_text",
            return_value="test material content",
        ),
        patch(
            "backend.app.graph.nodes.material_ingestor.summarize",
            return_value="요약 내용",
        ),
        patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=_PLANNER_RESPONSE,
        ),
        patch(
            "backend.app.graph.nodes.generator._solar_complete",
            return_value=_GENERATOR_RESPONSE,
        ),
        patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value=_VERIFIER_OK,
        ),
        patch(
            "backend.app.graph.nodes.renderer.apply_drafts",
            return_value=b"output-hwpx-bytes",
        ),
    ):
        result = graph.invoke(initial)

    # LangGraph returns a dict when Pydantic state is used
    final = GraphState.model_validate(result) if isinstance(result, dict) else result

    assert final.form_doc is not None, "FormParser did not set form_doc"
    assert len(final.drafts) > 0, "Generator did not produce drafts"
    assert all(d.approved for d in final.drafts), "Verifier did not approve drafts"


# ---------------------------------------------------------------------------
# Test 2: rewrite_item skips Planner; drafts are produced
# ---------------------------------------------------------------------------


def test_rewrite_item_skips_planner():
    """rewrite_item routes directly to Generator; Planner is never called."""
    graph = _build_graph()

    pre_plan = ItemPlan(
        item_id="s0:p0",
        source_evidence=["m1"],
        confidence=0.9,
        needs_question=False,
    )
    initial = GraphState(
        user_message="다시 써줘",
        session_id="s2",
        form_doc=_SINGLE_ITEM_FORM,
        plans=[pre_plan],
    )

    planner_called = []

    def _spy_planner(messages):
        planner_called.append(messages)
        return _PLANNER_RESPONSE

    with (
        patch(
            "backend.app.graph.nodes.router._solar_complete",
            return_value=_ROUTER_REWRITE,
        ),
        patch(
            "backend.app.graph.nodes.planner._solar_complete",
            side_effect=_spy_planner,
        ),
        patch(
            "backend.app.graph.nodes.generator._solar_complete",
            return_value=_GENERATOR_RESPONSE,
        ),
        patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value=_VERIFIER_OK,
        ),
        patch(
            "backend.app.graph.nodes.renderer.apply_drafts",
            return_value=b"output-hwpx-bytes",
        ),
    ):
        result = graph.invoke(initial)

    final = GraphState.model_validate(result) if isinstance(result, dict) else result

    assert not planner_called, "Planner Solar was called but should have been skipped"
    assert len(final.plans) == 1, "Plan count changed unexpectedly"
    assert len(final.drafts) > 0, "Generator did not produce drafts"


# ---------------------------------------------------------------------------
# Test 3: general_qa → no renderer, response in history
# ---------------------------------------------------------------------------


def test_general_qa_has_no_renderer():
    """general_qa intent must not run Renderer; response appears in history."""
    graph = _build_graph()
    initial = GraphState(user_message="LangGraph이 뭔가요?", session_id="s3")

    renderer_called = []

    def _spy_renderer(form_bytes, drafts):
        renderer_called.append(True)
        return b"should-not-be-called"

    with (
        patch(
            "backend.app.graph.nodes.router._solar_complete",
            return_value=_ROUTER_GENERAL_QA,
        ),
        patch(
            "backend.app.graph.graph._solar_mod.complete",
            return_value="LangGraph은 LLM 애플리케이션 구축 프레임워크입니다.",
        ),
        patch(
            "backend.app.graph.nodes.renderer.apply_drafts",
            side_effect=_spy_renderer,
        ),
    ):
        result = graph.invoke(initial)

    final = GraphState.model_validate(result) if isinstance(result, dict) else result

    assert not renderer_called, "Renderer ran but should not for general_qa"
    assert not hasattr(final, "rendered_bytes") or not getattr(final, "rendered_bytes", None), \
        "rendered_bytes should not be set for general_qa"
    # Check that a reply was produced (history should have assistant turn)
    assistant_turns = [t for t in final.history if t.get("role") == "assistant"]
    assert len(assistant_turns) > 0, "No assistant reply in history for general_qa"


# ---------------------------------------------------------------------------
# Test 4: add_material → MaterialIngestor + Planner both run
# ---------------------------------------------------------------------------


def test_add_material_runs_ingestor_and_planner():
    """add_material intent runs MaterialIngestor and Planner; materials and plans updated."""
    graph = _build_graph()

    initial = GraphState(
        user_message="자료를 추가할게요",
        session_id="s4",
        form_doc=_SINGLE_ITEM_FORM,
        materials=MaterialBundle(docs=[]),
    )

    with (
        patch(
            "backend.app.graph.nodes.router._solar_complete",
            return_value=_ROUTER_ADD_MATERIAL,
        ),
        patch(
            "backend.app.graph.nodes.material_ingestor.extract_text",
            return_value="추가 자료 내용",
        ),
        patch(
            "backend.app.graph.nodes.material_ingestor.summarize",
            return_value="추가 자료 요약",
        ),
        patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=_PLANNER_RESPONSE,
        ),
        patch(
            "backend.app.graph.nodes.generator._solar_complete",
            return_value=_GENERATOR_RESPONSE,
        ),
        patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value=_VERIFIER_OK,
        ),
        patch(
            "backend.app.graph.nodes.renderer.apply_drafts",
            return_value=b"output-hwpx-bytes",
        ),
    ):
        result = graph.invoke(initial)

    final = GraphState.model_validate(result) if isinstance(result, dict) else result

    assert len(final.materials.docs) > 0, "MaterialIngestor did not add docs"
    assert len(final.plans) > 0, "Planner did not produce plans"


# ---------------------------------------------------------------------------
# Test 5: upload_form → only FormParser runs; no plans generated
# ---------------------------------------------------------------------------


def test_upload_form_only_parses():
    """upload_form intent runs only FormParser; no plans generated."""
    graph = _build_graph()
    initial = GraphState(user_message="양식을 업로드합니다", session_id="s5")

    planner_called = []

    def _spy_planner(messages):
        planner_called.append(messages)
        return _PLANNER_RESPONSE

    with (
        patch(
            "backend.app.graph.nodes.router._solar_complete",
            return_value=_ROUTER_UPLOAD_FORM,
        ),
        patch(
            "backend.app.graph.nodes.form_parser.parse_hwpx",
            return_value=_SINGLE_ITEM_FORM,
        ),
        patch(
            "backend.app.graph.nodes.planner._solar_complete",
            side_effect=_spy_planner,
        ),
    ):
        result = graph.invoke(initial)

    final = GraphState.model_validate(result) if isinstance(result, dict) else result

    assert final.form_doc is not None, "FormParser did not set form_doc"
    assert not planner_called, "Planner ran but should not for upload_form"
    assert final.plans == [], "Plans should be empty for upload_form"


# ---------------------------------------------------------------------------
# Test 6: error in router → no subsequent node runs
# ---------------------------------------------------------------------------


def test_error_state_routes_to_end():
    """When router returns errors, no subsequent node runs (graph goes to END)."""
    graph = _build_graph()
    initial = GraphState(user_message="", session_id="s6")  # empty message triggers error

    # router.route() returns errors when user_message is empty;
    # no Solar mock needed — the node returns early with errors.
    form_parser_called = []

    def _spy_form_parser(data: bytes):
        form_parser_called.append(True)
        return _SINGLE_ITEM_FORM

    with patch(
        "backend.app.graph.nodes.form_parser.parse_hwpx",
        side_effect=_spy_form_parser,
    ):
        result = graph.invoke(initial)

    final = GraphState.model_validate(result) if isinstance(result, dict) else result

    assert len(final.errors) > 0, "Expected errors in state"
    assert not form_parser_called, "FormParser ran after router error"
    assert final.form_doc is None, "form_doc should not be set when router errors"
