"""Integration tests for /api/chat (SSE) and the output download endpoint."""

from __future__ import annotations

import io
import json
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.hwpx.models import FormDoc, Item
from backend.app.main import app
from backend.app.session import store


@pytest.fixture(autouse=True)
def _reset_store():
    store._sessions.clear()
    yield
    store._sessions.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _form_doc() -> FormDoc:
    return FormDoc(
        sections=["Contents/section0.xml"],
        items=[
            Item(
                item_id="s0:p0",
                label="연구의 필요성",
                section="Contents/section0.xml",
                kind="paragraph",
                xml_xpath="/hp:p[1]",
                is_pii=False,
            )
        ],
        tables=[],
        placeholders=[],
    )


def _start_fill_patches():
    """Patch graph internals so start_fill runs end-to-end with fake data."""
    return [
        patch(
            "backend.app.graph.nodes.router._solar_complete",
            return_value={"intent": "start_fill", "confidence": 0.95},
        ),
        patch(
            "backend.app.graph.nodes.form_parser.parse_hwpx",
            return_value=_form_doc(),
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
            return_value=[
                {
                    "item_id": "s0:p0",
                    "source_evidence": ["m1"],
                    "confidence": 0.9,
                    "needs_question": False,
                    "question": None,
                }
            ],
        ),
        patch(
            "backend.app.graph.nodes.generator._solar_complete",
            return_value={"text": "테스트 본문", "citations": ["m1"]},
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


async def _consume_sse(response) -> list[tuple[str, str]]:
    """Read SSE stream as a list of (event, data) tuples."""
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


async def _create_session_with_form() -> str:
    async with _client() as c:
        sid = (await c.post("/api/sessions")).json()["session_id"]
        await c.post(
            "/api/upload",
            data={"session_id": sid, "kind": "form"},
            files={"file": ("f.hwpx", io.BytesIO(b"fake-form"), "application/octet-stream")},
        )
        await c.post(
            "/api/upload",
            data={"session_id": sid, "kind": "material"},
            files={"file": ("cv.txt", io.BytesIO(b"cv-bytes"), "text/plain")},
        )
    return sid


# ---------------------------------------------------------------------------
# Happy path: SSE event stream for start_fill
# ---------------------------------------------------------------------------


async def test_chat_emits_intent_node_started_preview_done():
    sid = await _create_session_with_form()
    with ExitStack() as stack:
        for p in _start_fill_patches():
            stack.enter_context(p)
        async with _client() as c:
            async with c.stream(
                "POST",
                "/api/chat",
                json={"session_id": sid, "message": "양식 채워주세요"},
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                events = await _consume_sse(response)

    event_names = [name for name, _ in events]
    assert "intent" in event_names
    assert "node_started" in event_names
    assert "preview" in event_names
    assert "done" in event_names

    intent_payload = json.loads(next(data for name, data in events if name == "intent"))
    assert intent_payload["intent"] == "start_fill"

    done_payload = json.loads(next(data for name, data in events if name == "done"))
    assert done_payload["download_url"] == f"/api/sessions/{sid}/output.hwpx"


async def test_chat_stores_rendered_bytes_after_run():
    sid = await _create_session_with_form()
    with ExitStack() as stack:
        for p in _start_fill_patches():
            stack.enter_context(p)
        async with _client() as c:
            async with c.stream(
                "POST",
                "/api/chat",
                json={"session_id": sid, "message": "양식 채워주세요"},
            ) as response:
                await _consume_sse(response)

    session = await store.get(sid)
    assert session is not None
    assert session.rendered_bytes == b"RENDERED-HWPX-BYTES"


# ---------------------------------------------------------------------------
# 404 handling
# ---------------------------------------------------------------------------


async def test_chat_unknown_session_returns_404():
    async with _client() as c:
        r = await c.post(
            "/api/chat",
            json={"session_id": "nope", "message": "hello"},
        )
    assert r.status_code == 404


async def test_download_returns_rendered_bytes():
    sid = await _create_session_with_form()
    store.put_rendered_bytes(sid, b"OUTPUT-BYTES")
    async with _client() as c:
        r = await c.get(f"/api/sessions/{sid}/output.hwpx")
    assert r.status_code == 200
    assert r.content == b"OUTPUT-BYTES"
    assert r.headers["content-type"].startswith("application/")
    assert "attachment" in r.headers.get("content-disposition", "").lower()


async def test_download_before_render_returns_404():
    sid = await _create_session_with_form()
    async with _client() as c:
        r = await c.get(f"/api/sessions/{sid}/output.hwpx")
    assert r.status_code == 404


async def test_download_unknown_session_returns_404():
    async with _client() as c:
        r = await c.get("/api/sessions/no-such/output.hwpx")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/sessions/{id}/drafts — manual edit + re-render
# ---------------------------------------------------------------------------


async def test_put_draft_updates_state_and_rerenders():
    sid = await _create_session_with_form()
    with ExitStack() as stack:
        for p in _start_fill_patches():
            stack.enter_context(p)
        async with _client() as c:
            async with c.stream(
                "POST",
                "/api/chat",
                json={"session_id": sid, "message": "양식 채워주세요"},
            ) as response:
                await _consume_sse(response)

        async with _client() as c:
            r = await c.put(
                f"/api/sessions/{sid}/drafts",
                json={"item_id": "s0:p0", "text": "사용자가 직접 편집한 본문"},
            )

    assert r.status_code == 200
    assert r.json()["item_id"] == "s0:p0"

    session = await store.get(sid)
    assert session is not None
    matched = next(d for d in session.graph_state.drafts if d.item_id == "s0:p0")
    assert matched.text == "사용자가 직접 편집한 본문"
    assert matched.approved is True


async def test_put_draft_unknown_item_returns_404():
    sid = await _create_session_with_form()
    with ExitStack() as stack:
        for p in _start_fill_patches():
            stack.enter_context(p)
        async with _client() as c:
            async with c.stream(
                "POST",
                "/api/chat",
                json={"session_id": sid, "message": "양식 채워주세요"},
            ) as response:
                await _consume_sse(response)

        async with _client() as c:
            r = await c.put(
                f"/api/sessions/{sid}/drafts",
                json={"item_id": "s0:nope", "text": "x"},
            )
    assert r.status_code == 404


async def test_put_draft_no_session_returns_404():
    async with _client() as c:
        r = await c.put(
            "/api/sessions/no-such/drafts",
            json={"item_id": "s0:p0", "text": "x"},
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/sessions/{id}/items/{item_id}/chat — per-item conversation
# ---------------------------------------------------------------------------


async def test_item_chat_returns_solar_reply():
    sid = await _create_session_with_form()
    with ExitStack() as stack:
        for p in _start_fill_patches():
            stack.enter_context(p)
        async with _client() as c:
            async with c.stream(
                "POST", "/api/chat", json={"session_id": sid, "message": "양식 채워주세요"}
            ) as response:
                await _consume_sse(response)

    with patch(
        "backend.app.api.sessions.solar.complete",
        return_value="이 항목의 핵심을 말씀해 주시겠어요?",
    ):
        async with _client() as c:
            r = await c.post(
                f"/api/sessions/{sid}/item-chat",
                json={"item_id": "s0:p0", "message": "이 항목 어떻게 채워?", "history": []},
            )
    assert r.status_code == 200
    body = r.json()
    assert body["reply"].startswith("이 항목의 핵심")


async def test_item_chat_masks_pii_before_solar():
    sid = await _create_session_with_form()
    with ExitStack() as stack:
        for p in _start_fill_patches():
            stack.enter_context(p)
        async with _client() as c:
            async with c.stream(
                "POST", "/api/chat", json={"session_id": sid, "message": "양식 채워주세요"}
            ) as response:
                await _consume_sse(response)

    captured: list[list[dict]] = []

    def _spy(messages, **kwargs):
        captured.append(messages)
        return "고맙습니다."

    with patch("backend.app.api.sessions.solar.complete", side_effect=_spy):
        async with _client() as c:
            r = await c.post(
                f"/api/sessions/{sid}/item-chat",
                json={
                    "item_id": "s0:p0",
                    "message": "전화번호는 010-1234-5678입니다",
                    "history": [],
                },
            )
    assert r.status_code == 200
    payload = "".join(m.get("content", "") for m in captured[0])
    assert "010-1234-5678" not in payload


async def test_item_chat_pii_item_returns_400():
    """Per spec §7 rule 2 — PII items don't get LLM-assisted authoring."""
    sid = await _create_session_with_form()
    with ExitStack() as stack:
        for p in _start_fill_patches():
            stack.enter_context(p)
        async with _client() as c:
            async with c.stream(
                "POST", "/api/chat", json={"session_id": sid, "message": "양식 채워주세요"}
            ) as response:
                await _consume_sse(response)

    # Patch the saved graph_state's form_doc so item s0:p0 is PII.
    from backend.app.hwpx.models import FormDoc, Item

    sess = await store.get(sid)
    pii_form = FormDoc(
        sections=["Contents/section0.xml"],
        items=[
            Item(
                item_id="s0:p0",
                label="성명",
                section="Contents/section0.xml",
                kind="paragraph",
                xml_xpath="/hp:p[1]",
                is_pii=True,
            )
        ],
        tables=[],
        placeholders=[],
    )
    new_state = sess.graph_state.model_copy(update={"form_doc": pii_form})
    await store.save_state(sid, new_state)

    async with _client() as c:
        r = await c.post(
            f"/api/sessions/{sid}/item-chat",
            json={"item_id": "s0:p0", "message": "어떻게 채울까요?", "history": []},
        )
    assert r.status_code == 400


async def test_item_chat_unknown_session_returns_404():
    async with _client() as c:
        r = await c.post(
            "/api/sessions/no-such/item-chat",
            json={"item_id": "s0:p0", "message": "x", "history": []},
        )
    assert r.status_code == 404


async def test_item_chat_supports_slash_in_item_id():
    """Regression: item_ids contain '/' (e.g. 'Contents/section0.xml:p2')
    so item_id must travel in the body, not the URL path."""
    sid = await _create_session_with_form()
    with ExitStack() as stack:
        for p in _start_fill_patches():
            stack.enter_context(p)
        async with _client() as c:
            async with c.stream(
                "POST", "/api/chat", json={"session_id": sid, "message": "양식 채워주세요"}
            ) as response:
                await _consume_sse(response)

    # Patch saved state with an item_id containing '/'
    from backend.app.graph.state import DraftItem
    from backend.app.hwpx.models import FormDoc, Item

    sess = await store.get(sid)
    real_id = "Contents/section0.xml:p2"
    new_form = FormDoc(
        sections=["Contents/section0.xml"],
        items=[
            Item(
                item_id=real_id,
                label="연구의 필요성",
                section="Contents/section0.xml",
                kind="paragraph",
                xml_xpath="/hp:p[1]",
                is_pii=False,
            )
        ],
        tables=[],
        placeholders=[],
    )
    new_state = sess.graph_state.model_copy(
        update={
            "form_doc": new_form,
            "drafts": [DraftItem(item_id=real_id, text="초안", citations=[])],
        }
    )
    await store.save_state(sid, new_state)

    with patch("backend.app.api.sessions.solar.complete", return_value="follow-up 질문 드립니다."):
        async with _client() as c:
            r = await c.post(
                f"/api/sessions/{sid}/item-chat",
                json={"item_id": real_id, "message": "도와주세요", "history": []},
            )
    assert r.status_code == 200, r.text
    assert "follow-up" in r.json()["reply"]
