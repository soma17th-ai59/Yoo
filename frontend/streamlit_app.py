"""HwpAgent — Streamlit chat UI.

Talks to the FastAPI backend (BACKEND_URL env var, default http://localhost:8000).
Sessions are server-side and in-memory only — nothing persists to disk.
"""

from __future__ import annotations

import json
import os
from typing import Iterator

import httpx
import streamlit as st


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


st.set_page_config(page_title="HwpAgent", page_icon=":page_facing_up:", layout="wide")
st.title("HwpAgent — 양식 자동 채우기")


# --- session state ---------------------------------------------------------

_DEFAULTS = {
    "session_id": None,
    "messages": [],
    "form_doc": None,
    "drafts": [],
    "download_url": None,
    "pending_question": None,
    "uploaded_form": None,
    "uploaded_materials": [],
}
for key, default in _DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default


# --- backend helpers -------------------------------------------------------


def _create_session() -> str:
    r = httpx.post(f"{BACKEND_URL}/api/sessions", timeout=10.0)
    r.raise_for_status()
    return r.json()["session_id"]


def _upload(kind: str, name: str, data: bytes) -> None:
    sid = st.session_state.session_id
    r = httpx.post(
        f"{BACKEND_URL}/api/upload",
        data={"session_id": sid, "kind": kind},
        files={"file": (name, data, "application/octet-stream")},
        timeout=30.0,
    )
    r.raise_for_status()


def _stream_chat(message: str) -> Iterator[tuple[str, str]]:
    sid = st.session_state.session_id
    with httpx.stream(
        "POST",
        f"{BACKEND_URL}/api/chat",
        json={"session_id": sid, "message": message},
        timeout=120.0,
    ) as r:
        r.raise_for_status()
        event = "message"
        data: list[str] = []
        for raw in r.iter_lines():
            line = raw.rstrip("\r")
            if line == "":
                if data:
                    yield event, "\n".join(data)
                event = "message"
                data = []
                continue
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data.append(line.split(":", 1)[1].strip())
        if data:
            yield event, "\n".join(data)


def _reset_state() -> None:
    for key, default in _DEFAULTS.items():
        if key == "session_id":
            continue
        st.session_state[key] = default if not isinstance(default, list) else list(default)


# --- sidebar ---------------------------------------------------------------

with st.sidebar:
    st.header("세션")
    if st.button("▶ 새 세션", use_container_width=True):
        st.session_state.session_id = _create_session()
        _reset_state()
        st.rerun()

    if st.session_state.session_id:
        st.caption(f"session: `{st.session_state.session_id[:8]}…`")
    else:
        st.caption("새 세션 버튼으로 시작하세요.")

    st.divider()
    st.subheader("양식 (.hwpx)")
    form_file = st.file_uploader("양식 파일", type=["hwpx"], key="form_uploader")
    if (
        form_file is not None
        and st.session_state.session_id
        and form_file.name != st.session_state.uploaded_form
    ):
        _upload("form", form_file.name, form_file.read())
        st.session_state.uploaded_form = form_file.name
        st.success(f"양식 업로드 완료: {form_file.name}")

    st.subheader("자료 (CV / 계획서 / 보고서)")
    mat_files = st.file_uploader(
        "자료 파일 (PDF/docx/txt/hwpx)",
        type=["pdf", "docx", "txt", "hwpx"],
        accept_multiple_files=True,
        key="material_uploader",
    )
    if mat_files and st.session_state.session_id:
        for f in mat_files:
            if f.name not in st.session_state.uploaded_materials:
                _upload("material", f.name, f.read())
                st.session_state.uploaded_materials.append(f.name)
        if st.session_state.uploaded_materials:
            st.caption("업로드된 자료: " + ", ".join(st.session_state.uploaded_materials))


# --- form-structure visualization ------------------------------------------

if st.session_state.form_doc:
    fd = st.session_state.form_doc
    items = fd.get("items", [])
    pii_count = sum(1 for it in items if it.get("is_pii"))
    with st.expander(
        f"양식 구조 요약 — 항목 {len(items)}개 (PII {pii_count}개, 표 {len(fd.get('tables', []))}개)"
    ):
        for sec in fd.get("sections", []):
            st.markdown(f"**{sec}**")
            for it in items:
                if it.get("section") == sec:
                    badge = " 🔒(PII)" if it.get("is_pii") else ""
                    st.markdown(f"- `{it.get('item_id')}` {it.get('label')}{badge}")


# --- chat thread -----------------------------------------------------------

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])


def _process_stream(message: str) -> None:
    """Consume an SSE stream and update session state."""
    status = st.empty()
    try:
        for event, data in _stream_chat(message):
            payload = json.loads(data) if data else None
            if event == "intent":
                status.info(f"의도: `{payload['intent']}`")
            elif event == "node_started":
                status.write(f"… {payload['node']}")
            elif event == "form_parsed":
                st.session_state.form_doc = payload
            elif event == "preview":
                st.session_state.drafts = payload or []
            elif event == "pending_question":
                st.session_state.pending_question = payload
            elif event == "done":
                st.session_state.download_url = payload.get("download_url") if payload else None
                status.success("완료")
            elif event == "error":
                st.error(f"오류: {payload.get('error') if payload else 'unknown'}")
    except Exception as exc:
        st.error(f"통신 오류: {exc}")


user_msg = st.chat_input("무엇을 도와드릴까요?")
if user_msg:
    if not st.session_state.session_id:
        st.warning("먼저 ▶ 새 세션 버튼으로 세션을 시작하세요.")
    else:
        st.session_state.messages.append({"role": "user", "content": user_msg})
        with st.chat_message("user"):
            st.markdown(user_msg)
        with st.chat_message("assistant"):
            _process_stream(user_msg)
            if st.session_state.drafts:
                summary = f"초안 {len(st.session_state.drafts)}개 생성"
                if st.session_state.download_url:
                    summary += " — 우측 다운로드 버튼을 사용하세요."
                st.markdown(summary)
                st.session_state.messages.append({"role": "assistant", "content": summary})


# --- drafts preview blocks -------------------------------------------------

if st.session_state.drafts:
    st.subheader("작성된 초안")
    for d in st.session_state.drafts:
        item_id = d.get("item_id", "?")
        with st.container(border=True):
            cols = st.columns([5, 1, 1, 1])
            cols[0].markdown(f"**{item_id}**")
            cols[1].button("✓ 적용", key=f"apply_{item_id}")
            cols[2].button("✏ 수정", key=f"edit_{item_id}")
            cols[3].button("🔁 다시", key=f"redo_{item_id}")
            st.write(d.get("text", ""))
            citations = d.get("citations", [])
            if citations:
                st.caption(f"근거: {', '.join(citations)}")


# --- pending question ------------------------------------------------------

if st.session_state.pending_question:
    pq = st.session_state.pending_question
    with st.container(border=True):
        st.warning(f"❓ {pq.get('question', '추가 정보가 필요합니다.')}")
        ans_key = f"answer_{pq.get('item_id', 'q')}"
        ans = st.text_input("답변", key=ans_key)
        if st.button("답변 전송", key=f"send_{pq.get('item_id', 'q')}"):
            st.session_state.pending_question = None
            st.session_state.messages.append({"role": "user", "content": ans})
            _process_stream(ans)
            st.rerun()


# --- download + PII banner -------------------------------------------------

if st.session_state.download_url:
    fd = st.session_state.form_doc or {}
    pii_items = [it for it in fd.get("items", []) if it.get("is_pii")]
    if pii_items:
        st.info(
            f"⚠ {len(pii_items)}개 PII 항목은 직접 작성이 필요합니다 "
            "(`[본인 직접 입력]` 표시)."
        )
    st.link_button(
        "📥 출력 .hwpx 다운로드",
        f"{BACKEND_URL}{st.session_state.download_url}",
    )
