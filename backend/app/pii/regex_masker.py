"""Pass-1 PII masker: regex substitution for structured Korean PII patterns.

Ordering is load-bearing:
1. JUMIN  — 13-digit with/without hyphen; must run before generic digit runs
2. CARD   — 16-digit (4-4-4-4); must run before ACCOUNT (10-14 digit)
3. ACCOUNT — bank account formats (hyphenated or keyword-gated plain digits)
4. PHONE  — international / domestic / no-hyphen mobile
5. EMAIL  — RFC-ish local@domain
6. MONEY  — ₩/원/만원/억원
"""

import re

# ── compiled patterns ──────────────────────────────────────────────────────────

_JUMIN = re.compile(
    r"\b\d{6}-[1-9]\d{6}\b"          # hyphenated: 901231-1234567 (covers 외국인 5-8)
    r"|\b\d{6}[1-9]\d{6}\b",         # no hyphen:  9012311234567
)

_CARD = re.compile(
    r"\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b"  # 4-4-4-4 (hyphen or space)
    r"|\b\d{16}\b",                               # plain 16 digits
)

# Hyphenated bank account formats: XX(X)-XX(X)-XXXXXX(XX)
# Covers 국민(XXX-XX-XXXXXX), 신한(XXX-XXX-XXXXXX), 농협(XXXX-XX-XXXXXX), etc.
_ACCOUNT_HYPHEN = re.compile(
    r"\b\d{3,4}-\d{2,3}-\d{6,8}\b"
)

# Plain digit account: 10–14 digits preceded by a 계좌 keyword.
# Use a capturing group for the keyword prefix; the replacement re-inserts it.
_ACCOUNT_KEYWORD = re.compile(
    r"((?:계좌번호|입금계좌|수납계좌|계좌)[번호\s:：]*)\s*(\d{10,14})"
)

_PHONE = re.compile(
    r"\+82[-\s]?\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}\b"  # +82-XX-XXXX-XXXX
    r"|\b0\d{1,2}-\d{3,4}-\d{4}\b"                   # 02-/010-/031- (hyphenated)
    r"|\b01[016789]\d{7,8}\b",                        # 010/011/016/017/018/019 no hyphen
)

_EMAIL = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

_MONEY = re.compile(
    r"₩[\d,]+"                     # ₩1,000,000
    r"|\d[\d,]*(?:억원|만원|원)\b"  # 500만원 / 2억원 / 30000원
)

# ── ordered pipeline ──────────────────────────────────────────────────────────

def _account_keyword_repl(m: re.Match) -> str:
    return m.group(1) + "[ACCOUNT]"


def mask(text: str) -> str:
    """Replace all structured PII in *text* with opaque tokens."""
    text = _JUMIN.sub("[JUMIN]", text)
    text = _CARD.sub("[CARD]", text)
    text = _ACCOUNT_HYPHEN.sub("[ACCOUNT]", text)
    text = _ACCOUNT_KEYWORD.sub(_account_keyword_repl, text)
    text = _PHONE.sub("[PHONE]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _MONEY.sub("[MONEY]", text)
    return text
