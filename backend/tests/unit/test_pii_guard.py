"""Tests for pii.output_guard — detection-only PII scan on Generator output.

output_guard is STRICTER than the masker: false positives just trigger a retry,
not permanent data loss. So unhyphenated 13-digit runs, plain 16-digit sequences,
and plain 10-14 digit runs are all flagged.
"""

from backend.app.pii.output_guard import scan

# ── 정상 텍스트 (clean text → True) ──────────────────────────────────────────


def test_scan_clean_korean_text():
    assert scan("이 연구는 중요합니다.") == (True, "")


def test_scan_clean_english_text():
    assert scan("This research is important.") == (True, "")


def test_scan_clean_with_numbers():
    # Year range and short digit sequences should not trigger
    assert scan("연구 기간 2023-2025년, 총 3단계") == (True, "")


def test_scan_clean_academic_text():
    assert scan("BK21 사업의 핵심 목표는 연구역량 강화입니다.") == (True, "")


def test_scan_clean_money_text():
    # Money amounts alone are not PII
    assert scan("연구비 500만원을 지원합니다.") == (True, "")


def test_scan_empty_string():
    assert scan("") == (True, "")


# ── 주민번호 하이픈 형식 (JUMIN — hyphenated) ─────────────────────────────────


def test_scan_detects_jumin_hyphenated():
    ok, reason = scan("주민 901231-1234567 입니다")
    assert ok is False
    assert "jumin" in reason.lower()


def test_scan_detects_jumin_foreign_resident():
    ok, reason = scan("외국인등록번호 820101-5123456")
    assert ok is False
    assert "jumin" in reason.lower()


def test_scan_detects_jumin_in_sentence():
    ok, reason = scan("신청자의 주민등록번호는 901231-1234567이며 연구를 진행합니다.")
    assert ok is False
    assert "jumin" in reason.lower()


# ── 주민번호 비하이픈 13자리 (JUMIN — unhyphenated 13-digit) ─────────────────


def test_scan_detects_13digit_unhyphenated():
    """Stricter than masker: unhyphenated 13-digit sequences are flagged."""
    ok, reason = scan("번호 9012311234567")
    assert ok is False
    assert reason != ""


def test_scan_detects_13digit_in_context():
    ok, reason = scan("등록번호: 8201015123456 입니다")
    assert ok is False
    assert reason != ""


# ── 계좌번호 (ACCOUNT) ────────────────────────────────────────────────────────


def test_scan_detects_account_14digit():
    ok, reason = scan("계좌 12345678901234")
    assert ok is False
    assert "account" in reason.lower()


def test_scan_detects_account_10digit():
    ok, reason = scan("입금 계좌번호: 1234567890")
    assert ok is False
    assert "account" in reason.lower()


def test_scan_detects_account_hyphenated():
    ok, reason = scan("은행계좌 110-234-567890 로 입금")
    assert ok is False
    assert "account" in reason.lower()


# ── 카드번호 (CARD) ───────────────────────────────────────────────────────────


def test_scan_detects_card_4x4_hyphen():
    ok, reason = scan("카드번호 1234-5678-9012-3456")
    assert ok is False
    assert "card" in reason.lower()


def test_scan_detects_card_4x4_space():
    ok, reason = scan("번호: 1234 5678 9012 3456")
    assert ok is False
    assert "card" in reason.lower()


def test_scan_detects_card_plain_16digit():
    """Stricter than masker: 16-digit plain sequence is flagged without keyword."""
    ok, reason = scan("바코드 1234567890123456")
    assert ok is False
    assert "card" in reason.lower()


# ── 전화번호 (PHONE) ──────────────────────────────────────────────────────────


def test_scan_detects_phone_mobile_hyphen():
    ok, reason = scan("연락처: 010-1234-5678")
    assert ok is False
    assert "phone" in reason.lower()


def test_scan_detects_phone_seoul():
    ok, reason = scan("전화 02-1234-5678")
    assert ok is False
    assert "phone" in reason.lower()


def test_scan_detects_phone_no_hyphen():
    ok, reason = scan("연락처 01012345678")
    assert ok is False
    assert "phone" in reason.lower()


def test_scan_detects_phone_international():
    ok, reason = scan("+82-10-1234-5678 로 연락하세요")
    assert ok is False
    assert "phone" in reason.lower()


# ── 이메일 (EMAIL) ────────────────────────────────────────────────────────────


def test_scan_detects_email_basic():
    ok, reason = scan("이메일: user@example.com")
    assert ok is False
    assert "email" in reason.lower()


def test_scan_detects_email_korean_domain():
    ok, reason = scan("연락: abc@korea.ac.kr")
    assert ok is False
    assert "email" in reason.lower()


def test_scan_detects_email_in_sentence():
    ok, reason = scan("담당자 이메일은 prof@snu.ac.kr입니다.")
    assert ok is False
    assert "email" in reason.lower()


# ── 복합 (multiple PII types) ────────────────────────────────────────────────


def test_scan_stops_at_first_match():
    """Returns on first detected type (does not require exhaustive scan)."""
    ok, reason = scan("주민 901231-1234567 이메일 a@b.com")
    assert ok is False
    assert reason != ""
