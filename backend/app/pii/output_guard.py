"""Pass-3 PII output guard: detection-only scan of Generator LLM output.

Stricter than the masker — false positives trigger a retry, not data loss.
Returns (True, "") when clean; (False, "PII pattern detected: <type>") on hit.

Pattern ordering (most-specific → most-general):
1. JUMIN      — hyphenated 6-7 pattern (most precise)
2. CARD       — 4-4-4-4 delimited, then plain 16-digit (stricter: no keyword gate)
3. ACCOUNT    — hyphenated bank formats, then plain 10–14 digit runs
4. PHONE      — international, domestic hyphenated, no-hyphen mobile
5. EMAIL      — RFC-ish local@domain
6. JUMIN_13   — any unhyphenated 13-digit run (catches jumin without hyphen)
"""

import re

# ── patterns ──────────────────────────────────────────────────────────────────

# Boundary note: \b doesn't separate Korean syllables from digits in Python
# regex (both are \w under Unicode), so we use digit-aware lookaround
# (?<!\d)…(?!\d) to fire even when PII sits flush against Korean characters.

_JUMIN_HYPHEN = re.compile(r"(?<!\d)\d{6}-[1-9]\d{6}(?!\d)")

_CARD_DELIMITED = re.compile(r"(?<!\d)\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}(?!\d)")

# Stricter than masker: 16-digit plain run flagged regardless of keyword.
_CARD_PLAIN_16 = re.compile(r"(?<!\d)\d{16}(?!\d)")

# Hyphenated bank account: 3-4 digits, dash, 2-3 digits, dash, 6-8 digits.
_ACCOUNT_HYPHEN = re.compile(r"(?<!\d)\d{3,4}-\d{2,3}-\d{6,8}(?!\d)")

# Stricter: any 10–14 digit run (covers plain account numbers without keyword).
# Lower bound 10 avoids years (4 digits) and phone no-hyphen forms (11 digits
# are caught by _PHONE first, but 10/12/13/14 digit runs catch accounts).
_ACCOUNT_PLAIN = re.compile(r"(?<!\d)\d{10,14}(?!\d)")

_PHONE = re.compile(
    r"\+82[-\s]?\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"
    r"|(?<!\d)0\d{1,2}-\d{3,4}-\d{4}(?!\d)"
    r"|(?<!\d)01[016789]\d{7,8}(?!\d)"
)

_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Catch unhyphenated 13-digit runs (JUMIN without hyphen, 외국인등록번호, etc.).
# Must come after _CARD_PLAIN_16 and _ACCOUNT_PLAIN in the scan order to
# keep reason strings specific — but we tag it as "jumin" since 13-digit
# runs in Korean administrative text are almost exclusively resident IDs.
_JUMIN_13_PLAIN = re.compile(r"(?<!\d)\d{13}(?!\d)")

# ── ordered scan pipeline ─────────────────────────────────────────────────────

_CHECKS: list[tuple[re.Pattern[str], str]] = [
    (_JUMIN_HYPHEN, "PII pattern detected: jumin"),
    (_CARD_DELIMITED, "PII pattern detected: card"),
    (_PHONE, "PII pattern detected: phone"),
    (_EMAIL, "PII pattern detected: email"),
    (_CARD_PLAIN_16, "PII pattern detected: card"),
    (_ACCOUNT_HYPHEN, "PII pattern detected: account"),
    (_ACCOUNT_PLAIN, "PII pattern detected: account"),
    (_JUMIN_13_PLAIN, "PII pattern detected: jumin"),
]


def scan(text: str) -> tuple[bool, str]:
    """Scan Generator output for PII leaks.

    Returns:
        (True, "") if no PII detected.
        (False, reason) where reason names the first matched pattern type.
    """
    for pattern, reason in _CHECKS:
        if pattern.search(text):
            return False, reason
    return True, ""
