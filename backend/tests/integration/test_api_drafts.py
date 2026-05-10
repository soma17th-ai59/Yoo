"""Integration tests for PUT /api/sessions/{sid}/drafts (text-only update)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.graph.state import DraftItem, GraphState
from backend.app.hwpx.models import FormDoc, Item
from backend.app.main import app
from backend.app.session import store


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
async def session_with_draft(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    form = FormDoc(
        sections=["s1"],
        items=[
            Item(item_id="it1", label="자기소개", section="s1", kind="paragraph", xml_xpath="/p[1]")
        ],
        tables=[],
        placeholders=[],
    )
    state = GraphState(
        session_id=sid,
        form_doc=form,
        drafts=[DraftItem(item_id="it1", text="원본", citations=[], locked=False)],
    )
    await store.save_state(sid, state)
    yield sid
    await store.delete(sid)


def test_put_drafts_replaces_text_only(client: TestClient, session_with_draft):
    sid = session_with_draft
    r = client.put(f"/api/sessions/{sid}/drafts", json={"item_id": "it1", "text": "수정됨"})
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "수정됨"
    assert body["locked"] is False


def test_put_drafts_409_when_locked(client: TestClient, session_with_draft):
    sid = session_with_draft
    client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "it1"})
    r = client.put(f"/api/sessions/{sid}/drafts", json={"item_id": "it1", "text": "수정됨"})
    assert r.status_code == 409


def test_put_drafts_no_immediate_render(client: TestClient, session_with_draft):
    sid = session_with_draft
    client.put(f"/api/sessions/{sid}/drafts", json={"item_id": "it1", "text": "수정"})
    session = store._sessions[sid]
    assert session.rendered_bytes is None
