"""Tests for pii.regex_masker — covering all token types, including negative cases."""

from backend.app.pii.regex_masker import mask

# ── 주민번호 (JUMIN) ─────────────────────────────────────────────────────────


def test_mask_jumin_hyphen():
    assert mask("주민 901231-1234567 입니다") == "주민 [JUMIN] 입니다"


def test_mask_jumin_no_hyphen_not_masked():
    # No-hyphen form removed (over-matches ISBNs); only hyphenated form is masked.
    assert mask("등록번호: 9012311234567") == "등록번호: 9012311234567"


def test_mask_jumin_foreign():
    assert mask("외국인 820101-5123456 등록") == "외국인 [JUMIN] 등록"


def test_mask_jumin_multiple():
    result = mask("갑 901231-1234567 을 800101-2345678")
    assert result == "갑 [JUMIN] 을 [JUMIN]"


# ── Korean-adjacent PII (regression: \b doesn't separate Korean from digits)


def test_mask_jumin_flush_against_korean():
    """주민번호 immediately preceded/followed by Korean syllables must mask.
    Previously \b failed because Korean syllables are \w in Python regex."""
    assert mask("주민901231-1234567입니다") == "주민[JUMIN]입니다"


def test_mask_phone_flush_against_korean():
    assert mask("내번호는010-1234-5678입니다") == "내번호는[PHONE]입니다"


def test_mask_phone_intl_flush_against_korean():
    assert mask("연락처+82-10-1234-5678로요") == "연락처[PHONE]로요"


# ── 카드 (CARD) ──────────────────────────────────────────────────────────────


def test_mask_card_hyphen():
    assert mask("카드 1234-5678-9012-3456") == "카드 [CARD]"


def test_mask_card_space():
    assert mask("번호 1234 5678 9012 3456") == "번호 [CARD]"


def test_mask_card_plain():
    assert mask("카드번호: 1234567890123456") == "카드번호: [CARD]"


# ── 계좌 (ACCOUNT) ───────────────────────────────────────────────────────────


def test_mask_account_kb():
    # 국민은행 형식 XXX-XX-XXXXXX (11자리)
    assert mask("계좌번호 123-45-678901") == "계좌번호 [ACCOUNT]"


def test_mask_account_shinhan():
    # 신한은행 형식 XXX-XXX-XXXXXX (12자리)
    assert mask("입금계좌 110-234-567890") == "입금계좌 [ACCOUNT]"


def test_mask_account_nh():
    # 농협 형식 XXXX-XX-XXXXXX (12자리)
    assert mask("수납계좌: 3020-12-345678") == "수납계좌: [ACCOUNT]"


def test_mask_account_plain_digits():
    # 계좌 키워드 뒤에 오는 10~14자리 숫자
    assert mask("계좌 12345678901234") == "계좌 [ACCOUNT]"


# ── 전화번호 (PHONE) ─────────────────────────────────────────────────────────


def test_mask_phone_mobile():
    assert mask("연락처 010-1234-5678") == "연락처 [PHONE]"


def test_mask_phone_seoul():
    assert mask("전화 02-1234-5678") == "전화 [PHONE]"


def test_mask_phone_regional():
    assert mask("문의 031-234-5678") == "문의 [PHONE]"


def test_mask_phone_intl():
    assert mask("해외 +82-10-1234-5678") == "해외 [PHONE]"


def test_mask_phone_no_hyphen_mobile():
    assert mask("01012345678") == "[PHONE]"


# ── 이메일 (EMAIL) ───────────────────────────────────────────────────────────


def test_mask_email_basic():
    assert mask("연락 abc@def.kr") == "연락 [EMAIL]"


def test_mask_email_subdomain():
    assert mask("이메일: user.name+tag@mail.example.co.kr") == "이메일: [EMAIL]"


def test_mask_email_multiple():
    result = mask("from a@b.com to c@d.org")
    assert result == "from [EMAIL] to [EMAIL]"


# ── 금액 (MONEY) ─────────────────────────────────────────────────────────────


def test_mask_money_won_sign():
    assert mask("금액 ₩1,000,000 청구") == "금액 [MONEY] 청구"


def test_mask_money_man_won():
    assert mask("지원금 500만원") == "지원금 [MONEY]"


def test_mask_money_eok_won():
    assert mask("예산 2억원") == "예산 [MONEY]"


def test_mask_money_plain_won():
    assert mask("비용 30000원") == "비용 [MONEY]"


# ── 부정 사례 (false-positive guards) ────────────────────────────────────────


def test_no_mask_research_period():
    # Hyphenated year range must not be treated as an account number.
    assert mask("연구 기간 2023-2025") == "연구 기간 2023-2025"


def test_no_mask_project_number_alpha():
    # Alphanumeric project code must not be touched.
    assert mask("과제번호: NRF-2023-R1") == "과제번호: NRF-2023-R1"


def test_no_mask_isbn():
    # 13-digit ISBN must not be matched as JUMIN (no-hyphen pattern removed).
    assert mask("ISBN 9780306406157") == "ISBN 9780306406157"


def test_no_mask_project_hyphen_number():
    # Government project number without 계좌 keyword must not become ACCOUNT.
    assert mask("과제번호: 2345-01-123456") == "과제번호: 2345-01-123456"


def test_no_mask_plain_16digit_without_card_keyword():
    # 16-digit number without 카드/신용/체크 keyword must not become [CARD].
    assert mask("바코드 1234567890123456") == "바코드 1234567890123456"


def test_no_mask_product_code_16digit():
    # Product/barcode 16-digit sequences without card keyword must not become [CARD].
    assert mask("제품코드: 4912345678901234") == "제품코드: 4912345678901234"


# ── 키워드 접두사 보존 ───────────────────────────────────────────────────────


def test_account_keyword_prefix_preserved():
    assert mask("계좌번호:  12345678901234") == "계좌번호:  [ACCOUNT]"


def test_account_hyphen_keyword_prefix_preserved():
    assert mask("입금계좌 110-234-567890") == "입금계좌 [ACCOUNT]"


def test_mask_account_tongzhang_plain():
    # 통장 keyword should trigger plain-digit account masking too
    assert mask("통장 12345678901") == "통장 [ACCOUNT]"


def test_mask_account_bank_plain():
    # 은행 keyword should trigger plain-digit account masking
    assert mask("은행 12345678901234") == "은행 [ACCOUNT]"
