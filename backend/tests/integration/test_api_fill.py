"""Integration tests for POST /api/sessions/{sid}/fill."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.session import store

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "forms" / "sample_form.hwpx"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
async def session_with_form_and_material(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    form_bytes = _FIXTURE.read_bytes()
    client.post(
        "/api/upload",
        data={"session_id": sid, "kind": "form"},
        files={"file": ("sample.hwpx", form_bytes, "application/octet-stream")},
    )
    client.post(
        "/api/upload",
        data={"session_id": sid, "kind": "material"},
        files={"file": ("cv.txt", b"My name is anonymized researcher.", "text/plain")},
    )
    yield sid
    await store.delete(sid)


def test_fill_returns_404_for_unknown_session(client: TestClient):
    r = client.post("/api/sessions/nonexistent/fill")
    assert r.status_code == 404


_FILL_PATCHES = [
    "backend.app.graph.nodes.material_ingestor.extract_text",
    "backend.app.graph.nodes.material_ingestor.summarize",
    "backend.app.graph.nodes.planner._solar_complete",
    "backend.app.graph.nodes.generator._solar_complete",
    "backend.app.graph.nodes.verifier._solar_complete",
]

_FILL_RETURNS = [
    "연구자 텍스트",
    "요약",
    [],
    {"text": "초안", "citations": []},
    {"verdict": "ok"},
]


def test_fill_streams_node_progress_and_drafts(client: TestClient, session_with_form_and_material):
    sid = session_with_form_and_material
    with (
        patch(_FILL_PATCHES[0], return_value=_FILL_RETURNS[0]),
        patch(_FILL_PATCHES[1], return_value=_FILL_RETURNS[1]),
        patch(_FILL_PATCHES[2], return_value=_FILL_RETURNS[2]),
        patch(_FILL_PATCHES[3], return_value=_FILL_RETURNS[3]),
        patch(_FILL_PATCHES[4], return_value=_FILL_RETURNS[4]),
    ):
        r = client.post(f"/api/sessions/{sid}/fill")
    assert r.status_code == 200
    body = r.text
    assert "event: node_started" in body
    assert "event: form_parsed" in body
    assert "event: done" in body


def test_fill_drafts_all_unlocked(client: TestClient, session_with_form_and_material):
    sid = session_with_form_and_material
    with (
        patch(_FILL_PATCHES[0], return_value=_FILL_RETURNS[0]),
        patch(_FILL_PATCHES[1], return_value=_FILL_RETURNS[1]),
        patch(_FILL_PATCHES[2], return_value=_FILL_RETURNS[2]),
        patch(_FILL_PATCHES[3], return_value=_FILL_RETURNS[3]),
        patch(_FILL_PATCHES[4], return_value=_FILL_RETURNS[4]),
    ):
        client.post(f"/api/sessions/{sid}/fill")
    session = store._sessions[sid]
    assert session.graph_state is not None
    assert all(d.locked is False for d in session.graph_state.drafts)
