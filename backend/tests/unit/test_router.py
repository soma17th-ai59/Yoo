"""Unit tests for backend.app.graph.nodes.router — TDD Phase 1 (failing → passing)."""

from __future__ import annotations

from unittest.mock import patch

from backend.app.graph.state import GraphState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(msg: str, history: list[dict] | None = None) -> GraphState:
    return GraphState(user_message=msg, history=history or [])


def _patch_solar(return_value: dict):
    """Patch the solar complete call inside the router module."""
    return patch(
        "backend.app.graph.nodes.router._solar_complete",
        return_value=return_value,
    )


# ---------------------------------------------------------------------------
# Intent classification — one test per intent (7 intents × ~2 examples = 14+)
# ---------------------------------------------------------------------------

class TestIntentClassification:
    def test_upload_form_hwpx_attachment(self):
        with _patch_solar({"intent": "upload_form", "confidence": 0.95}):
            from backend.app.graph.nodes.router import route
            result = route(_state("BK21 양식 파일 올렸습니다"))
        assert result["intent"] == "upload_form"

    def test_upload_form_폼_업로드(self):
        with _patch_solar({"intent": "upload_form", "confidence": 0.92}):
            from backend.app.graph.nodes.router import route
            result = route(_state("폼 업로드 완료했어요"))
        assert result["intent"] == "upload_form"

    def test_upload_form_양식_첨부(self):
        with _patch_solar({"intent": "upload_form", "confidence": 0.88}):
            from backend.app.graph.nodes.router import route
            result = route(_state("hwpx 파일 첨부했어요"))
        assert result["intent"] == "upload_form"

    def test_upload_material_이력서(self):
        with _patch_solar({"intent": "upload_material", "confidence": 0.93}):
            from backend.app.graph.nodes.router import route
            result = route(_state("이력서를 업로드했습니다"))
        assert result["intent"] == "upload_material"

    def test_upload_material_연구계획서(self):
        with _patch_solar({"intent": "upload_material", "confidence": 0.91}):
            from backend.app.graph.nodes.router import route
            result = route(_state("연구계획서 파일을 올렸어요"))
        assert result["intent"] == "upload_material"

    def test_upload_material_논문(self):
        with _patch_solar({"intent": "upload_material", "confidence": 0.87}):
            from backend.app.graph.nodes.router import route
            result = route(_state("논문 PDF 첨부했어요"))
        assert result["intent"] == "upload_material"

    def test_start_fill_양식_채워줘(self):
        with _patch_solar({"intent": "start_fill", "confidence": 0.97}):
            from backend.app.graph.nodes.router import route
            result = route(_state("양식 채워줘"))
        assert result["intent"] == "start_fill"

    def test_start_fill_자동채우기(self):
        with _patch_solar({"intent": "start_fill", "confidence": 0.96}):
            from backend.app.graph.nodes.router import route
            result = route(_state("자동으로 채워주세요"))
        assert result["intent"] == "start_fill"

    def test_start_fill_시작(self):
        with _patch_solar({"intent": "start_fill", "confidence": 0.90}):
            from backend.app.graph.nodes.router import route
            result = route(_state("작성 시작해주세요"))
        assert result["intent"] == "start_fill"

    def test_rewrite_item_다시써줘(self):
        with _patch_solar({"intent": "rewrite_item", "confidence": 0.94}):
            from backend.app.graph.nodes.router import route
            result = route(_state("3번 다시 써주세요"))
        assert result["intent"] == "rewrite_item"

    def test_rewrite_item_수정(self):
        with _patch_solar({"intent": "rewrite_item", "confidence": 0.89}):
            from backend.app.graph.nodes.router import route
            result = route(_state("연구목표 부분 수정해줘"))
        assert result["intent"] == "rewrite_item"

    def test_rewrite_item_재작성(self):
        with _patch_solar({"intent": "rewrite_item", "confidence": 0.91}):
            from backend.app.graph.nodes.router import route
            result = route(_state("첫 번째 항목 다시 작성해줘"))
        assert result["intent"] == "rewrite_item"

    def test_change_tone_격식체(self):
        with _patch_solar({"intent": "change_tone", "confidence": 0.93}):
            from backend.app.graph.nodes.router import route
            result = route(_state("좀 더 격식체로 바꿔줘"))
        assert result["intent"] == "change_tone"

    def test_change_tone_논문체(self):
        with _patch_solar({"intent": "change_tone", "confidence": 0.90}):
            from backend.app.graph.nodes.router import route
            result = route(_state("논문 스타일로 수정해주세요"))
        assert result["intent"] == "change_tone"

    def test_change_tone_어조변경(self):
        with _patch_solar({"intent": "change_tone", "confidence": 0.88}):
            from backend.app.graph.nodes.router import route
            result = route(_state("어조를 부드럽게 바꿔주세요"))
        assert result["intent"] == "change_tone"

    def test_add_material_이자료도(self):
        with _patch_solar({"intent": "add_material", "confidence": 0.92}):
            from backend.app.graph.nodes.router import route
            result = route(_state("이 자료도 참고해"))
        assert result["intent"] == "add_material"

    def test_add_material_추가자료(self):
        with _patch_solar({"intent": "add_material", "confidence": 0.88}):
            from backend.app.graph.nodes.router import route
            result = route(_state("추가 자료 드릴게요"))
        assert result["intent"] == "add_material"

    def test_add_material_참고파일(self):
        with _patch_solar({"intent": "add_material", "confidence": 0.91}):
            from backend.app.graph.nodes.router import route
            result = route(_state("참고할 파일 하나 더 올릴게요"))
        assert result["intent"] == "add_material"

    def test_general_qa_무엇인가요(self):
        with _patch_solar({"intent": "general_qa", "confidence": 0.85}):
            from backend.app.graph.nodes.router import route
            result = route(_state("BK21 사업이 뭔가요?"))
        assert result["intent"] == "general_qa"

    def test_general_qa_안녕(self):
        with _patch_solar({"intent": "general_qa", "confidence": 0.80}):
            from backend.app.graph.nodes.router import route
            result = route(_state("안녕하세요"))
        assert result["intent"] == "general_qa"

    def test_general_qa_도움말(self):
        with _patch_solar({"intent": "general_qa", "confidence": 0.78}):
            from backend.app.graph.nodes.router import route
            result = route(_state("어떻게 사용하면 되나요?"))
        assert result["intent"] == "general_qa"


# ---------------------------------------------------------------------------
# State update — intent and history
# ---------------------------------------------------------------------------

class TestStateUpdate:
    def test_returns_dict(self):
        with _patch_solar({"intent": "start_fill", "confidence": 0.95}):
            from backend.app.graph.nodes.router import route
            result = route(_state("채워줘"))
        assert isinstance(result, dict)

    def test_returns_intent_key(self):
        with _patch_solar({"intent": "start_fill", "confidence": 0.95}):
            from backend.app.graph.nodes.router import route
            result = route(_state("채워줘"))
        assert "intent" in result

    def test_returns_history_key_on_success(self):
        with _patch_solar({"intent": "start_fill", "confidence": 0.95}):
            from backend.app.graph.nodes.router import route
            result = route(_state("채워줘"))
        assert "history" in result

    def test_history_appended_with_user_message(self):
        with _patch_solar({"intent": "start_fill", "confidence": 0.95}):
            from backend.app.graph.nodes.router import route
            result = route(_state("채워줘"))
        history = result["history"]
        assert any(t["role"] == "user" and "채워줘" in t["content"] for t in history)

    def test_previous_history_preserved(self):
        prev = [{"role": "user", "content": "이전 메시지"}]
        with _patch_solar({"intent": "general_qa", "confidence": 0.80}):
            from backend.app.graph.nodes.router import route
            result = route(_state("새 메시지", history=prev))
        contents = [t["content"] for t in result["history"]]
        assert "이전 메시지" in contents
        assert "새 메시지" in contents


# ---------------------------------------------------------------------------
# Disambiguation — confidence < 0.7
# ---------------------------------------------------------------------------

class TestDisambiguation:
    def test_low_confidence_produces_errors(self):
        with _patch_solar({
            "intent": "start_fill",
            "confidence": 0.55,
            "disambiguation": "양식 자동 채우기를 원하시나요?",
        }):
            from backend.app.graph.nodes.router import route
            result = route(_state("뭔가 해줘"))
        assert "errors" in result
        assert len(result["errors"]) > 0

    def test_low_confidence_error_contains_disambiguation(self):
        with _patch_solar({
            "intent": "start_fill",
            "confidence": 0.55,
            "disambiguation": "양식 자동 채우기를 원하시나요?",
        }):
            from backend.app.graph.nodes.router import route
            result = route(_state("뭔가 해줘"))
        assert any("양식 자동 채우기" in e for e in result["errors"])

    def test_low_confidence_no_missing_disambiguation_key_uses_fallback(self):
        with _patch_solar({"intent": "general_qa", "confidence": 0.45}):
            from backend.app.graph.nodes.router import route
            result = route(_state("뭔가 해줘"))
        assert "errors" in result
        assert len(result["errors"]) > 0

    def test_boundary_exactly_07_is_not_disambiguation(self):
        with _patch_solar({"intent": "start_fill", "confidence": 0.7}):
            from backend.app.graph.nodes.router import route
            result = route(_state("채워줘"))
        assert "errors" not in result or result.get("errors") == []


# ---------------------------------------------------------------------------
# Error handling — invalid Solar responses
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_invalid_json_produces_error(self):
        with patch(
            "backend.app.graph.nodes.router._solar_complete",
            side_effect=Exception("JSON decode error"),
        ):
            from backend.app.graph.nodes.router import route
            result = route(_state("채워줘"))
        assert "errors" in result
        assert len(result["errors"]) > 0

    def test_unknown_intent_produces_error(self):
        with _patch_solar({"intent": "totally_unknown_intent", "confidence": 0.99}):
            from backend.app.graph.nodes.router import route
            result = route(_state("채워줘"))
        assert "errors" in result
        assert len(result["errors"]) > 0

    def test_missing_intent_key_produces_error(self):
        with _patch_solar({"confidence": 0.90}):
            from backend.app.graph.nodes.router import route
            result = route(_state("채워줘"))
        assert "errors" in result
        assert len(result["errors"]) > 0

    def test_missing_confidence_key_produces_error(self):
        with _patch_solar({"intent": "start_fill"}):
            from backend.app.graph.nodes.router import route
            result = route(_state("채워줘"))
        assert "errors" in result
        assert len(result["errors"]) > 0

    def test_no_user_message_produces_error(self):
        with _patch_solar({"intent": "general_qa", "confidence": 0.85}):
            from backend.app.graph.nodes.router import route
            result = route(GraphState())
        assert "errors" in result
        assert len(result["errors"]) > 0
