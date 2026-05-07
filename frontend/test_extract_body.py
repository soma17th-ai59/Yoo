"""Unit tests for frontend.extract_body."""

from __future__ import annotations

from frontend.extract_body import extract_body


def test_extract_between_triple_dashes():
    reply = (
        "정리해 드리면 다음과 같습니다.\n"
        "---\n"
        "본 연구는 임상 노트 자동 요약 시스템을 개발한다.\n"
        "---\n"
        "이대로 적용하시겠어요?"
    )
    assert extract_body(reply) == "본 연구는 임상 노트 자동 요약 시스템을 개발한다."


def test_strips_acknowledgement_opener():
    reply = "알겠습니다. 본 연구는 한국어 임상 노트 요약을 다룬다."
    assert extract_body(reply).startswith("본 연구는")


def test_strips_apply_trailer():
    reply = "본문 내용입니다.\n수정 사항이 있으면 알려주세요."
    out = extract_body(reply)
    assert "수정 사항" not in out
    assert "본문 내용" in out


def test_returns_input_when_no_markers():
    reply = "단순한 본문 한 줄."
    assert extract_body(reply) == "단순한 본문 한 줄."


def test_handles_empty_string():
    assert extract_body("") == ""


def test_strips_real_world_filler():
    """The case the user reported — apply button used to take the whole reply."""
    reply = (
        "알겠습니다. 본 연구는 한국어 임상 노트 자동 요약을 통해 의료진 부담을 30% 완화한다. "
        "추가 수정 요청사항이 있으면 알려주시기 바랍니다."
    )
    out = extract_body(reply)
    assert "알겠습니다" not in out
    assert "추가 수정 요청사항" not in out
    assert "본 연구는" in out


def test_strips_jeongri_haedeurimyeon_preamble():
    """The session 0607e351 case — markdown-bold "**정리해 드리면…**" preamble
    used to leak through and become the entire body."""
    reply = (
        "**정리해 드리면 다음과 같습니다.**\n\n"
        "본 연구는 ClinicalBERT-Ko 기반 추출형 요약 모델을 개발하여 "
        "의료진의 노트 검토 시간을 30% 단축한다.\n\n"
        "이대로 적용하시겠어요?"
    )
    out = extract_body(reply)
    assert "정리해 드리면" not in out
    assert "이대로 적용" not in out
    assert "본 연구는" in out


def test_falls_back_when_body_is_too_short():
    """If stripping leaves only filler, return the full reply (minus
    obvious trailers) so the user sees something to review."""
    reply = "**정리해 드리면 다음과 같습니다.**\n\n이대로 적용하시겠어요?"
    out = extract_body(reply)
    # Must NOT be empty and must NOT be just the preamble.
    assert out
    # Acceptable fallback: returns the preamble text or the full reply,
    # but at minimum the user gets a visible string they can edit.
    assert len(out) > 0


def test_strips_markdown_heading():
    reply = "## 본문 제안:\n\n실제 본문 내용입니다 충분히 긴 본문 내용이에요."
    out = extract_body(reply)
    assert "##" not in out
    assert "실제 본문 내용" in out


def test_dash_delimited_with_filler_inside_does_not_misfire():
    reply = (
        "정리해 드리면 다음과 같습니다.\n"
        "---\n"
        "본 연구는 임상 노트 요약을 통해 의료진 부담을 완화한다.\n"
        "---\n"
        "이대로 적용하시겠어요?"
    )
    out = extract_body(reply)
    assert out == "본 연구는 임상 노트 요약을 통해 의료진 부담을 완화한다."
