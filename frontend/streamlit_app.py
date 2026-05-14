"""HwpAgent — Streamlit chat UI.

Talks to the FastAPI backend (BACKEND_URL env var, default http://localhost:8000).
Sessions are server-side and in-memory only — nothing persists to disk.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from typing import Any

import httpx
import streamlit as st
import streamlit.components.v1 as components

try:
    from frontend.extract_body import extract_body as _extract_body
except ModuleNotFoundError:
    from extract_body import extract_body as _extract_body

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
_NEEDS_INFO_PREFIX = "[추가 정보 필요]"

st.set_page_config(page_title="HwpAgent", page_icon=":page_facing_up:", layout="wide")
st.title("HwpAgent — 양식 자동 채우기")

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
        setInterval(attach, 1500);
      })();
    </script>
    """,
    height=0,
)

_APP_DEFAULTS = {
    "active_session_id": None,
    "session_cache": {},
    "session_list": [],
}


def _new_session_state() -> dict[str, Any]:
    return {
        "messages": [],
        "form_doc": None,
        "drafts": [],
        "uploaded_form": None,
        "uploaded_materials": [],
        "fill_requested": False,
    }


for key, default in _APP_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default if not isinstance(default, dict) else dict(default)


def _current_backend() -> str:
    return BACKEND_URL


def _active_session_id() -> str | None:
    return st.session_state.active_session_id


def _ensure_session_cache(session_id: str) -> dict[str, Any]:
    cache = st.session_state.session_cache
    if session_id not in cache:
        cache[session_id] = _new_session_state()
    return cache[session_id]


def _active_state() -> dict[str, Any]:
    session_id = _active_session_id()
    if session_id is None:
        return _new_session_state()
    return _ensure_session_cache(session_id)


def _session_ui_key(prefix: str, suffix: str) -> str:
    session_id = _active_session_id() or "no-session"
    return f"{prefix}_{session_id}_{suffix}"


def _session_summary_defaults(session_id: str) -> dict[str, Any]:
    now = time.time()
    return {
        "session_id": session_id,
        "created_at": now,
        "updated_at": now,
        "has_form": False,
        "uploaded_form": None,
        "uploaded_materials": [],
        "material_count": 0,
        "has_rendered": False,
        "has_state": False,
    }


def _upsert_session_summary(summary: dict[str, Any]) -> None:
    sessions = [
        session
        for session in st.session_state.session_list
        if session["session_id"] != summary["session_id"]
    ]
    sessions.append(summary)
    sessions.sort(key=lambda item: item.get("updated_at", 0.0), reverse=True)
    st.session_state.session_list = sessions


def _update_active_summary(**changes: Any) -> None:
    session_id = _active_session_id()
    if session_id is None:
        return
    summary = next(
        (item for item in st.session_state.session_list if item["session_id"] == session_id),
        None,
    )
    if summary is None:
        summary = _session_summary_defaults(session_id)
    summary.update(changes)
    _upsert_session_summary(summary)


def _clear_session_ui_state(session_id: str) -> None:
    prefixes = (
        "editing_",
        "edit_text_",
        "chatting_",
        "chat_history_",
        "chat_input_",
        "apply_warn_",
        "form_uploader_",
        "material_uploader_",
        "download_btn_",
        "download_force_btn_",
        "download_save_btn_",
        "download_force_save_btn_",
    )
    target = f"_{session_id}_"
    for key in list(st.session_state.keys()):
        if any(key.startswith(prefix) and target in key for prefix in prefixes):
            del st.session_state[key]


def _create_session() -> str:
    r = httpx.post(f"{_current_backend()}/api/sessions", timeout=10.0)
    r.raise_for_status()
    return r.json()["session_id"]


def _list_sessions() -> list[dict[str, Any]]:
    r = httpx.get(f"{_current_backend()}/api/sessions", timeout=10.0)
    r.raise_for_status()
    return r.json().get("sessions", [])


def _get_session_detail(session_id: str) -> dict[str, Any]:
    r = httpx.get(f"{_current_backend()}/api/sessions/{session_id}", timeout=10.0)
    r.raise_for_status()
    return r.json()


def _switch_session(session_id: str) -> None:
    current = _ensure_session_cache(session_id)
    if current == _new_session_state():
        detail = _get_session_detail(session_id)
        current["messages"] = detail.get("history", [])
        current["form_doc"] = detail.get("form_doc")
        current["drafts"] = detail.get("drafts", [])
        current["uploaded_form"] = detail.get("uploaded_form")
        current["uploaded_materials"] = detail.get("uploaded_materials", [])
        _upsert_session_summary(
            {
                key: detail.get(key)
                for key in (
                    "session_id",
                    "created_at",
                    "updated_at",
                    "has_form",
                    "uploaded_form",
                    "uploaded_materials",
                    "material_count",
                    "has_rendered",
                    "has_state",
                )
            }
        )
    st.session_state.active_session_id = session_id


def _refresh_sessions() -> None:
    st.session_state.session_list = _list_sessions()


def _upload(kind: str, name: str, data: bytes) -> None:
    sid = _active_session_id()
    r = httpx.post(
        f"{_current_backend()}/api/upload",
        data={"session_id": sid, "kind": kind},
        files={"file": (name, data, "application/octet-stream")},
        timeout=30.0,
    )
    r.raise_for_status()

    current = _active_state()
    if kind == "form":
        current["uploaded_form"] = name
        current["form_doc"] = None
        current["drafts"] = []
        _clear_session_ui_state(sid or "")
        _update_active_summary(
            has_form=True,
            uploaded_form=name,
            has_state=False,
            updated_at=time.time(),
        )
        return

    materials = list(current["uploaded_materials"])
    if name not in materials:
        materials.append(name)
    current["uploaded_materials"] = materials
    _update_active_summary(
        material_count=len(materials),
        uploaded_materials=materials,
        updated_at=time.time(),
    )


def _stream_fill(session_id: str) -> Iterator[tuple[str, str]]:
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
    with httpx.stream(
        "POST",
        f"{_current_backend()}/api/sessions/{session_id}/fill",
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


def _replace_draft(updated: dict[str, Any]) -> None:
    current = _active_state()
    for index, draft in enumerate(current["drafts"]):
        if draft.get("item_id") == updated["item_id"]:
            current["drafts"][index] = updated
            return


def _apply_item(item_id: str) -> bool:
    sid = _active_session_id()
    try:
        r = httpx.post(
            f"{_current_backend()}/api/sessions/{sid}/items/apply",
            json={"item_id": item_id},
            timeout=10.0,
        )
        r.raise_for_status()
        _replace_draft(r.json())
        _update_active_summary(has_state=True, updated_at=time.time())
        return True
    except Exception as exc:
        st.error(f"적용 실패: {exc}")
        return False


def _unlock_item(item_id: str) -> bool:
    sid = _active_session_id()
    try:
        r = httpx.post(
            f"{_current_backend()}/api/sessions/{sid}/items/unlock",
            json={"item_id": item_id},
            timeout=10.0,
        )
        r.raise_for_status()
        _replace_draft(r.json())
        _update_active_summary(has_state=True, updated_at=time.time())
        return True
    except Exception as exc:
        st.error(f"해제 실패: {exc}")
        return False


def _save_draft_edit(item_id: str, text: str) -> bool:
    sid = _active_session_id()
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

    payload = r.json()
    if isinstance(payload, dict) and payload.get("item_id"):
        _replace_draft(payload)
    _update_active_summary(has_state=True, updated_at=time.time())
    return True


def _fetch_output_bytes(*, include_unlocked: bool = False) -> bytes | None:
    sid = _active_session_id()
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


def _item_chat(item_id: str, message: str, history: list[dict[str, str]]) -> str | None:
    sid = _active_session_id()
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


def _process_chat(message: str) -> str | None:
    sid = _active_session_id()
    try:
        r = httpx.post(
            f"{_current_backend()}/api/chat",
            json={"session_id": sid, "message": message},
            timeout=120.0,
        )
        r.raise_for_status()
        reply = r.json().get("reply", "")
        _update_active_summary(has_state=True, updated_at=time.time())
        return reply
    except Exception as exc:
        st.error(f"통신 오류: {exc}")
        return None


def _status_of(d: dict) -> str:
    return d.get("status") or "ok"


def _is_pii_draft(d: dict) -> bool:
    return bool(d.get("is_pii")) or _status_of(d) == "pii"


def _is_unfilled(d: dict) -> bool:
    s = _status_of(d)
    if s in {"needs_info", "needs_check", "pii"}:
        return not (d.get("text") or "").strip()
    return False


def _item_label(item_id: str) -> str:
    fd = _active_state().get("form_doc") or {}
    for item in fd.get("items", []):
        if item.get("item_id") == item_id:
            return item.get("label", item_id)
    return item_id


def _needs_manual_entry() -> tuple[list[dict], list[dict]]:
    current = _active_state()
    fd = current.get("form_doc") or {}
    items = fd.get("items", [])
    drafted_ids = {draft.get("item_id") for draft in current.get("drafts", [])}
    pii_items = [item for item in items if item.get("is_pii")]
    gap_items = [
        item
        for item in items
        if not item.get("is_pii") and item.get("item_id") not in drafted_ids
    ]
    return pii_items, gap_items


with st.sidebar:
    st.header("세션")
    if st.button("🆕 새 세션", use_container_width=True, type="primary"):
        session_id = _create_session()
        st.session_state.active_session_id = session_id
        _ensure_session_cache(session_id)
        _upsert_session_summary(_session_summary_defaults(session_id))
        st.rerun()

    if st.button("↻ 세션 목록 새로고침", use_container_width=True):
        try:
            _refresh_sessions()
        except Exception as exc:
            st.error(f"세션 목록 조회 실패: {exc}")

    active_id = _active_session_id()
    if active_id:
        st.caption(f"현재 세션: `{active_id[:8]}…`")
    else:
        st.caption("새 세션 버튼으로 시작하세요.")
    st.caption(
        "ℹ️ 세션은 메모리에만 저장됩니다 (디스크 저장 없음). "
        "백엔드를 재시작하면 모든 세션이 초기화되니, 작성 중에는 백엔드 터미널을 그대로 두세요."
    )

    if st.session_state.session_list:
        st.subheader("세션 목록")
        for session in st.session_state.session_list:
            sid = session["session_id"]
            status = "현재 사용 중" if sid == active_id else "열기"
            form_status = "양식" if session.get("has_form") else "양식 없음"
            material_count = session.get("material_count", 0)
            has_state = "초안 있음" if session.get("has_state") else "초안 없음"
            if st.button(
                f"{sid[:8]}…",
                key=f"select_session_{sid}",
                use_container_width=True,
                disabled=sid == active_id,
            ):
                try:
                    _switch_session(sid)
                except Exception as exc:
                    st.error(f"세션 전환 실패: {exc}")
                st.rerun()
            st.caption(f"{status} · {form_status} · 자료 {material_count}개 · {has_state}")

    st.divider()
    st.subheader("양식 (.hwpx)")
    current = _active_state()
    form_file = st.file_uploader(
        "양식 파일",
        type=["hwpx"],
        key=_session_ui_key("form_uploader", "main"),
    )
    if form_file is not None and active_id and form_file.name != current.get("uploaded_form"):
        _upload("form", form_file.name, form_file.read())
        st.success(f"양식 업로드 완료: {form_file.name}")

    st.subheader("자료 (CV / 계획서 / 보고서)")
    mat_files = st.file_uploader(
        "자료 파일 (PDF/docx/txt/hwpx)",
        type=["pdf", "docx", "txt", "hwpx"],
        accept_multiple_files=True,
        key=_session_ui_key("material_uploader", "main"),
    )
    if mat_files and active_id:
        for file in mat_files:
            if file.name not in current.get("uploaded_materials", []):
                _upload("material", file.name, file.read())
        if current.get("uploaded_materials"):
            st.caption("업로드된 자료: " + ", ".join(current["uploaded_materials"]))
    elif current.get("uploaded_materials"):
        st.caption("업로드된 자료: " + ", ".join(current["uploaded_materials"]))

    st.divider()
    st.subheader("자동 채우기")
    can_fill = bool(current.get("uploaded_form")) and bool(current.get("uploaded_materials"))
    if st.button(
        "▶ 양식 자동 채우기 시작",
        use_container_width=True,
        disabled=not can_fill,
        type="primary" if can_fill else "secondary",
        key=_session_ui_key("fill", "main"),
    ):
        current["fill_requested"] = True
        st.rerun()
    if not can_fill:
        st.caption("양식과 자료를 모두 업로드하면 활성화됩니다.")

    locked_count = sum(1 for draft in current.get("drafts", []) if draft.get("locked"))
    total_count = len(current.get("drafts", []))
    st.caption(f"적용된 항목 {locked_count} / 전체 {total_count}")
    if st.button(
        "📥 출력 .hwpx 다운로드",
        use_container_width=True,
        disabled=locked_count == 0,
        key=_session_ui_key("download_btn", "locked"),
    ):
        data = _fetch_output_bytes()
        if data:
            st.download_button(
                "📁 파일 저장",
                data=data,
                file_name="output.hwpx",
                mime="application/vnd.hancom.hwpx",
                key=_session_ui_key("download_save_btn", "locked"),
                use_container_width=True,
            )

    if st.button(
        "⬇ 미적용 초안 포함 다운로드",
        use_container_width=True,
        disabled=not current.get("form_doc"),
        key=_session_ui_key("download_force_btn", "all"),
        help="적용(✓) 안 한 항목도 생성된 초안 텍스트로 채워서 .hwpx를 받습니다. PII 항목은 사용자가 입력한 내용 그대로 들어갑니다.",
    ):
        data = _fetch_output_bytes(include_unlocked=True)
        if data:
            st.download_button(
                "📁 파일 저장 (미적용 초안 포함)",
                data=data,
                file_name="output.hwpx",
                mime="application/vnd.hancom.hwpx",
                key=_session_ui_key("download_force_save_btn", "all"),
                use_container_width=True,
            )


current = _active_state()

if current.get("form_doc"):
    fd = current["form_doc"]
    items = fd.get("items", [])
    pii_count = sum(1 for item in items if item.get("is_pii"))
    table_count = len(fd.get("tables", []))
    by_section: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        section = item.get("section") or "(섹션 없음)"
        by_section.setdefault(section, []).append(item)

    with st.expander(
        f"양식 구조 요약 — 항목 {len(items)}개 (PII {pii_count}개, 표 {table_count}개)",
        expanded=False,
    ):
        if not items:
            st.caption("항목이 추출되지 않았습니다. 양식을 다시 업로드해 주세요.")
        for section, section_items in by_section.items():
            st.markdown(f"**{section}**  &nbsp;_{len(section_items)}개_")
            for item in section_items:
                badge = " 🔒(PII)" if item.get("is_pii") else ""
                st.markdown(f"- {item.get('label', '?')}{badge}  &nbsp;`{item.get('item_id')}`")
        for table in fd.get("tables", []):
            headers = ", ".join(table.get("headers", []))
            st.markdown(
                f"**표 `{table.get('table_id')}`**  &nbsp;_{table.get('row_count', 0)}행_  &nbsp; 헤더: {headers}"
            )


if current.get("fill_requested"):
    current["fill_requested"] = False
    status = st.empty()
    try:
        for event, raw in _stream_fill(_active_session_id() or ""):
            payload = json.loads(raw) if raw else None
            if event == "node_started":
                status.write(f"… {payload['node']}")
            elif event == "form_parsed":
                current["form_doc"] = payload
            elif event == "preview":
                current["drafts"] = payload or []
                _update_active_summary(has_state=bool(current["drafts"]), updated_at=time.time())
            elif event == "done":
                count = (payload or {}).get("draft_count", 0)
                _update_active_summary(has_state=bool(current["drafts"]), updated_at=time.time())
                status.success(f"초안 {count}개 생성")
            elif event == "error":
                err = (payload or {}).get("error", "unknown")
                st.error(f"채우기 오류: {err}")
    except Exception as exc:
        st.error(f"통신 오류: {exc}")
    st.rerun()


for message in current.get("messages", []):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


user_msg = st.chat_input("무엇을 도와드릴까요?")
if user_msg:
    if not _active_session_id():
        st.warning("먼저 ▶ 새 세션 버튼으로 세션을 시작하세요.")
    else:
        current["messages"].append({"role": "user", "content": user_msg})
        with st.chat_message("user"):
            st.markdown(user_msg)
        with st.chat_message("assistant"):
            reply = _process_chat(user_msg)
            if reply is not None:
                st.markdown(reply)
                current["messages"].append({"role": "assistant", "content": reply})


if current.get("drafts"):
    st.subheader("작성된 초안")
    for draft in current["drafts"]:
        item_id = draft.get("item_id", "?")
        locked = bool(draft.get("locked", False))
        editing_key = _session_ui_key("editing", item_id)
        chatting_key = _session_ui_key("chatting", item_id)
        warn_key = _session_ui_key("apply_warn", item_id)
        history_key = _session_ui_key("chat_history", item_id)
        label = _item_label(item_id)
        status = _status_of(draft)
        is_pii = _is_pii_draft(draft)
        text = draft.get("text", "") or ""
        editing = st.session_state.get(editing_key, False)
        chatting = st.session_state.get(chatting_key, False)
        unfilled = _is_unfilled(draft)

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
                if cols[1].button("🔓 해제", key=_session_ui_key("unlock", item_id)):
                    if _unlock_item(item_id):
                        st.rerun()
                st.write(text if text else "_(빈 값)_")
                citations = draft.get("citations", [])
                if citations and not is_pii:
                    st.caption(f"근거: {', '.join(citations)}")
                continue

            # PII items get only 적용/수정 (no 대화 — LLM path is blocked for PII).
            if is_pii:
                cols = st.columns([5, 1, 1])
                cols[0].markdown(f"**{label}**  {badge}")
                if cols[1].button(
                    "✓ 적용",
                    key=_session_ui_key("apply", item_id),
                    disabled=editing,
                ):
                    if not text.strip():
                        st.session_state[warn_key] = True
                        st.rerun()
                    elif _apply_item(item_id):
                        st.rerun()
                if cols[2].button("✏ 수정", key=_session_ui_key("edit", item_id)):
                    st.session_state[editing_key] = not editing
                    st.rerun()
                st.caption("AI는 이 항목을 작성하지 않습니다. 직접 입력해 주세요.")
            else:
                cols = st.columns([4, 1, 1, 1])
                cols[0].markdown(f"**{label}**  {badge}")

                if cols[1].button(
                    "✓ 적용",
                    key=_session_ui_key("apply", item_id),
                    disabled=editing,
                ):
                    if unfilled:
                        st.session_state[warn_key] = True
                        st.rerun()
                    elif _apply_item(item_id):
                        st.rerun()

                if cols[2].button("✏ 수정", key=_session_ui_key("edit", item_id)):
                    st.session_state[editing_key] = not editing
                    st.rerun()

                if cols[3].button("💬 대화", key=_session_ui_key("chat", item_id)):
                    st.session_state[chatting_key] = not chatting
                    st.rerun()

            if st.session_state.pop(warn_key, False):
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
                    key=_session_ui_key("edit_text", item_id),
                    height=120 if is_pii else 160,
                    placeholder="여기에 입력…" if is_pii else "",
                )
                save_col, cancel_col = st.columns([1, 1])
                if save_col.button("저장", key=_session_ui_key("save", item_id)):
                    if _save_draft_edit(item_id, new_text):
                        st.session_state[editing_key] = False
                        st.rerun()
                if cancel_col.button("취소", key=_session_ui_key("cancel", item_id)):
                    st.session_state[editing_key] = False
                    st.rerun()
            else:
                if text:
                    st.write(text)
                elif is_pii:
                    st.write("_(미입력 — ✏ 수정으로 직접 입력하세요)_")
                else:
                    st.write("_(미작성)_")

            citations = draft.get("citations", [])
            if citations and not is_pii:
                st.caption(f"근거: {', '.join(citations)}")

            if chatting:
                history = st.session_state.get(history_key, [])
                with st.container(border=True):
                    st.markdown(
                        f"💬 **'{label}' 항목과 대화하기** — 정보를 알려주시면 본문을 함께 만들어 드립니다."
                    )
                    for message in history:
                        with st.chat_message(message["role"]):
                            import html as _html

                            safe = _html.escape(message["content"]).replace("\n", "<br>")
                            st.markdown(
                                f'<div style="font-size: 0.95rem; line-height: 1.55;">{safe}</div>',
                                unsafe_allow_html=True,
                            )

                    with st.form(_session_ui_key("chat_form", item_id), clear_on_submit=True):
                        typed = st.text_input(
                            "메시지",
                            key=_session_ui_key("chat_input", item_id),
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
                        st.session_state[history_key] = history
                        st.rerun()

                    if history:
                        last_assistant = next(
                            (
                                message["content"]
                                for message in reversed(history)
                                if message["role"] == "assistant"
                            ),
                            None,
                        )
                        body_preview = _extract_body(last_assistant) if last_assistant else ""
                        if body_preview and body_preview != (last_assistant or "").strip():
                            with st.expander("적용될 본문 미리보기", expanded=False):
                                st.write(body_preview)
                        action_cols = st.columns([2, 1, 2])
                        if action_cols[0].button(
                            "🟢 본문만 추출해 적용",
                            key=_session_ui_key("apply_chat", item_id),
                            disabled=not body_preview,
                        ):
                            if body_preview and _save_draft_edit(item_id, body_preview):
                                if _apply_item(item_id):
                                    st.session_state[chatting_key] = False
                                    st.session_state[history_key] = []
                                    st.rerun()
                        if action_cols[1].button(
                            "대화 닫기",
                            key=_session_ui_key("close_chat", item_id),
                        ):
                            st.session_state[chatting_key] = False
                            st.rerun()


if current.get("form_doc") and current.get("drafts"):
    pii_items, gap_items = _needs_manual_entry()
    if pii_items or gap_items:
        with st.container(border=True):
            st.markdown("### ✍️ 직접 작성이 필요한 항목")
            if pii_items:
                st.markdown(
                    "**🔒 개인정보 (AI는 작성하지 않습니다 — ✏ 수정으로 직접 입력해 주세요)**"
                )
                for item in pii_items:
                    st.markdown(f"- {item.get('label', '?')}")
            if gap_items:
                st.markdown("**❓ 자료에 단서가 부족한 항목 (추가 정보 또는 직접 작성 필요)**")
                for item in gap_items:
                    st.markdown(f"- {item.get('label', '?')}")
                st.caption(
                    "💡 채팅으로 정보를 더 알려주시거나, 다운로드한 .hwpx에서 직접 채우세요."
                )
