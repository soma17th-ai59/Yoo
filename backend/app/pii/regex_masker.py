"""Pass-1 PII masker: regex substitution for structured Korean PII patterns.

Ordering is load-bearing:
1. JUMIN  — 13-digit hyphenated; must run before generic digit runs
2. CARD   — 16-digit (4-4-4-4 delimited, or plain with card keyword)
3. ACCOUNT — bank account formats (keyword-gated hyphenated or plain digits)
4. PHONE  — international / domestic / no-hyphen mobile
5. EMAIL  — RFC-ish local@domain
6. MONEY  — ₩/원/만원/억원
"""

import re

# ── compiled patterns ──────────────────────────────────────────────────────────

# Hyphenated only: no-hyphen form over-matches ISBNs/barcodes/product codes.
# Use digit-aware lookaround instead of \b so Korean-adjacent matches still
# fire — \b doesn't separate Korean syllables from digits in Python regex.
_JUMIN = re.compile(r"(?<!\d)\d{6}-[1-9]\d{6}(?!\d)")

# 4-4-4-4 delimited form is precise; plain 16-digit is gated by card keyword.
_CARD_DELIMITED = re.compile(r"(?<!\d)\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}(?!\d)")
_CARD_PLAIN = re.compile(
    r"(?:카드|신용|체크)[번호\s:：]*(\d{16})(?!\d)"  # keyword-gated plain 16 digits
)

# Hyphenated bank account formats: keyword-gated to avoid project/document numbers.
# Covers 국민(XXX-XX-XXXXXX), 신한(XXX-XXX-XXXXXX), 농협(XXXX-XX-XXXXXX), etc.
_ACCOUNT_HYPHEN = re.compile(
    r"((?:계좌번호|입금계좌|수납계좌|통장|은행|계좌)[번호\s:：]*)\s*(\d{3,4}-\d{2,3}-\d{6,8})(?!\d)"
)

# Plain digit account: 10–14 digits preceded by a 계좌 keyword.
# Use a capturing group for the keyword prefix; the replacement re-inserts it.
_ACCOUNT_KEYWORD = re.compile(
    r"((?:계좌번호|입금계좌|수납계좌|통장|은행|계좌)[번호\s:：]*)\s*(\d{10,14})"
)

_PHONE = re.compile(
    r"\+82[-\s]?\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"  # +82-XX-XXXX-XXXX
    r"|(?<!\d)0\d{1,2}-\d{3,4}-\d{4}(?!\d)"  # 02-/010-/031- (hyphenated)
    r"|(?<!\d)01[016789]\d{7,8}(?!\d)",  # 010/011/016/017/018/019 no hyphen
)

_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

_MONEY = re.compile(
    r"₩[\d,]+"  # ₩1,000,000
    r"|\d[\d,]*(?:억원|만원|원)\b"  # 500만원 / 2억원 / 30000원
)

# ── ordered pipeline ──────────────────────────────────────────────────────────


def _keyword_account_repl(m: re.Match) -> str:
    return m.group(1) + "[ACCOUNT]"


def _card_plain_repl(m: re.Match) -> str:
    # Preserve the keyword prefix; replace only the 16-digit number.
    full = m.group(0)
    return full[: full.rfind(m.group(1))] + "[CARD]"


def mask(text: str) -> str:
    """Replace all structured PII in *text* with opaque tokens."""
    text = _JUMIN.sub("[JUMIN]", text)
    text = _CARD_DELIMITED.sub("[CARD]", text)
    text = _CARD_PLAIN.sub(_card_plain_repl, text)
    text = _ACCOUNT_HYPHEN.sub(_keyword_account_repl, text)
    text = _ACCOUNT_KEYWORD.sub(_keyword_account_repl, text)
    text = _PHONE.sub("[PHONE]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _MONEY.sub("[MONEY]", text)
    return text
