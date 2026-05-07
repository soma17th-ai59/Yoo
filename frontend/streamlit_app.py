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
import streamlit.components.v1 as components


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


st.set_page_config(page_title="HwpAgent", page_icon=":page_facing_up:", layout="wide")
st.title("HwpAgent — 양식 자동 채우기")


# Neutralize Streamlit's single-letter hotkeys (C / R / S / ?) when a
# modifier is held, so Ctrl+C / Cmd+C / Ctrl+R behave as the user expects
# (copy / refresh) instead of triggering Clear-cache or Rerun.
# We bind on multiple targets in capture phase, run on every event type
# Streamlit might use, and re-attach periodically so the listener survives
# Streamlit's DOM rebuilds.
components.html(
    """
    <script>
      (function () {
        function block(e) {
          if (e.ctrlKey || e.metaKey || e.altKey) {
            e.stopImmediatePropagation();
          }
        }
        var ATTACHED = "__hwpagent_hotkey_block";
        function attach() {
          try {
            var pw = window.parent;
            var pd = pw && pw.document;
            if (!pd) return;
            var targets = [pw, pd, pd.body, pd.documentElement].filter(Boolean);
            for (var i = 0; i < targets.length; i++) {
              var t = targets[i];
              if (t[ATTACHED]) continue;
              ["keydown", "keypress", "keyup"].forEach(function (evt) {
                t.addEventListener(evt, block, { capture: true });
              });
              t[ATTACHED] = true;
            }
          } catch (err) {}
        }
        attach();
        // Re-attach in case Streamlit rebuilds the body
        setInterval(attach, 1500);
      })();
    </script>
    """,
    height=0,
)


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
    # Clear per-draft action state from prior session
    for key in list(st.session_state.keys()):
        if key.startswith(
            (
                "applied_",
                "editing_",
                "edit_text_",
                "chatting_",
                "chat_history_",
                "chat_input_",
                "apply_warn_",
            )
        ):
            del st.session_state[key]


def _save_draft_edit(item_id: str, text: str) -> bool:
    """PUT the edited draft to the backend and re-render. Returns True on success."""
    sid = st.session_state.session_id
    try:
        r = httpx.put(
            f"{BACKEND_URL}/api/sessions/{sid}/drafts",
            json={"item_id": item_id, "text": text},
            timeout=30.0,
        )
        r.raise_for_status()
    except Exception as exc:
        st.error(f"저장 실패: {exc}")
        return False
    for di in st.session_state.drafts:
        if di.get("item_id") == item_id:
            di["text"] = text
            break
    return True


def _item_chat(item_id: str, message: str, history: list[dict]) -> str | None:
    """POST a turn to the per-item conversation endpoint and return the reply."""
    sid = st.session_state.session_id
    try:
        r = httpx.post(
            f"{BACKEND_URL}/api/sessions/{sid}/item-chat",
            json={"item_id": item_id, "message": message, "history": history},
            timeout=120.0,
        )
        r.raise_for_status()
        return r.json().get("reply")
    except Exception as exc:
        st.error(f"대화 오류: {exc}")
        return None


_NEEDS_INFO_PREFIX = "[추가 정보 필요]"


def _is_unfilled(text: str) -> bool:
    return text.strip().startswith(_NEEDS_INFO_PREFIX)


from frontend.extract_body import extract_body as _extract_body  # noqa: E402


# --- sidebar ---------------------------------------------------------------

with st.sidebar:
    st.header("세션")
    if st.button("🆕 새 세션 (현재 세션 초기화)", use_container_width=True, type="primary"):
        st.session_state.session_id = _create_session()
        _reset_state()
        st.rerun()

    if st.session_state.session_id:
        st.caption(f"session: `{st.session_state.session_id[:8]}…`")
    else:
        st.caption("새 세션 버튼으로 시작하세요.")
    st.caption(
        "ℹ️ 세션은 메모리에만 저장됩니다 (디스크 저장 없음). "
        "백엔드를 재시작하면 모든 세션이 초기화되니, 작성 중에는 백엔드 터미널을 그대로 두세요."
    )

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
    table_count = len(fd.get("tables", []))

    # Group items by their actual section path (resilient to mismatched
    # sections list — falls back to the section value on each item).
    by_section: dict[str, list[dict]] = {}
    for it in items:
        sec = it.get("section") or "(섹션 없음)"
        by_section.setdefault(sec, []).append(it)

    with st.expander(
        f"양식 구조 요약 — 항목 {len(items)}개 (PII {pii_count}개, 표 {table_count}개)",
        expanded=False,
    ):
        if not items:
            st.caption("항목이 추출되지 않았습니다. 양식을 다시 업로드해 주세요.")
        for sec, sec_items in by_section.items():
            st.markdown(f"**{sec}**  &nbsp;_{len(sec_items)}개_")
            for it in sec_items:
                badge = " 🔒(PII)" if it.get("is_pii") else ""
                st.markdown(f"- {it.get('label', '?')}{badge}  &nbsp;`{it.get('item_id')}`")
        for tbl in fd.get("tables", []):
            headers = ", ".join(tbl.get("headers", []))
            st.markdown(
                f"**표 `{tbl.get('table_id')}`**  &nbsp;_{tbl.get('row_count', 0)}행_  &nbsp; 헤더: {headers}"
            )


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


def _item_label(item_id: str) -> str:
    fd = st.session_state.form_doc or {}
    for it in fd.get("items", []):
        if it.get("item_id") == item_id:
            return it.get("label", item_id)
    return item_id


if st.session_state.drafts:
    st.subheader("작성된 초안")
    for d in st.session_state.drafts:
        item_id = d.get("item_id", "?")
        applied = st.session_state.get(f"applied_{item_id}", False)
        editing = st.session_state.get(f"editing_{item_id}", False)
        chatting = st.session_state.get(f"chatting_{item_id}", False)
        label = _item_label(item_id)
        unfilled = _is_unfilled(d.get("text", ""))

        with st.container(border=True):
            badge = ""
            if applied:
                badge = "✅"
            elif unfilled:
                badge = "⚠️ 미작성"
            cols = st.columns([4, 1, 1, 1, 1])
            cols[0].markdown(f"**{label}** {badge}")

            if cols[1].button("✓ 적용", key=f"apply_{item_id}", disabled=applied or editing):
                if unfilled:
                    st.session_state[f"apply_warn_{item_id}"] = True
                else:
                    st.session_state[f"applied_{item_id}"] = True
                    st.session_state.pop(f"apply_warn_{item_id}", None)
                st.rerun()

            if cols[2].button("✏ 수정", key=f"edit_{item_id}", disabled=applied):
                st.session_state[f"editing_{item_id}"] = not editing
                st.rerun()

            if cols[3].button("🔁 다시", key=f"redo_{item_id}", disabled=applied or editing):
                redo_msg = f"{label} 항목을 다시 써줘"
                st.session_state.messages.append({"role": "user", "content": redo_msg})
                with st.chat_message("assistant"):
                    _process_stream(redo_msg)
                st.rerun()

            if cols[4].button("💬 대화", key=f"chat_{item_id}", disabled=applied):
                st.session_state[f"chatting_{item_id}"] = not chatting
                st.rerun()

            if st.session_state.pop(f"apply_warn_{item_id}", False):
                st.warning(
                    f"⚠ '{label}' 항목이 아직 비어 있습니다 (`[추가 정보 필요]`). "
                    "💬 대화로 채우거나 ✏ 수정으로 직접 입력한 뒤 적용해 주세요."
                )

            if editing:
                new_text = st.text_area(
                    "본문 수정",
                    value=d.get("text", ""),
                    key=f"edit_text_{item_id}",
                    height=160,
                )
                save_col, cancel_col = st.columns([1, 1])
                if save_col.button("저장", key=f"save_{item_id}"):
                    if _save_draft_edit(item_id, new_text):
                        st.session_state[f"editing_{item_id}"] = False
                        st.rerun()
                if cancel_col.button("취소", key=f"cancel_{item_id}"):
                    st.session_state[f"editing_{item_id}"] = False
                    st.rerun()
            else:
                st.write(d.get("text", ""))

            citations = d.get("citations", [])
            if citations:
                st.caption(f"근거: {', '.join(citations)}")

            if chatting:
                hist_key = f"chat_history_{item_id}"
                history = st.session_state.get(hist_key, [])
                with st.container(border=True):
                    st.markdown(f"💬 **'{label}' 항목과 대화하기** — 정보를 알려주시면 본문을 함께 만들어 드립니다.")
                    for m in history:
                        with st.chat_message(m["role"]):
                            # Render as normal-body-sized plain text (no markdown
                            # heading / bold escalation) so LLM responses stay
                            # consistent with the rest of the page.
                            import html as _html

                            safe = _html.escape(m["content"]).replace("\n", "<br>")
                            st.markdown(
                                f'<div style="font-size: 0.95rem; line-height: 1.55;">{safe}</div>',
                                unsafe_allow_html=True,
                            )

                    with st.form(f"chat_form_{item_id}", clear_on_submit=True):
                        typed = st.text_input(
                            "메시지", key=f"chat_input_{item_id}", label_visibility="collapsed",
                            placeholder="이 항목에 대한 정보를 입력하거나 질문하세요…",
                        )
                        send = st.form_submit_button("전송")
                    if send and typed:
                        history.append({"role": "user", "content": typed})
                        with st.spinner("응답 생성 중…"):
                            reply = _item_chat(item_id, typed, history[:-1])
                        if reply:
                            history.append({"role": "assistant", "content": reply})
                        st.session_state[hist_key] = history
                        st.rerun()

                    if history:
                        last_assistant = next(
                            (m["content"] for m in reversed(history) if m["role"] == "assistant"),
                            None,
                        )
                        body_preview = _extract_body(last_assistant) if last_assistant else ""
                        if body_preview and body_preview != (last_assistant or "").strip():
                            with st.expander("적용될 본문 미리보기", expanded=False):
                                st.write(body_preview)
                        action_cols = st.columns([2, 1, 2])
                        if action_cols[0].button(
                            "🟢 본문만 추출해 적용",
                            key=f"apply_chat_{item_id}",
                            disabled=not body_preview,
                        ):
                            if body_preview and _save_draft_edit(item_id, body_preview):
                                st.session_state[f"chatting_{item_id}"] = False
                                st.session_state[f"applied_{item_id}"] = True
                                st.session_state[hist_key] = []
                                st.rerun()
                        if action_cols[1].button("대화 닫기", key=f"close_chat_{item_id}"):
                            st.session_state[f"chatting_{item_id}"] = False
                            st.rerun()


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


# --- 직접 작성이 필요한 항목 안내 ------------------------------------------


def _needs_manual_entry() -> tuple[list[dict], list[dict]]:
    """Return (pii_items, gap_items) — items the user needs to fill in manually.

    pii_items   — flagged PII (Generator never writes these).
    gap_items   — non-PII items with no draft yet (Planner didn't have enough
                  to start, or Generator skipped them via needs_question).
    """
    fd = st.session_state.form_doc or {}
    items = fd.get("items", [])
    drafted_ids = {d.get("item_id") for d in st.session_state.drafts}

    pii_items = [it for it in items if it.get("is_pii")]
    gap_items = [
        it
        for it in items
        if not it.get("is_pii") and it.get("item_id") not in drafted_ids
    ]
    return pii_items, gap_items


if st.session_state.form_doc and (st.session_state.drafts or st.session_state.download_url):
    pii_items, gap_items = _needs_manual_entry()
    if pii_items or gap_items:
        with st.container(border=True):
            st.markdown("### ✍️ 직접 작성이 필요한 항목")
            if pii_items:
                st.markdown("**🔒 개인정보 (AI는 작성하지 않습니다 — `[본인 직접 입력]`로 비워둠)**")
                for it in pii_items:
                    st.markdown(f"- {it.get('label', '?')}")
            if gap_items:
                st.markdown("**❓ 자료에 단서가 부족한 항목 (추가 정보 또는 직접 작성 필요)**")
                for it in gap_items:
                    st.markdown(f"- {it.get('label', '?')}")
                st.caption(
                    "💡 채팅으로 정보를 더 알려주시거나, 다운로드한 .hwpx에서 직접 채우세요."
                )


# --- download --------------------------------------------------------------

if st.session_state.download_url:
    unfilled_drafts = [
        d for d in st.session_state.drafts if _is_unfilled(d.get("text", ""))
    ]
    if unfilled_drafts:
        names = "\n".join(f"  • {_item_label(d.get('item_id'))}" for d in unfilled_drafts)
        st.warning(
            f"⚠ 다음 {len(unfilled_drafts)}개 항목이 아직 비어 있습니다 (`[추가 정보 필요]`). "
            f"지금 다운로드하면 해당 항목은 비어 있는 채로 저장됩니다.\n\n{names}\n\n"
            "💬 대화 또는 ✏ 수정으로 채운 뒤 다시 다운로드하세요."
        )
    st.link_button(
        "📥 출력 .hwpx 다운로드",
        f"{BACKEND_URL}{st.session_state.download_url}",
    )
