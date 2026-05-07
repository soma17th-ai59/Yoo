"""Integration tests for /api/sessions and /api/upload."""

from __future__ import annotations

import io

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import app
from backend.app.session import store


@pytest.fixture(autouse=True)
def _reset_store():
    """Each test starts with a clean in-memory store."""
    store._sessions.clear()
    yield
    store._sessions.clear()


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# POST /api/sessions
# ---------------------------------------------------------------------------


async def test_create_session_returns_id():
    async with await _client() as c:
        r = await c.post("/api/sessions")
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert isinstance(body["session_id"], str)
    assert body["session_id"]


async def test_create_session_yields_unique_ids():
    async with await _client() as c:
        r1 = await c.post("/api/sessions")
        r2 = await c.post("/api/sessions")
    assert r1.json()["session_id"] != r2.json()["session_id"]


# ---------------------------------------------------------------------------
# POST /api/upload
# ---------------------------------------------------------------------------


async def test_upload_form_stores_bytes():
    async with await _client() as c:
        sid = (await c.post("/api/sessions")).json()["session_id"]
        files = {"file": ("form.hwpx", io.BytesIO(b"FORMBYTES"), "application/octet-stream")}
        r = await c.post(
            "/api/upload",
            data={"session_id": sid, "kind": "form"},
            files=files,
        )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "session_id": sid, "kind": "form"}
    assert store.get_form_bytes(sid) == b"FORMBYTES"


async def test_upload_form_replaces_previous():
    async with await _client() as c:
        sid = (await c.post("/api/sessions")).json()["session_id"]
        await c.post(
            "/api/upload",
            data={"session_id": sid, "kind": "form"},
            files={"file": ("a.hwpx", io.BytesIO(b"first"), "application/octet-stream")},
        )
        r = await c.post(
            "/api/upload",
            data={"session_id": sid, "kind": "form"},
            files={"file": ("b.hwpx", io.BytesIO(b"second"), "application/octet-stream")},
        )
    assert r.status_code == 200
    assert store.get_form_bytes(sid) == b"second"


async def test_upload_material_appends():
    async with await _client() as c:
        sid = (await c.post("/api/sessions")).json()["session_id"]
        await c.post(
            "/api/upload",
            data={"session_id": sid, "kind": "material"},
            files={"file": ("cv.pdf", io.BytesIO(b"CV"), "application/pdf")},
        )
        await c.post(
            "/api/upload",
            data={"session_id": sid, "kind": "material"},
            files={"file": ("plan.docx", io.BytesIO(b"PLAN"), "application/octet-stream")},
        )
    files = store.get_material_files(sid)
    assert len(files) == 2
    assert files[0] == ("cv.pdf", b"CV")
    assert files[1] == ("plan.docx", b"PLAN")


async def test_upload_oversize_returns_413():
    async with await _client() as c:
        sid = (await c.post("/api/sessions")).json()["session_id"]
        big = b"x" * (20 * 1024 * 1024 + 1)
        r = await c.post(
            "/api/upload",
            data={"session_id": sid, "kind": "form"},
            files={"file": ("big.hwpx", io.BytesIO(big), "application/octet-stream")},
        )
    assert r.status_code == 413


async def test_upload_invalid_kind_returns_400():
    async with await _client() as c:
        sid = (await c.post("/api/sessions")).json()["session_id"]
        r = await c.post(
            "/api/upload",
            data={"session_id": sid, "kind": "bogus"},
            files={"file": ("x.bin", io.BytesIO(b"x"), "application/octet-stream")},
        )
    assert r.status_code == 400


async def test_upload_unknown_session_returns_404():
    async with await _client() as c:
        r = await c.post(
            "/api/upload",
            data={"session_id": "no-such-session", "kind": "form"},
            files={"file": ("x.hwpx", io.BytesIO(b"x"), "application/octet-stream")},
        )
    assert r.status_code == 404
    assert store.get_form_bytes("no-such-session") == b""
