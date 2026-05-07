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
