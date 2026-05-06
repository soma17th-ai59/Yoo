"""Generate a brief Korean summary of a material using Solar LLM.

Input MUST already be PII-masked before calling summarize().
Zero LangGraph imports per module purity rules.
"""

from __future__ import annotations

from backend.app.llm import solar as _solar_mod

_SYSTEM_PROMPT: str = """\
당신은 연구 관련 문서를 요약하는 전문가입니다.
제공된 문서의 핵심 내용을 2~3문장으로 간결하게 한국어로 요약하세요.
개인정보를 언급하지 말고, 연구 내용, 경력, 성과 등 실질적인 내용 위주로 요약하세요.
"""


def _solar_complete(messages: list[dict]) -> str:
    """Thin wrapper so tests can patch a single symbol."""
    return _solar_mod.complete(messages, json_mode=False)  # type: ignore[return-value]


def summarize(masked_text: str, filename: str) -> str:
    """Generate a brief summary of material using Solar.

    Input MUST already be PII-masked. Returns a 2-3 sentence Korean summary.
    """
    truncated = masked_text[:4000] if len(masked_text) > 4000 else masked_text
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"파일명: {filename}\n\n내용:\n{truncated}\n\n위 내용을 2~3문장으로 한국어로 요약하세요.",
        },
    ]
    return _solar_complete(messages)
