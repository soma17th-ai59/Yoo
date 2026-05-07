"""Extract the form-body text from a per-item chat reply.

The Solar system prompt for /api/sessions/{id}/item-chat asks the model to
wrap proposed body text between triple-dash delimiters. When that format is
honoured we take the middle chunk; otherwise we strip common conversational
openers and trailers and return what remains. If the strip leaves us with
near-nothing we fall back to the full reply so the user gets *something* to
review rather than just a cleaned-up filler line.
"""

from __future__ import annotations

import re

# Conversational openers — match the trigger phrase plus the rest of its
# sentence/line. \s in re.DOTALL covers both inline ("알겠습니다. 본문…") and
# block ("**정리해 드리면…**\n\n본문") variants.
_OPENERS = [
    re.compile(r"^\**\s*(알겠습니다|네|좋습니다|확인했습니다)[.!,]?\s*\**\s+"),
    re.compile(r"^\**\s*정리해\s*드리면[^\n]*?[\.!]?\**\s*(\n+|\Z)", re.MULTILINE),
    re.compile(r"^\**\s*다음과\s*같이?\s*정리[^\n]*?[\.!]?\**\s*(\n+|\Z)", re.MULTILINE),
    re.compile(r"^\**\s*다음과\s*같이?\s*작성[^\n]*?[\.!]?\**\s*(\n+|\Z)", re.MULTILINE),
    re.compile(r"^\**\s*제안[^\n]*?드립니다[^\n]*?[\.!]?\**\s*(\n+|\Z)", re.MULTILINE),
    re.compile(r"^\**\s*요약[^\n]*?드리면[^\n]*?[\.!]?\**\s*(\n+|\Z)", re.MULTILINE),
    re.compile(r"^\**\s*본문[^\n]*?제안[^\n]*?[\.!]?\**\s*(\n+|\Z)", re.MULTILINE),
]

# Conversational trailers — match from trigger phrase to end of string.
# (?:\n|\.\s+|^) lets us catch both block ("\n\n이대로…") and inline
# ("…30% 완화한다. 추가 수정 요청사항이…") forms.
_TRAIL_BOUNDARY = r"(?:\n|\.\s+)\**\s*"
_TRAILERS = [
    re.compile(_TRAIL_BOUNDARY + r"이대로[\s\S]*$"),
    re.compile(_TRAIL_BOUNDARY + r"수정[^\n]*알려주[\s\S]*$"),
    re.compile(_TRAIL_BOUNDARY + r"추가[^\n]*수정[\s\S]*$"),
    re.compile(_TRAIL_BOUNDARY + r"필요한\s*부분[\s\S]*$"),
    re.compile(_TRAIL_BOUNDARY + r"어떠신가요\??[\s\S]*$"),
    re.compile(_TRAIL_BOUNDARY + r"괜찮으신가요\??[\s\S]*$"),
    re.compile(_TRAIL_BOUNDARY + r"알려주시기\s*바랍니다[\s\S]*$"),
]

_MD_HEADING = re.compile(r"^#+\s+", re.MULTILINE)
_MD_HORIZ_RULE = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_MD_BOLD = re.compile(r"\*\*(.*?)\*\*")
_MD_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")

_MIN_BODY_CHARS = 20  # below this, fall back to the full reply


def _strip_markdown_chrome(text: str) -> str:
    text = _MD_HEADING.sub("", text)
    text = _MD_HORIZ_RULE.sub("", text)
    text = _MD_BOLD.sub(r"\1", text)
    text = _MD_ITALIC.sub(r"\1", text)
    return text


def extract_body(reply: str) -> str:
    """Return only the proposed body text, stripped of conversational filler.

    Strategy, in order:
      1. If the reply contains the spec-mandated `---body---` delimiters,
         take the middle chunk.
      2. Otherwise strip common openers (greetings, "정리해 드리면…",
         markdown bold/heading) and trailers (이대로 적용 / 수정 알려주세요).
      3. If what remains is too short (<20 chars), return the full reply
         minus only the obvious trailers — better to show the user
         everything and let them edit than to apply just a preamble.
    """
    if not reply:
        return ""

    parts = reply.split("---")
    if len(parts) >= 3:
        candidate = _strip_markdown_chrome(parts[1]).strip()
        if len(candidate) >= _MIN_BODY_CHARS:
            return candidate

    text = reply.strip()
    for pat in _TRAILERS:
        text = pat.sub("", text)
    for pat in _OPENERS:
        text = pat.sub("", text, count=1)
    text = _strip_markdown_chrome(text).strip()
    if len(text) >= _MIN_BODY_CHARS:
        return text

    fallback = reply.strip()
    for pat in _TRAILERS:
        fallback = pat.sub("", fallback)
    return _strip_markdown_chrome(fallback).strip() or reply.strip()
