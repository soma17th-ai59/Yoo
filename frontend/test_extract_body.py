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
