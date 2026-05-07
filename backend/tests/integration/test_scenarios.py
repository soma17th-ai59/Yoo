"""End-to-end scenarios A–E driving the full HwpAgent graph through the API.

These exercise the canonical flows from spec §4 / plan Phase 7. Solar is
mocked at the node-level wrappers so the graph runs deterministically;
material extraction is mocked too so we can use synthetic byte content.
"""

from __future__ import annotations

import io
import json
import re
from contextlib import ExitStack
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.hwpx.models import FormDoc, Item
from backend.app.main import app
from backend.app.pii import output_guard
from backend.app.session import store


# ---------------------------------------------------------------------------
# Fixtures and builders
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_store():
    store._sessions.clear()
    yield
    store._sessions.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _form_with_pii() -> FormDoc:
    """5-item form: 1 PII (주민등록번호) + 4 normal."""
    return FormDoc(
        sections=["Contents/section0.xml"],
        items=[
            Item(
                item_id="s0:p0",
                label="주민등록번호",
                section="Contents/section0.xml",
                kind="paragraph",
                xml_xpath="/hp:p[1]",
                is_pii=True,
            ),
            Item(
                item_id="s0:p1",
                label="연구의 필요성",
                section="Contents/section0.xml",
                kind="paragraph",
                xml_xpath="/hp:p[2]",
            ),
            Item(
                item_id="s0:p2",
                label="연구 방법",
                section="Contents/section0.xml",
                kind="paragraph",
                xml_xpath="/hp:p[3]",
            ),
            Item(
                item_id="s0:p3",
                label="예상 결과",
                section="Contents/section0.xml",
                kind="paragraph",
                xml_xpath="/hp:p[4]",
            ),
            Item(
                item_id="s0:p4",
                label="활용 방안",
                section="Contents/section0.xml",
                kind="paragraph",
                xml_xpath="/hp:p[5]",
            ),
        ],
        tables=[],
        placeholders=[],
    )


def _planner_for_form(form: FormDoc, needs_question_ids: set[str] | None = None) -> list[dict]:
    needs_question_ids = needs_question_ids or set()
    return [
        {
            "item_id": it.item_id,
            "source_evidence": ["m1"],
            "confidence": 0.9,
            "needs_question": it.item_id in needs_question_ids,
            "question": "본인의 강점을 한 줄로 알려주세요." if it.item_id in needs_question_ids else None,
        }
        for it in form.items
        if not it.is_pii  # PII items get pii_placeholder evidence handled by the renderer
    ] + [
        {
            "item_id": it.item_id,
            "source_evidence": ["pii_placeholder"],
            "confidence": 1.0,
            "needs_question": False,
            "question": None,
        }
        for it in form.items
        if it.is_pii
    ]


async def _create_session_with_form_and_materials(
    material_payloads: list[tuple[str, bytes]] | None = None,
) -> str:
    if material_payloads is None:
        material_payloads = [
            ("cv.txt", b"CV-bytes"),
            ("plan.txt", b"PLAN-bytes"),
            ("report.txt", b"REPORT-bytes"),
        ]
    async with _client() as c:
        sid = (await c.post("/api/sessions")).json()["session_id"]
        await c.post(
            "/api/upload",
            data={"session_id": sid, "kind": "form"},
            files={"file": ("f.hwpx", io.BytesIO(b"fake-form"), "application/octet-stream")},
        )
        for fname, fbytes in material_payloads:
            await c.post(
                "/api/upload",
                data={"session_id": sid, "kind": "material"},
                files={"file": (fname, io.BytesIO(fbytes), "application/octet-stream")},
            )
    return sid


async def _consume_sse(response) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    current_event = "message"
    data_buf: list[str] = []
    async for raw in response.aiter_lines():
        line = raw.rstrip("\r")
        if line == "":
            if data_buf:
                events.append((current_event, "\n".join(data_buf)))
            current_event = "message"
            data_buf = []
            continue
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_buf.append(line.split(":", 1)[1].strip())
    if data_buf:
        events.append((current_event, "\n".join(data_buf)))
    return events


def _start_fill_patches(form: FormDoc, *, planner_response: list[dict] | None = None):
    """Patches that drive a complete start_fill run with mocked Solar."""
    return [
        patch(
            "backend.app.graph.nodes.router._solar_complete",
            return_value={"intent": "start_fill", "confidence": 0.95},
        ),
        patch(
            "backend.app.graph.nodes.form_parser.parse_hwpx",
            return_value=form,
        ),
        patch(
            "backend.app.graph.nodes.material_ingestor.extract_text",
            return_value="자료 텍스트",
        ),
        patch(
            "backend.app.graph.nodes.material_ingestor.summarize",
            return_value="요약",
        ),
        patch(
            "backend.app.graph.nodes.planner._solar_complete",
            return_value=planner_response or _planner_for_form(form),
        ),
        patch(
            "backend.app.graph.nodes.generator._solar_complete",
            return_value={"text": "생성된 본문 내용", "citations": ["m1"]},
        ),
        patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "ok"},
        ),
        patch(
            "backend.app.graph.nodes.renderer.apply_drafts",
            return_value=b"RENDERED-HWPX-BYTES",
        ),
    ]


# ---------------------------------------------------------------------------
# Scenario A — happy path: ≥60% drafts auto-generated, download served
# ---------------------------------------------------------------------------


async def test_scenario_a_happy_path():
    form = _form_with_pii()
    sid = await _create_session_with_form_and_materials()

    with ExitStack() as stack:
        for p in _start_fill_patches(form):
            stack.enter_context(p)
        async with _client() as c:
            async with c.stream(
                "POST", "/api/chat", json={"session_id": sid, "message": "양식을 채워주세요"}
            ) as response:
                events = await _consume_sse(response)

    event_names = [n for n, _ in events]
    assert "intent" in event_names
    assert "preview" in event_names
    assert "done" in event_names

    preview_data = next(d for n, d in events if n == "preview")
    drafts = json.loads(preview_data)
    non_pii_count = sum(1 for it in form.items if not it.is_pii)
    auto_fill_rate = len(drafts) / len(form.items)
    assert auto_fill_rate >= 0.60, f"auto-fill rate {auto_fill_rate:.2f} below 0.60"
    assert all(d["item_id"] != "s0:p0" for d in drafts), "PII item should not be drafted"
    assert len(drafts) == non_pii_count

    # Download endpoint serves rendered bytes
    async with _client() as c:
        r = await c.get(f"/api/sessions/{sid}/output.hwpx")
    assert r.status_code == 200
    assert r.content == b"RENDERED-HWPX-BYTES"


# ---------------------------------------------------------------------------
# Scenario B — rewrite_item after A leaves Planner cold
# ---------------------------------------------------------------------------


async def test_scenario_b_rewrite_item_skips_planner():
    sid = await _create_session_with_form_and_materials()
    form = _form_with_pii()

    # Run A first to seed drafts
    with ExitStack() as stack:
        for p in _start_fill_patches(form):
            stack.enter_context(p)
        async with _client() as c:
            async with c.stream(
                "POST", "/api/chat", json={"session_id": sid, "message": "양식 채워주세요"}
            ) as response:
                await _consume_sse(response)

    # Simulate session continuity: stash the prior plans on the session
    session = await store.get(sid)
    assert session is not None

    # Now send a rewrite_item — Planner should not be invoked
    planner_calls: list[Any] = []

    def _spy_planner(messages):
        planner_calls.append(messages)
        return _planner_for_form(form)

    with (
        patch(
            "backend.app.graph.nodes.router._solar_complete",
            return_value={"intent": "rewrite_item", "confidence": 0.95},
        ),
        patch(
            "backend.app.graph.nodes.planner._solar_complete",
            side_effect=_spy_planner,
        ),
        patch(
            "backend.app.graph.nodes.generator._solar_complete",
            return_value={"text": "재작성된 본문", "citations": ["m1"]},
        ),
        patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "ok"},
        ),
        patch(
            "backend.app.graph.nodes.renderer.apply_drafts",
            return_value=b"REWRITTEN-HWPX-BYTES",
        ),
    ):
        async with _client() as c:
            async with c.stream(
                "POST",
                "/api/chat",
                json={"session_id": sid, "message": "3번 다시 써줘. 더 학술적으로."},
            ) as response:
                events = await _consume_sse(response)

    assert planner_calls == [], "Planner ran but should be skipped for rewrite_item"
    intent_event = next((d for n, d in events if n == "intent"), None)
    assert intent_event is not None
    assert json.loads(intent_event)["intent"] == "rewrite_item"


# ---------------------------------------------------------------------------
# Scenario C — pending_question fires when Planner needs more info
# ---------------------------------------------------------------------------


async def test_scenario_c_pending_question_event():
    """When Planner marks an item needs_question=True, the Generator skips it
    and the Question node surfaces a pending_question event for that item.
    """
    form = _form_with_pii()
    sid = await _create_session_with_form_and_materials()

    # Mark s0:p4 (활용 방안) as needing a question
    planner_response = _planner_for_form(form, needs_question_ids={"s0:p4"})

    with ExitStack() as stack:
        for p in _start_fill_patches(form, planner_response=planner_response):
            stack.enter_context(p)
        async with _client() as c:
            async with c.stream(
                "POST", "/api/chat", json={"session_id": sid, "message": "양식 채워주세요"}
            ) as response:
                events = await _consume_sse(response)

    event_names = [n for n, _ in events]
    assert "pending_question" in event_names, f"events: {event_names}"
    pq_data = json.loads(next(d for n, d in events if n == "pending_question"))
    assert pq_data["item_id"] == "s0:p4"
    assert "강점" in pq_data["question"] or "정보" in pq_data["question"]

    # The Generator should have skipped s0:p4
    preview_data = next(d for n, d in events if n == "preview")
    drafts = json.loads(preview_data)
    drafted_ids = {d["item_id"] for d in drafts}
    assert "s0:p4" not in drafted_ids


# ---------------------------------------------------------------------------
# Scenario D — add_material runs MaterialIngestor + Planner
# ---------------------------------------------------------------------------


async def test_scenario_d_add_material_invokes_ingestor_and_planner():
    sid = await _create_session_with_form_and_materials()
    form = _form_with_pii()

    # Run A to set up form_doc + initial materials
    with ExitStack() as stack:
        for p in _start_fill_patches(form):
            stack.enter_context(p)
        async with _client() as c:
            async with c.stream(
                "POST", "/api/chat", json={"session_id": sid, "message": "양식 채워주세요"}
            ) as response:
                await _consume_sse(response)

    # Add a new material file via /api/upload
    async with _client() as c:
        await c.post(
            "/api/upload",
            data={"session_id": sid, "kind": "material"},
            files={"file": ("extra.txt", io.BytesIO(b"EXTRA-bytes"), "application/octet-stream")},
        )

    # Now send add_material chat message
    planner_calls: list[Any] = []

    def _spy_planner(messages):
        planner_calls.append(messages)
        return _planner_for_form(form)

    with (
        patch(
            "backend.app.graph.nodes.router._solar_complete",
            return_value={"intent": "add_material", "confidence": 0.95},
        ),
        patch(
            "backend.app.graph.nodes.material_ingestor.extract_text",
            return_value="새로 추가된 자료",
        ),
        patch(
            "backend.app.graph.nodes.material_ingestor.summarize",
            return_value="새 요약",
        ),
        patch(
            "backend.app.graph.nodes.planner._solar_complete",
            side_effect=_spy_planner,
        ),
        patch(
            "backend.app.graph.nodes.generator._solar_complete",
            return_value={"text": "추가 자료 반영 본문", "citations": ["m2"]},
        ),
        patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            return_value={"verdict": "ok"},
        ),
        patch(
            "backend.app.graph.nodes.renderer.apply_drafts",
            return_value=b"AFTER-ADD-MATERIAL",
        ),
    ):
        async with _client() as c:
            async with c.stream(
                "POST",
                "/api/chat",
                json={"session_id": sid, "message": "이 자료도 참고해 주세요"},
            ) as response:
                events = await _consume_sse(response)

    intent_event = json.loads(next(d for n, d in events if n == "intent"))
    assert intent_event["intent"] == "add_material"
    assert len(planner_calls) == 1, "Planner should run exactly once on add_material"


# ---------------------------------------------------------------------------
# Scenario E — PII safety: Solar bodies don't contain raw PII; PII items
# are skipped by the Generator (Renderer writes [본인 직접 입력] elsewhere)
# ---------------------------------------------------------------------------


_RAW_JUMIN = "900101-1234567"


async def test_scenario_e_pii_never_reaches_solar_or_drafts():
    form = _form_with_pii()
    # Material containing raw 주민번호 — must be masked before any LLM call.
    materials = [("private_cv.txt", f"이력서. 주민번호 {_RAW_JUMIN}".encode("utf-8"))]
    sid = await _create_session_with_form_and_materials(materials)

    captured_payloads: list[str] = []

    def _record_and_route(messages):
        captured_payloads.append(json.dumps(messages, ensure_ascii=False))
        return {"intent": "start_fill", "confidence": 0.95}

    def _record_and_plan(messages):
        captured_payloads.append(json.dumps(messages, ensure_ascii=False))
        return _planner_for_form(form)

    def _record_and_generate(messages):
        captured_payloads.append(json.dumps(messages, ensure_ascii=False))
        return {"text": "생성된 본문 내용", "citations": ["m1"]}

    def _record_and_verify(messages):
        captured_payloads.append(json.dumps(messages, ensure_ascii=False))
        return {"verdict": "ok"}

    def _record_and_summarize(masked_text, filename):
        captured_payloads.append(f"summarize:{filename}:{masked_text}")
        return "요약"

    with (
        patch(
            "backend.app.graph.nodes.router._solar_complete",
            side_effect=_record_and_route,
        ),
        patch(
            "backend.app.graph.nodes.form_parser.parse_hwpx",
            return_value=form,
        ),
        patch(
            "backend.app.graph.nodes.material_ingestor.extract_text",
            return_value=f"이력서. 주민번호 {_RAW_JUMIN}",
        ),
        patch(
            "backend.app.graph.nodes.material_ingestor.summarize",
            side_effect=_record_and_summarize,
        ),
        patch(
            "backend.app.graph.nodes.planner._solar_complete",
            side_effect=_record_and_plan,
        ),
        patch(
            "backend.app.graph.nodes.generator._solar_complete",
            side_effect=_record_and_generate,
        ),
        patch(
            "backend.app.graph.nodes.verifier._solar_complete",
            side_effect=_record_and_verify,
        ),
        patch(
            "backend.app.graph.nodes.renderer.apply_drafts",
            return_value=b"RENDERED",
        ),
    ):
        async with _client() as c:
            async with c.stream(
                "POST", "/api/chat", json={"session_id": sid, "message": "양식 채워주세요"}
            ) as response:
                events = await _consume_sse(response)

    # 1. Raw 주민번호 must NOT appear in any captured payload.
    for payload in captured_payloads:
        assert _RAW_JUMIN not in payload, f"Raw jumin leaked to LLM input: {payload[:200]}"
        ok, reason = output_guard.scan(payload)
        assert ok, f"PII regex hit in LLM payload: {reason} | payload: {payload[:200]}"

    # 2. PII item (s0:p0) must NOT appear in drafts.
    preview_data = next(d for n, d in events if n == "preview")
    drafts = json.loads(preview_data)
    assert all(d["item_id"] != "s0:p0" for d in drafts), "PII item leaked into drafts"
