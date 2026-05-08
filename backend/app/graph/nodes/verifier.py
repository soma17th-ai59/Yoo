"""Verifier node — review each draft and apply verdict markers.

V1 simplified approach (no re-generation within this node):
  ok        → draft.approved = True, text unchanged
  retry     → prepend "[검토 필요] " to text, set approved = True
  soft_fail → append " [확인 필요]" to text, set approved = True
  invalid   → treat as soft_fail

Zero LangGraph imports per module purity rules.
"""

from __future__ import annotations

from backend.app.graph.state import DraftItem, GraphState
from backend.app.llm import solar as _solar_mod
from backend.app.llm.prompts import build_verifier_messages

_RETRY_PREFIX = "[검토 필요] "
_SOFT_FAIL_SUFFIX = " [확인 필요]"
_NEEDS_INFO_PREFIX = "[추가 정보 필요]"
_VALID_VERDICTS = frozenset(["ok", "retry", "soft_fail"])


def _solar_complete(messages: list[dict]) -> object:
    """Thin wrapper so tests can patch a single symbol."""
    return _solar_mod.complete(messages, json_mode=True)


def verify_drafts(state: GraphState) -> dict:
    """Verify every unapproved draft and return an updated draft list.

    Returns {"drafts": list[DraftItem]} where all drafts have approved=True.
    """
    if state.form_doc is None:
        return {"drafts": [draft.model_copy(update={"approved": True}) for draft in state.drafts]}

    updated_drafts: list[DraftItem] = []

    for draft in state.drafts:
        if draft.approved:
            updated_drafts.append(draft)
            continue

        # Placeholder drafts (needs_question items the user hasn't answered
        # yet) carry no LLM-generated claims; skip verification and approve
        # so they render and surface in the UI's manual-entry list.
        if draft.text.startswith(_NEEDS_INFO_PREFIX):
            updated_drafts.append(draft.model_copy(update={"approved": True}))
            continue

        updated_drafts.append(_verify_single(draft, state))

    return {"drafts": updated_drafts}


def _verify_single(draft: DraftItem, state: GraphState) -> DraftItem:
    """Call Solar to verify one draft and apply verdict transformation."""
    messages = build_verifier_messages(
        draft.model_dump(),
        state.form_doc,  # type: ignore[arg-type]
        state.materials.docs,
    )

    try:
        response = _solar_complete(messages)
        if not isinstance(response, dict):
            verdict = "soft_fail"
        else:
            verdict = response.get("verdict", "soft_fail")
            if verdict not in _VALID_VERDICTS:
                verdict = "soft_fail"
    except Exception:
        verdict = "soft_fail"

    if verdict == "ok":
        return draft.model_copy(update={"approved": True})
    elif verdict == "retry":
        return draft.model_copy(update={"text": _RETRY_PREFIX + draft.text, "approved": True})
    else:  # soft_fail or fallback
        return draft.model_copy(update={"text": draft.text + _SOFT_FAIL_SUFFIX, "approved": True})
