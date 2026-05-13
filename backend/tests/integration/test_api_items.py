"""Integration tests for POST /api/sessions/{sid}/items/apply and /unlock."""

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
async def session_with_drafts(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    form = FormDoc(
        sections=["s1"],
        items=[
            Item(
                item_id="it1", label="자기소개", section="s1", kind="paragraph", xml_xpath="/p[1]"
            ),
            Item(
                item_id="pii1",
                label="성명",
                section="s1",
                kind="paragraph",
                xml_xpath="/p[2]",
                is_pii=True,
            ),
        ],
        tables=[],
        placeholders=[],
    )
    state = GraphState(
        session_id=sid,
        form_doc=form,
        drafts=[
            DraftItem(item_id="it1", text="안녕하세요", citations=[], locked=False),
            DraftItem(
                item_id="pii1",
                text="",
                citations=[],
                locked=False,
                status="pii",
                is_pii=True,
            ),
        ],
    )
    await store.save_state(sid, state)
    yield sid
    await store.delete(sid)


def test_apply_sets_locked_true(client: TestClient, session_with_drafts):
    sid = session_with_drafts
    r = client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "it1"})
    assert r.status_code == 200
    assert r.json()["locked"] is True
    assert r.json()["item_id"] == "it1"


def test_unlock_sets_locked_false(client: TestClient, session_with_drafts):
    sid = session_with_drafts
    client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "it1"})
    r = client.post(f"/api/sessions/{sid}/items/unlock", json={"item_id": "it1"})
    assert r.status_code == 200
    assert r.json()["locked"] is False


def test_apply_pii_now_allowed(client: TestClient, session_with_drafts):
    """PII items are user-fillable. apply locks the user-typed text."""
    sid = session_with_drafts
    # User types their PII via PUT /drafts first.
    put_r = client.put(
        f"/api/sessions/{sid}/drafts",
        json={"item_id": "pii1", "text": "홍길동"},
    )
    assert put_r.status_code == 200

    r = client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "pii1"})
    assert r.status_code == 200
    assert r.json()["locked"] is True
    assert r.json()["text"] == "홍길동"


def test_apply_unknown_item_returns_404(client: TestClient, session_with_drafts):
    sid = session_with_drafts
    r = client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "ghost"})
    assert r.status_code == 404


def test_apply_idempotent(client: TestClient, session_with_drafts):
    sid = session_with_drafts
    r1 = client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "it1"})
    r2 = client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "it1"})
    assert r1.json()["locked"] is True
    assert r2.json()["locked"] is True


def test_item_chat_400_when_locked(client: TestClient, session_with_drafts):
    sid = session_with_drafts
    client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "it1"})
    r = client.post(
        f"/api/sessions/{sid}/item-chat",
        json={"item_id": "it1", "message": "다시 써줘", "history": []},
    )
    assert r.status_code == 400
    assert "해제" in r.json()["detail"]
