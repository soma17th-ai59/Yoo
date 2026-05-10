"""Integration tests for GET /api/sessions/{sid}/output.hwpx (lazy render)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.graph.state import DraftItem, GraphState
from backend.app.hwpx.parser import parse_hwpx
from backend.app.main import app
from backend.app.session import store

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "forms" / "sample_form.hwpx"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
async def session_with_form(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    form_bytes = _FIXTURE.read_bytes()
    await store.put_form_bytes(sid, form_bytes)
    fd = parse_hwpx(form_bytes)
    if not fd.items:
        pytest.skip("fixture has no items")
    drafts = [
        DraftItem(item_id=fd.items[0].item_id, text="적용된 본문", citations=[], locked=True),
    ]
    if len(fd.items) > 1:
        drafts.append(
            DraftItem(item_id=fd.items[1].item_id, text="미적용 본문", citations=[], locked=False)
        )
    state = GraphState(session_id=sid, form_doc=fd, drafts=drafts)
    await store.save_state(sid, state)
    yield sid, fd
    await store.delete(sid)


def test_download_renders_only_locked_drafts(client: TestClient, session_with_form):
    sid, fd = session_with_form
    r = client.get(f"/api/sessions/{sid}/output.hwpx")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/")
    assert r.content[:2] == b"PK"


def test_download_404_without_form(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.get(f"/api/sessions/{sid}/output.hwpx")
    assert r.status_code == 404
