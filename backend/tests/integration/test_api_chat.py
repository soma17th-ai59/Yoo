"""Integration tests for POST /api/chat — general QA only, plain JSON."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.session import store


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
async def session_id(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    yield sid
    await store.delete(sid)


def test_chat_404_for_unknown_session(client: TestClient):
    r = client.post("/api/chat", json={"session_id": "ghost", "message": "안녕"})
    assert r.status_code == 404


def test_chat_returns_plain_json_reply(client: TestClient, session_id):
    with patch(
        "backend.app.api.chat._solar_complete", return_value="안녕하세요. 무엇을 도와드릴까요?"
    ):
        r = client.post("/api/chat", json={"session_id": session_id, "message": "안녕"})
    assert r.status_code == 200
    body = r.json()
    assert "reply" in body
    assert isinstance(body["reply"], str)


def test_chat_appends_to_history(client: TestClient, session_id):
    with patch("backend.app.api.chat._solar_complete", return_value="응답"):
        client.post("/api/chat", json={"session_id": session_id, "message": "Q1"})
        client.post("/api/chat", json={"session_id": session_id, "message": "Q2"})
    session = store._sessions[session_id]
    assert session.graph_state is not None
    history = session.graph_state.history
    user_msgs = [t for t in history if t["role"] == "user"]
    assert any(t["content"] == "Q1" for t in user_msgs)
    assert any(t["content"] == "Q2" for t in user_msgs)


def test_chat_masks_pii_before_solar(client: TestClient, session_id):
    """Hard rule 1: user-typed PII (jumin/phone/etc.) MUST be masked before
    being sent to Solar. The masked content is what reaches _solar_complete."""
    captured: list[list[dict]] = []

    def _spy(messages: list[dict]) -> str:
        captured.append(messages)
        return "응답"

    with patch("backend.app.api.chat._solar_complete", side_effect=_spy):
        r = client.post(
            "/api/chat",
            json={
                "session_id": session_id,
                "message": "제 주민번호는 901010-1234567 입니다.",
            },
        )
    assert r.status_code == 200
    assert captured, "Solar was not called"
    last_user_msg = next(
        m for m in reversed(captured[-1]) if m["role"] == "user"
    )
    assert "901010-1234567" not in last_user_msg["content"], (
        "PII (jumin) leaked to Solar — mask_all not applied"
    )
