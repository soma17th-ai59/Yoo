"""In-memory session store. No disk writes. Thread-safe via per-session asyncio locks."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from backend.app.graph.state import GraphState

_TTL_SECONDS = 2 * 60 * 60  # 2 hours


@dataclass
class Session:
    session_id: str
    created_at: float = field(default_factory=time.time)
    form_bytes: Optional[bytes] = None
    material_files: list[tuple[str, bytes]] = field(default_factory=list)
    rendered_bytes: Optional[bytes] = None
    graph_state: Optional[GraphState] = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionStore:
    """In-memory session store. No disk writes. Thread-safe via per-session locks."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._global_lock = asyncio.Lock()

    async def create(self) -> str:
        """Create a new session; return its session_id."""
        session_id = str(uuid.uuid4())
        async with self._global_lock:
            self._sessions[session_id] = Session(session_id=session_id)
        return session_id

    async def get(self, session_id: str) -> Optional[Session]:
        """Return session if exists and not expired; else None."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if self._is_expired(session):
            return None
        return session

    async def put_form_bytes(self, session_id: str, data: bytes) -> None:
        """Store (or replace) the form bytes for this session."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        async with session._lock:
            session.form_bytes = data

    async def put_material_file(self, session_id: str, filename: str, data: bytes) -> None:
        """Append a new material file."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        async with session._lock:
            session.material_files.append((filename, data))

    async def save_state(self, session_id: str, state: GraphState) -> None:
        """Persist graph state snapshot."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        async with session._lock:
            session.graph_state = state

    async def put_rendered_bytes(self, session_id: str, data: bytes) -> None:
        """Store the rendered output bytes."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        async with session._lock:
            session.rendered_bytes = data

    async def delete(self, session_id: str) -> None:
        """Remove session and free all bytes."""
        async with self._global_lock:
            self._sessions.pop(session_id, None)

    # --- SessionProvider Protocol methods (sync, for LangGraph compatibility) ---

    def get_form_bytes(self, session_id: str) -> bytes:
        """Sync accessor for LangGraph SessionProvider protocol."""
        s = self._sessions.get(session_id)
        return s.form_bytes if s else b""

    def get_material_files(self, session_id: str) -> list[tuple[str, bytes]]:
        """Sync accessor for LangGraph SessionProvider protocol."""
        s = self._sessions.get(session_id)
        return list(s.material_files) if s else []

    def _is_expired(self, session: Session) -> bool:
        return (time.time() - session.created_at) > _TTL_SECONDS


store = SessionStore()
