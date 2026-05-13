"""HwpAgent — Streamlit chat UI.

Talks to the FastAPI backend (BACKEND_URL env var, default http://localhost:8000).
Sessions are server-side and in-memory only — nothing persists to disk.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

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
    "uploaded_form": None,
    "uploaded_materials": [],
    "fill_requested": False,
}
for key, default in _DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default


# --- backend helpers -------------------------------------------------------


def _create_session() -> str:
    r = httpx.post(f"{_current_backend()}/api/sessions", timeout=10.0)
    r.raise_for_status()
    return r.json()["session_id"]


def _upload(kind: str, name: str, data: bytes) -> None:
    sid = st.session_state.session_id
    r = httpx.post(
        f"{_current_backend()}/api/upload",
        data={"session_id": sid, "kind": kind},
        files={"file": (name, data, "application/octet-stream")},
        timeout=30.0,
    )
    r.raise_for_status()


def _current_backend() -> str:
    return BACKEND_URL


def _stream_fill() -> Iterator[tuple[str, str]]:
    sid = st.session_state.session_id
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
    with httpx.stream(
        "POST",
        f"{_current_backend()}/api/sessions/{sid}/fill",
        timeout=timeout,
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
    for key in list(st.session_state.keys()):
        if key.startswith(
            (
                "editing_",
                "edit_text_",
                "chatting_",
                "chat_history_",
                "chat_input_",
                "apply_warn_",
            )
        ):
            del st.session_state[key]


def _replace_draft(updated: dict) -> None:
    for i, d in enumerate(st.session_state.drafts):
        if d.get("item_id") == updated["item_id"]:
            st.session_state.drafts[i] = updated
            return


def _apply_item(item_id: str) -> bool:
    sid = st.session_state.session_id
    try:
        r = httpx.post(
            f"{_current_backend()}/api/sessions/{sid}/items/apply",
            json={"item_id": item_id},
            timeout=10.0,
        )
        r.raise_for_status()
        _replace_draft(r.json())
        return True
    except Exception as exc:
        st.error(f"적용 실패: {exc}")
        return False


def _unlock_item(item_id: str) -> bool:
    sid = st.session_state.session_id
    try:
        r = httpx.post(
            f"{_current_backend()}/api/sessions/{sid}/items/unlock",
            json={"item_id": item_id},
            timeout=10.0,
        )
        r.raise_for_status()
        _replace_draft(r.json())
        return True
    except Exception as exc:
        st.error(f"해제 실패: {exc}")
        return False


def _save_draft_edit(item_id: str, text: str) -> bool:
    """PUT the edited draft to the backend. Returns True on success."""
    sid = st.session_state.session_id
    try:
        r = httpx.put(
            f"{_current_backend()}/api/sessions/{sid}/drafts",
            json={"item_id": item_id, "text": text},
            timeout=30.0,
        )
        r.raise_for_status()
    except Exception as exc:
        st.error(f"저장 실패: {exc}")
        return False
    try:
        _replace_draft(r.json())
    except Exception:
        for di in st.session_state.drafts:
            if di.get("item_id") == item_id:
                di["text"] = text
                break
    return True


def _fetch_output_bytes(*, include_unlocked: bool = False) -> bytes | None:
    sid = st.session_state.session_id
    params = {"include_unlocked": "true"} if include_unlocked else None
    try:
        r = httpx.get(
            f"{_current_backend()}/api/sessions/{sid}/output.hwpx",
            params=params,
            timeout=60.0,
        )
        r.raise_for_status()
        return r.content
    except Exception as exc:
        st.error(f"다운로드 실패: {exc}")
        return None


def _item_chat(item_id: str, message: str, history: list[dict]) -> str | None:
    """POST a turn to the per-item conversation endpoint and return the reply."""
    sid = st.session_state.session_id
    try:
        r = httpx.post(
            f"{_current_backend()}/api/sessions/{sid}/item-chat",
            json={"item_id": item_id, "message": message, "history": history},
            timeout=120.0,
        )
        r.raise_for_status()
        return r.json().get("reply")
    except Exception as exc:
        st.error(f"대화 오류: {exc}")
        return None


_STATUS_BADGES: dict[str, str] = {
    "needs_review": "🟡 검토 필요",
    "needs_info": "🔵 추가 정보 필요",
    "needs_check": "🔴 확인 필요",
    "pii": "🔒 개인정보 (직접 입력)",
}


def _status_of(d: dict) -> str:
    return d.get("status") or "ok"


def _is_pii_draft(d: dict) -> bool:
    return bool(d.get("is_pii")) or _status_of(d) == "pii"


def _is_unfilled(d: dict) -> bool:
    s = _status_of(d)
    if s in {"needs_info", "needs_check", "pii"}:
        return not (d.get("text") or "").strip()
    return False


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

    st.divider()
    st.subheader("자동 채우기")
    can_fill = bool(st.session_state.uploaded_form) and bool(st.session_state.uploaded_materials)
    if st.button(
        "▶ 양식 자동 채우기 시작",
        use_container_width=True,
        disabled=not can_fill,
        type="primary" if can_fill else "secondary",
    ):
        st.session_state.fill_requested = True
        st.rerun()
    if not can_fill:
        st.caption("양식과 자료를 모두 업로드하면 활성화됩니다.")

    locked_count = sum(1 for d in st.session_state.drafts if d.get("locked"))
    total_count = len(st.session_state.drafts)
    st.caption(f"적용된 항목 {locked_count} / 전체 {total_count}")
    if st.button(
        "📥 출력 .hwpx 다운로드",
        use_container_width=True,
        disabled=locked_count == 0,
        key="download_btn",
    ):
        data = _fetch_output_bytes()
        if data:
            st.download_button(
                "📁 파일 저장",
                data=data,
                file_name="output.hwpx",
                mime="application/vnd.hancom.hwpx",
                key="download_save_btn",
                use_container_width=True,
            )

    if st.button(
        "⬇ 미적용 초안 포함 다운로드",
        use_container_width=True,
        disabled=not st.session_state.form_doc,
        key="download_force_btn",
        help="적용(✓) 안 한 항목도 생성된 초안 텍스트로 채워서 .hwpx를 받습니다. PII 항목은 사용자가 입력한 내용 그대로 들어갑니다.",
    ):
        data = _fetch_output_bytes(include_unlocked=True)
        if data:
            st.download_button(
                "📁 파일 저장 (미적용 초안 포함)",
                data=data,
                file_name="output.hwpx",
                mime="application/vnd.hancom.hwpx",
                key="download_force_save_btn",
                use_container_width=True,
            )


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


# --- fill request handler --------------------------------------------------

if st.session_state.fill_requested:
    st.session_state.fill_requested = False
    status = st.empty()
    try:
        for event, raw in _stream_fill():
            payload = json.loads(raw) if raw else None
            if event == "node_started":
                status.write(f"… {payload['node']}")
            elif event == "form_parsed":
                st.session_state.form_doc = payload
            elif event == "preview":
                st.session_state.drafts = payload or []
            elif event == "done":
                count = (payload or {}).get("draft_count", 0)
                status.success(f"초안 {count}개 생성")
            elif event == "error":
                err = (payload or {}).get("error", "unknown")
                st.error(f"채우기 오류: {err}")
    except Exception as exc:
        st.error(f"통신 오류: {exc}")
    st.rerun()


# --- chat thread -----------------------------------------------------------

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])


def _process_chat(message: str) -> None:
    sid = st.session_state.session_id
    try:
        r = httpx.post(
            f"{_current_backend()}/api/chat",
            json={"session_id": sid, "message": message},
            timeout=120.0,
        )
        r.raise_for_status()
        reply = r.json().get("reply", "")
    except Exception as exc:
        st.error(f"통신 오류: {exc}")
        return
    st.markdown(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})


user_msg = st.chat_input("무엇을 도와드릴까요?")
if user_msg:
    if not st.session_state.session_id:
        st.warning("먼저 ▶ 새 세션 버튼으로 세션을 시작하세요.")
    else:
        st.session_state.messages.append({"role": "user", "content": user_msg})
        with st.chat_message("user"):
            st.markdown(user_msg)
        with st.chat_message("assistant"):
            _process_chat(user_msg)


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
        locked = bool(d.get("locked", False))
        editing = st.session_state.get(f"editing_{item_id}", False)
        chatting = st.session_state.get(f"chatting_{item_id}", False)
        label = _item_label(item_id)
        status = _status_of(d)
        is_pii = _is_pii_draft(d)
        unfilled = _is_unfilled(d)
        text = d.get("text", "") or ""

        with st.container(border=True):
            badges: list[str] = []
            if locked:
                badges.append("🔒 적용됨")
            if status in _STATUS_BADGES:
                badges.append(_STATUS_BADGES[status])
            if not locked and not is_pii and unfilled:
                badges.append("⚠️ 미작성")
            badge = "  ".join(badges)

            if locked:
                cols = st.columns([5, 1])
                cols[0].markdown(f"**{label}**  {badge}")
                if cols[1].button("🔓 해제", key=f"unlock_{item_id}"):
                    if _unlock_item(item_id):
                        st.rerun()
                st.write(text if text else "_(빈 값)_")
                citations = d.get("citations", [])
                if citations and not is_pii:
                    st.caption(f"근거: {', '.join(citations)}")
                continue

            # PII items get only 적용/수정 (no 대화 — LLM path is blocked for PII).
            if is_pii:
                cols = st.columns([5, 1, 1])
                cols[0].markdown(f"**{label}**  {badge}")
                if cols[1].button("✓ 적용", key=f"apply_{item_id}", disabled=editing):
                    if not text.strip():
                        st.session_state[f"apply_warn_{item_id}"] = True
                        st.rerun()
                    elif _apply_item(item_id):
                        st.rerun()
                if cols[2].button("✏ 수정", key=f"edit_{item_id}"):
                    st.session_state[f"editing_{item_id}"] = not editing
                    st.rerun()
                st.caption("AI는 이 항목을 작성하지 않습니다. 직접 입력해 주세요.")
            else:
                cols = st.columns([4, 1, 1, 1])
                cols[0].markdown(f"**{label}**  {badge}")

                if cols[1].button("✓ 적용", key=f"apply_{item_id}", disabled=editing):
                    if unfilled:
                        st.session_state[f"apply_warn_{item_id}"] = True
                        st.rerun()
                    elif _apply_item(item_id):
                        st.rerun()

                if cols[2].button("✏ 수정", key=f"edit_{item_id}"):
                    st.session_state[f"editing_{item_id}"] = not editing
                    st.rerun()

                if cols[3].button("💬 대화", key=f"chat_{item_id}"):
                    st.session_state[f"chatting_{item_id}"] = not chatting
                    st.rerun()

            if st.session_state.pop(f"apply_warn_{item_id}", False):
                if is_pii:
                    st.warning(
                        f"⚠ '{label}' 항목이 비어 있습니다. ✏ 수정으로 직접 입력 후 적용해 주세요."
                    )
                else:
                    st.warning(
                        f"⚠ '{label}' 항목이 아직 비어 있습니다. "
                        "💬 대화로 채우거나 ✏ 수정으로 직접 입력한 뒤 적용해 주세요."
                    )

            if editing:
                edit_label = "직접 입력" if is_pii else "본문 수정"
                new_text = st.text_area(
                    edit_label,
                    value=text,
                    key=f"edit_text_{item_id}",
                    height=120 if is_pii else 160,
                    placeholder="여기에 입력…" if is_pii else "",
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
                if text:
                    st.write(text)
                elif is_pii:
                    st.write("_(미입력 — ✏ 수정으로 직접 입력하세요)_")
                else:
                    st.write("_(미작성)_")

            citations = d.get("citations", [])
            if citations and not is_pii:
                st.caption(f"근거: {', '.join(citations)}")

            if chatting:
                hist_key = f"chat_history_{item_id}"
                history = st.session_state.get(hist_key, [])
                with st.container(border=True):
                    st.markdown(
                        f"💬 **'{label}' 항목과 대화하기** — 정보를 알려주시면 본문을 함께 만들어 드립니다."
                    )
                    for m in history:
                        with st.chat_message(m["role"]):
                            import html as _html

                            safe = _html.escape(m["content"]).replace("\n", "<br>")
                            st.markdown(
                                f'<div style="font-size: 0.95rem; line-height: 1.55;">{safe}</div>',
                                unsafe_allow_html=True,
                            )

                    with st.form(f"chat_form_{item_id}", clear_on_submit=True):
                        typed = st.text_input(
                            "메시지",
                            key=f"chat_input_{item_id}",
                            label_visibility="collapsed",
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
                                if _apply_item(item_id):
                                    st.session_state[f"chatting_{item_id}"] = False
                                    st.session_state[hist_key] = []
                                    st.rerun()
                        if action_cols[1].button("대화 닫기", key=f"close_chat_{item_id}"):
                            st.session_state[f"chatting_{item_id}"] = False
                            st.rerun()


# --- 직접 작성이 필요한 항목 안내 ------------------------------------------


def _gap_items() -> list[dict]:
    fd = st.session_state.form_doc or {}
    items = fd.get("items", [])
    drafted_ids = {d.get("item_id") for d in st.session_state.drafts}
    return [it for it in items if not it.get("is_pii") and it.get("item_id") not in drafted_ids]


if st.session_state.form_doc and st.session_state.drafts:
    gap_items = _gap_items()
    if gap_items:
        with st.container(border=True):
            st.markdown("### ❓ 자료에 단서가 부족해 초안이 생성되지 않은 항목")
            for it in gap_items:
                st.markdown(f"- {it.get('label', '?')}")
            st.caption("💡 채팅으로 정보를 더 알려주시거나, 다운로드한 .hwpx에서 직접 채우세요.")
