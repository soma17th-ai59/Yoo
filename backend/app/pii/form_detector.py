"""PII form-field detector: flags Items whose label contains PII-sensitive keywords.

flag_pii_items(doc: FormDoc) -> FormDoc
  Returns an updated FormDoc with is_pii=True on matching Items.
  The original FormDoc and its Items are not mutated.
"""

from backend.app.hwpx.models import FormDoc, Item

# Keywords that indicate a form field collects PII.
# Substring matching is intentional: "신청자 성명" contains "성명".
_PII_KEYWORDS: frozenset[str] = frozenset(
    [
        # 성명 / 이름
        "성명",
        "이름",
        # 주민등록번호
        "주민등록번호",
        "주민번호",
        # 연락처 / 전화번호
        "연락처",
        "전화번호",
        "전화",
        # 주소
        "주소",
        # 계좌
        "계좌번호",
        "계좌",
        # 학번 / 사번
        "학번",
        "사번",
        "직원번호",
        # 이메일
        "이메일주소",
        "이메일",
        # 카드번호 / 카드
        "카드번호",
        "카드",
        # 외국인등록번호
        "외국인등록번호",
    ]
)


def _is_pii_label(label: str) -> bool:
    return any(keyword in label for keyword in _PII_KEYWORDS)


def flag_pii_items(doc: FormDoc) -> FormDoc:
    """Return a new FormDoc with is_pii set on Items whose label contains PII keywords."""
    updated_items: list[Item] = [
        item.model_copy(update={"is_pii": True}) if _is_pii_label(item.label) else item
        for item in doc.items
    ]
    return doc.model_copy(update={"items": updated_items})
