"""Tests for backend.app.llm.prompts — message builder shapes and content."""

from __future__ import annotations

from backend.app.hwpx.models import FormDoc, Item
from backend.app.llm.prompts import (
    GENERATOR_SYS,
    PLANNER_SYS,
    VERIFIER_SYS,
    build_generator_messages,
    build_planner_messages,
    build_verifier_messages,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_form_doc() -> FormDoc:
    items = [
        Item(
            item_id="item_001",
            label="연구의 필요성",
            section="연구개요",
            expected_chars=600,
            kind="paragraph",
            xml_xpath="//hp:p[1]",
        ),
        Item(
            item_id="item_002",
            label="연구 목표",
            section="연구개요",
            expected_chars=None,
            kind="paragraph",
            xml_xpath="//hp:p[2]",
        ),
    ]
    return FormDoc(sections=["연구개요"], items=items, tables=[], placeholders=[])


def _make_materials() -> list[dict]:
    return [
        {
            "filename": "cv.pdf",
            "summary": "연구자 이력서",
            "masked_text": "연구자는 10년간 AI 분야 연구를 진행하였다.",
        },
        {
            "filename": "prior_proposal.docx",
            "summary": "이전 연구제안서",
            "masked_text": "본 연구는 딥러닝 기반 자연어 처리 방법론을 탐구한다.",
        },
    ]


def _make_item_plan() -> dict:
    return {
        "item_id": "item_001",
        "source_evidence": ["cv.pdf", "prior_proposal.docx"],
        "confidence": 0.85,
        "needs_question": False,
        "question": None,
    }


def _make_draft() -> dict:
    return {
        "item_id": "item_001",
        "text": "본 연구는 AI 기반 자동화 시스템을 개발하는 것을 목적으로 한다.",
        "citations": ["cv.pdf"],
    }


# ---------------------------------------------------------------------------
# System prompt content tests
# ---------------------------------------------------------------------------


class TestSystemPromptContent:
    def test_planner_sys_nonempty(self):
        assert isinstance(PLANNER_SYS, str)
        assert len(PLANNER_SYS) > 100

    def test_planner_sys_specifies_item_plan_fields(self):
        assert "item_id" in PLANNER_SYS
        assert "confidence" in PLANNER_SYS
        assert "needs_question" in PLANNER_SYS

    def test_generator_sys_nonempty(self):
        assert isinstance(GENERATOR_SYS, str)
        assert len(GENERATOR_SYS) > 100

    def test_generator_sys_contains_citations_instruction(self):
        # Must mention citations — either Korean (출처) or English
        has_citations = "citations" in GENERATOR_SYS or "출처" in GENERATOR_SYS
        assert has_citations, "GENERATOR_SYS must mention citations or 출처"

    def test_generator_sys_no_pii_instruction(self):
        # Must instruct the model NOT to include personal info
        has_pii_warning = (
            "이름" in GENERATOR_SYS or "주민번호" in GENERATOR_SYS or "개인정보" in GENERATOR_SYS
        )
        assert has_pii_warning, "GENERATOR_SYS must warn against PII"

    def test_verifier_sys_nonempty(self):
        assert isinstance(VERIFIER_SYS, str)
        assert len(VERIFIER_SYS) > 100

    def test_verifier_sys_verdict_values(self):
        assert "ok" in VERIFIER_SYS
        assert "retry" in VERIFIER_SYS
        assert "soft_fail" in VERIFIER_SYS


# ---------------------------------------------------------------------------
# build_planner_messages
# ---------------------------------------------------------------------------


class TestBuildPlannerMessages:
    def test_returns_list_of_dicts(self):
        result = build_planner_messages(_make_form_doc(), _make_materials())
        assert isinstance(result, list)
        assert all(isinstance(m, dict) for m in result)

    def test_first_message_is_system(self):
        result = build_planner_messages(_make_form_doc(), _make_materials())
        assert result[0]["role"] == "system"
        assert result[0]["content"] == PLANNER_SYS

    def test_last_message_is_user(self):
        result = build_planner_messages(_make_form_doc(), _make_materials())
        assert result[-1]["role"] == "user"

    def test_user_message_contains_item_ids(self):
        result = build_planner_messages(_make_form_doc(), _make_materials())
        user_content = result[-1]["content"]
        assert "item_001" in user_content
        assert "item_002" in user_content

    def test_user_message_contains_item_labels(self):
        result = build_planner_messages(_make_form_doc(), _make_materials())
        user_content = result[-1]["content"]
        assert "연구의 필요성" in user_content
        assert "연구 목표" in user_content

    def test_user_message_contains_material_filenames(self):
        result = build_planner_messages(_make_form_doc(), _make_materials())
        user_content = result[-1]["content"]
        assert "cv.pdf" in user_content
        assert "prior_proposal.docx" in user_content

    def test_empty_materials(self):
        result = build_planner_messages(_make_form_doc(), [])
        assert isinstance(result, list)
        assert len(result) == 2

    def test_deterministic(self):
        form = _make_form_doc()
        mats = _make_materials()
        r1 = build_planner_messages(form, mats)
        r2 = build_planner_messages(form, mats)
        assert r1 == r2


# ---------------------------------------------------------------------------
# build_generator_messages
# ---------------------------------------------------------------------------


class TestBuildGeneratorMessages:
    def test_returns_list_of_dicts(self):
        result = build_generator_messages(_make_item_plan(), _make_materials(), _make_form_doc())
        assert isinstance(result, list)
        assert all(isinstance(m, dict) for m in result)

    def test_first_message_is_system(self):
        result = build_generator_messages(_make_item_plan(), _make_materials(), _make_form_doc())
        assert result[0]["role"] == "system"
        assert result[0]["content"] == GENERATOR_SYS

    def test_last_message_is_user(self):
        result = build_generator_messages(_make_item_plan(), _make_materials(), _make_form_doc())
        assert result[-1]["role"] == "user"

    def test_user_message_contains_citations_instruction(self):
        result = build_generator_messages(_make_item_plan(), _make_materials(), _make_form_doc())
        user_content = result[-1]["content"]
        has_citations = "citations" in user_content or "출처" in user_content
        assert has_citations, "Generator user message must include citations instruction"

    def test_user_message_contains_item_label(self):
        result = build_generator_messages(_make_item_plan(), _make_materials(), _make_form_doc())
        user_content = result[-1]["content"]
        assert "연구의 필요성" in user_content

    def test_user_message_contains_material_text(self):
        result = build_generator_messages(_make_item_plan(), _make_materials(), _make_form_doc())
        user_content = result[-1]["content"]
        assert "AI 분야 연구" in user_content or "딥러닝" in user_content

    def test_item_with_no_expected_chars(self):
        plan = {
            "item_id": "item_002",
            "source_evidence": ["cv.pdf"],
            "confidence": 0.7,
            "needs_question": False,
            "question": None,
        }
        result = build_generator_messages(plan, _make_materials(), _make_form_doc())
        assert isinstance(result, list)
        assert result[-1]["role"] == "user"

    def test_empty_materials(self):
        result = build_generator_messages(_make_item_plan(), [], _make_form_doc())
        assert isinstance(result, list)
        assert len(result) == 2

    def test_deterministic(self):
        plan = _make_item_plan()
        mats = _make_materials()
        form = _make_form_doc()
        r1 = build_generator_messages(plan, mats, form)
        r2 = build_generator_messages(plan, mats, form)
        assert r1 == r2


# ---------------------------------------------------------------------------
# build_verifier_messages
# ---------------------------------------------------------------------------


class TestBuildVerifierMessages:
    def test_returns_list_of_dicts(self):
        result = build_verifier_messages(_make_draft(), _make_form_doc(), _make_materials())
        assert isinstance(result, list)
        assert all(isinstance(m, dict) for m in result)

    def test_first_message_is_system(self):
        result = build_verifier_messages(_make_draft(), _make_form_doc(), _make_materials())
        assert result[0]["role"] == "system"
        assert result[0]["content"] == VERIFIER_SYS

    def test_last_message_is_user(self):
        result = build_verifier_messages(_make_draft(), _make_form_doc(), _make_materials())
        assert result[-1]["role"] == "user"

    def test_user_message_contains_draft_text(self):
        result = build_verifier_messages(_make_draft(), _make_form_doc(), _make_materials())
        user_content = result[-1]["content"]
        assert "AI 기반 자동화 시스템" in user_content

    def test_user_message_contains_verdict_instruction(self):
        result = build_verifier_messages(_make_draft(), _make_form_doc(), _make_materials())
        user_content = result[-1]["content"]
        has_verdict = "verdict" in user_content or "검토" in user_content
        assert has_verdict

    def test_user_message_contains_citations(self):
        result = build_verifier_messages(_make_draft(), _make_form_doc(), _make_materials())
        user_content = result[-1]["content"]
        assert "cv.pdf" in user_content

    def test_deterministic(self):
        draft = _make_draft()
        form = _make_form_doc()
        mats = _make_materials()
        r1 = build_verifier_messages(draft, form, mats)
        r2 = build_verifier_messages(draft, form, mats)
        assert r1 == r2
