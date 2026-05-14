"""Unit tests for backend.app.session.SessionStore."""

import asyncio
import time

from backend.app.graph.state import GraphState
from backend.app.session import SessionStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> SessionStore:
    return SessionStore()


# ---------------------------------------------------------------------------
# 1. create() returns unique IDs
# ---------------------------------------------------------------------------


async def test_create_returns_unique_ids():
    store = _make_store()
    id1 = await store.create()
    id2 = await store.create()
    assert id1 != id2
    assert isinstance(id1, str)
    assert isinstance(id2, str)


# ---------------------------------------------------------------------------
# 2. get() returns None for unknown ID
# ---------------------------------------------------------------------------


async def test_get_returns_none_for_unknown_id():
    store = _make_store()
    result = await store.get("nonexistent")
    assert result is None


# ---------------------------------------------------------------------------
# 3. put_form_bytes stores and sync get_form_bytes retrieves
# ---------------------------------------------------------------------------


async def test_put_form_bytes_stores_and_retrieves():
    store = _make_store()
    sid = await store.create()
    data = b"\x00\x01\x02FORM"
    await store.put_form_bytes(sid, data)
    assert store.get_form_bytes(sid) == data


# ---------------------------------------------------------------------------
# 4. put_form_bytes replaces previous value
# ---------------------------------------------------------------------------


async def test_put_form_bytes_replaces_previous():
    store = _make_store()
    sid = await store.create()
    await store.put_form_bytes(sid, b"first")
    await store.put_form_bytes(sid, b"second")
    assert store.get_form_bytes(sid) == b"second"


# ---------------------------------------------------------------------------
# 5. put_material_file appends; get_material_files returns all in order
# ---------------------------------------------------------------------------


async def test_put_material_file_appends():
    store = _make_store()
    sid = await store.create()
    await store.put_material_file(sid, "a.pdf", b"aaa")
    await store.put_material_file(sid, "b.pdf", b"bbb")
    await store.put_material_file(sid, "c.txt", b"ccc")
    files = store.get_material_files(sid)
    assert len(files) == 3
    assert files[0] == ("a.pdf", b"aaa")
    assert files[1] == ("b.pdf", b"bbb")
    assert files[2] == ("c.txt", b"ccc")


# ---------------------------------------------------------------------------
# 6. save_state and retrieve via get()
# ---------------------------------------------------------------------------


async def test_save_state_and_retrieve():
    store = _make_store()
    sid = await store.create()
    state = GraphState(session_id=sid, errors=["테스트 에러"])
    await store.save_state(sid, state)
    session = await store.get(sid)
    assert session is not None
    assert session.graph_state is not None
    assert session.graph_state.errors == ["테스트 에러"]


# ---------------------------------------------------------------------------
# 7. put_rendered_bytes stores bytes on session
# ---------------------------------------------------------------------------


async def test_put_rendered_bytes():
    store = _make_store()
    sid = await store.create()
    rendered = b"\xff\xferendered"
    store.put_rendered_bytes(sid, rendered)
    session = await store.get(sid)
    assert session is not None
    assert session.rendered_bytes == rendered


async def test_updated_at_advances_on_mutation():
    store = _make_store()
    sid = await store.create()
    session = await store.get(sid)
    assert session is not None
    initial_updated_at = session.updated_at

    await asyncio.sleep(0.01)
    await store.put_form_bytes(sid, b"form", "f.hwpx")
    session = await store.get(sid)
    assert session is not None
    assert session.updated_at > initial_updated_at
    assert session.form_filename == "f.hwpx"


async def test_list_sessions_returns_most_recent_first():
    store = _make_store()
    first = await store.create()
    second = await store.create()

    await asyncio.sleep(0.01)
    await store.put_material_file(first, "cv.txt", b"data")

    sessions = store.list_sessions()
    assert [session.session_id for session in sessions] == [first, second]


# ---------------------------------------------------------------------------
# 8. delete removes the session
# ---------------------------------------------------------------------------


async def test_delete_removes_session():
    store = _make_store()
    sid = await store.create()
    assert await store.get(sid) is not None
    await store.delete(sid)
    assert await store.get(sid) is None


# ---------------------------------------------------------------------------
# 9. delete of nonexistent ID is a no-op
# ---------------------------------------------------------------------------


async def test_delete_nonexistent_is_noop():
    store = _make_store()
    await store.delete("does-not-exist")  # must not raise


# ---------------------------------------------------------------------------
# 10. TTL expiry: get() returns None for sessions older than 2 hours
# ---------------------------------------------------------------------------


async def test_ttl_expired_returns_none():
    store = _make_store()
    sid = await store.create()
    session = store._sessions[sid]
    # Backdating created_at to more than 2 hours ago
    session.created_at = time.time() - (2 * 60 * 60 + 1)
    result = await store.get(sid)
    assert result is None


# ---------------------------------------------------------------------------
# 11. SessionProvider protocol — sync methods work without an event loop
# ---------------------------------------------------------------------------


async def test_session_provider_protocol_sync():
    store = _make_store()
    sid = await store.create()
    await store.put_form_bytes(sid, b"form_data")
    await store.put_material_file(sid, "cv.pdf", b"cv_data")

    # Sync calls must return correct data without await
    form_bytes = store.get_form_bytes(sid)
    material_files = store.get_material_files(sid)

    assert form_bytes == b"form_data"
    assert material_files == [("cv.pdf", b"cv_data")]

    # Unknown session returns safe defaults
    assert store.get_form_bytes("unknown") == b""
    assert store.get_material_files("unknown") == []


# ---------------------------------------------------------------------------
# 12. Concurrent puts are safe — all 10 files present after gather
# ---------------------------------------------------------------------------


async def test_concurrent_puts_are_safe():
    store = _make_store()
    sid = await store.create()

    async def _put(i: int) -> None:
        await store.put_material_file(sid, f"file_{i}.txt", f"data_{i}".encode())

    await asyncio.gather(*(_put(i) for i in range(10)))

    files = store.get_material_files(sid)
    assert len(files) == 10
    filenames = {name for name, _ in files}
    assert filenames == {f"file_{i}.txt" for i in range(10)}
