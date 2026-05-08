"""Tests for pii.presidio_masker (pass 2) and composed mask_all.

Pass 2 handles unstructured Korean PII: 이름, 주소, 소속, 학번.
Pass-1 tokens (e.g., [JUMIN]) must pass through unchanged.
"""

from backend.app.pii import mask_all
from backend.app.pii.presidio_masker import presidio_mask

# ── 이름 (NAME) ──────────────────────────────────────────────────────────────


def test_name_kim_yeongu():
    result = presidio_mask("연구책임자: 김연구 교수입니다.")
    assert "[NAME]" in result
    assert "김연구" not in result


def test_name_park_daehak():
    result = presidio_mask("담당자: 박대학 학생이 제출하였습니다.")
    assert "[NAME]" in result
    assert "박대학" not in result


def test_name_hong_gildong():
    result = presidio_mask("이름: 홍길동은 서울에 삽니다.")
    assert "[NAME]" in result
    assert "홍길동" not in result


def test_name_lee_baksa():
    result = presidio_mask("성명: 이박사가 논문을 발표했습니다.")
    assert "[NAME]" in result
    assert "이박사" not in result


def test_name_not_masked_without_keyword():
    # Words without a name-indicating keyword must not trigger NAME masking.
    result = presidio_mask("학교에서 교수가 제출합니다.")
    assert "[NAME]" not in result


def test_name_keyword_prefix_preserved():
    result = presidio_mask("이름: 홍길동")
    assert "이름:" in result or "이름: " in result
    assert "[NAME]" in result
    assert "홍길동" not in result


def test_name_responsible_researcher():
    result = presidio_mask("연구책임자: 김연구")
    assert "[NAME]" in result
    assert "김연구" not in result
    assert "연구책임자" in result


# ── 이름 거짓 양성 방지 (NAME false-positive prevention) ────────────────────


def test_no_name_match_on_form_labels():
    # Common form labels must not trigger NAME masking.
    for label in ["주소:", "소속:", "이메일:", "전화번호:", "서울특별시"]:
        result = presidio_mask(label)
        assert "[NAME]" not in result, f"False positive: {label!r} → {result!r}"


def test_no_name_match_on_address_prefix():
    result = presidio_mask("주소: 서울")
    assert "[NAME]" not in result


def test_no_name_match_on_affiliation_label():
    result = presidio_mask("소속: 한국대학교")
    assert "[NAME]" not in result


def test_no_name_match_on_email_label():
    result = presidio_mask("이메일: [EMAIL]")
    assert "[NAME]" not in result


def test_no_name_match_on_phone_label():
    result = presidio_mask("전화: [PHONE]")
    assert "[NAME]" not in result


# ── 주소 (ADDRESS) ───────────────────────────────────────────────────────────


def test_address_seoul():
    result = presidio_mask("주소: 서울특별시 강남구 테헤란로 123")
    assert "[ADDRESS]" in result
    assert "서울특별시" not in result


def test_address_gyeonggi():
    result = presidio_mask("경기도 수원시 영통구 삼성로 129번지")
    assert "[ADDRESS]" in result
    assert "경기도" not in result


def test_address_busan():
    result = presidio_mask("부산광역시 해운대구 해운대로 55")
    assert "[ADDRESS]" in result
    assert "부산광역시" not in result


def test_address_daejeon():
    result = presidio_mask("연구소 위치: 대전광역시 유성구 과학로 169-148")
    assert "[ADDRESS]" in result
    assert "대전광역시" not in result


def test_address_not_masked_without_admin_prefix():
    # A vague location without a city/province prefix should not be flagged
    result = presidio_mask("실험실은 3층에 있습니다.")
    assert "[ADDRESS]" not in result


# ── 소속 (AFFILIATION) ───────────────────────────────────────────────────────


def test_affiliation_seoul_univ():
    result = presidio_mask("소속: 서울대학교 공과대학")
    assert "[AFFILIATION]" in result
    assert "서울대학교" not in result


def test_affiliation_research_institute():
    result = presidio_mask("한국연구소 소속 연구원입니다.")
    assert "[AFFILIATION]" in result
    assert "한국연구소" not in result


def test_affiliation_company_paren():
    result = presidio_mask("(주)한국기술 대표이사")
    assert "[AFFILIATION]" in result
    assert "(주)한국기술" not in result


def test_affiliation_hospital():
    result = presidio_mask("서울대학교병원에서 근무합니다.")
    assert "[AFFILIATION]" in result


def test_affiliation_research_won():
    result = presidio_mask("한국과학기술연구원 소속입니다.")
    assert "[AFFILIATION]" in result
    assert "한국과학기술연구원" not in result


# ── 학번 (STUDENT_ID) ────────────────────────────────────────────────────────


def test_student_id_8digit():
    result = presidio_mask("학번 20201234")
    assert "[STUDENT_ID]" in result
    assert "20201234" not in result


def test_student_id_9digit():
    result = presidio_mask("학번: 202012345")
    assert "[STUDENT_ID]" in result
    assert "202012345" not in result


def test_student_id_10digit():
    result = presidio_mask("학번: 2022123456")
    assert "[STUDENT_ID]" in result
    assert "2022123456" not in result


def test_student_id_with_space():
    result = presidio_mask("학번 2021-12345 학생")
    assert "[STUDENT_ID]" in result


def test_student_id_not_masked_without_keyword():
    # 8-digit number without 학번 keyword should NOT be masked as student ID
    result = presidio_mask("연구번호 20201234")
    assert "[STUDENT_ID]" not in result


# ── 패스1 토큰 통과 (pass-1 tokens survive pass 2) ──────────────────────────


def test_pass1_jumin_token_survives():
    result = presidio_mask("주민번호: [JUMIN]")
    assert "[JUMIN]" in result
    assert "[NAME]" not in result


def test_pass1_phone_token_survives():
    result = presidio_mask("전화: [PHONE]")
    assert "[PHONE]" in result
    assert result == "전화: [PHONE]"
    assert "[NAME]" not in result


def test_pass1_email_token_survives():
    result = presidio_mask("이메일: [EMAIL]")
    assert "[EMAIL]" in result
    assert result == "이메일: [EMAIL]"
    assert "[NAME]" not in result


# ── mask_all 합성 (combines pass 1 + pass 2) ────────────────────────────────


def test_mask_all_name_and_phone():
    text = "연구책임자: 김연구 연구원의 전화번호는 010-1234-5678 입니다."
    result = mask_all(text)
    assert "[NAME]" in result
    assert "[PHONE]" in result
    assert "김연구" not in result
    assert "010-1234-5678" not in result


def test_mask_all_affiliation_and_email():
    text = "서울대학교 교수 연락처: prof@snu.ac.kr"
    result = mask_all(text)
    assert "[AFFILIATION]" in result
    assert "[EMAIL]" in result
    assert "서울대학교" not in result
    assert "prof@snu.ac.kr" not in result


def test_mask_all_student_id_and_address():
    text = "학번 2020123456 학생, 주소: 서울특별시 관악구 관악로 1"
    result = mask_all(text)
    assert "[STUDENT_ID]" in result
    assert "[ADDRESS]" in result
