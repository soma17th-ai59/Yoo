"""Extract the form-body text from a per-item chat reply.

The Solar system prompt for /api/sessions/{id}/item-chat asks the model to
wrap proposed body text between triple-dash delimiters. When that format is
honoured we take the middle chunk; otherwise we strip common conversational
openers and trailers and return what remains.
"""

from __future__ import annotations

import re

_OPENER = re.compile(r"^(알겠습니다|네,?|좋습니다|확인했습니다)[\.\!,\s]*")

_TRAILERS = [
    re.compile(r"이대로 적용하시겠.*?$", re.MULTILINE | re.DOTALL),
    re.compile(r"수정.*?알려주.*?$", re.MULTILINE | re.DOTALL),
    re.compile(r"추가.*?수정.*?있으면.*?$", re.MULTILINE | re.DOTALL),
    re.compile(r"필요한 부분.*?알려주.*?$", re.MULTILINE | re.DOTALL),
]


def extract_body(reply: str) -> str:
    """Return only the proposed body text, stripped of conversational filler."""
    if not reply:
        return ""
    parts = reply.split("---")
    if len(parts) >= 3:
        return parts[1].strip()
    text = reply.strip()
    text = _OPENER.sub("", text)
    for pat in _TRAILERS:
        text = pat.sub("", text).strip()
    return text or reply.strip()
