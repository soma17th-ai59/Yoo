"""End-to-end scenario tests."""

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


def _solar_patches():
    return (
        patch("backend.app.graph.nodes.planner._solar_complete", return_value=[]),
        patch(
            "backend.app.graph.nodes.generator._solar_complete",
            return_value={"text": "초안 본문", "citations": []},
        ),
        patch("backend.app.graph.nodes.verifier._solar_complete", return_value={"verdict": "ok"}),
        patch("backend.app.graph.nodes.material_ingestor.extract_text", return_value="자료 텍스트"),
        patch(
            "backend.app.graph.nodes.material_ingestor.summarize",
            return_value="요약",
        ),
    )


@pytest.mark.asyncio
async def test_full_flow_fill_apply_download(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    try:
        client.post(
            "/api/upload",
            data={"session_id": sid, "kind": "form"},
            files={"file": ("sample.hwpx", _FIXTURE.read_bytes(), "application/octet-stream")},
        )
        client.post(
            "/api/upload",
            data={"session_id": sid, "kind": "material"},
            files={"file": ("cv.txt", b"researcher info", "text/plain")},
        )

        patches = _solar_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            r = client.post(f"/api/sessions/{sid}/fill")
        assert r.status_code == 200

        state = store._sessions[sid].graph_state
        assert state is not None
        assert state.drafts, "drafts should be generated"
        assert all(d.locked is False for d in state.drafts)

        target_id = next(
            (
                d.item_id
                for d in state.drafts
                if not any(it.item_id == d.item_id and it.is_pii for it in state.form_doc.items)
            ),
            None,
        )
        assert target_id is not None

        r = client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": target_id})
        assert r.status_code == 200
        assert r.json()["locked"] is True

        r = client.get(f"/api/sessions/{sid}/output.hwpx")
        assert r.status_code == 200
        assert r.content[:2] == b"PK"
    finally:
        await store.delete(sid)
