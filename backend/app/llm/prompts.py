"""Korean system prompts and message builders for Solar LLM nodes.

Zero LangGraph imports. Zero openai imports.
All prompt strings are Korean per spec §5.6 / CLAUDE.md conventions.
"""

from __future__ import annotations

from backend.app.hwpx.models import FormDoc

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

ROUTER_SYS: str = """\
당신은 사용자의 의도를 분류하는 라우터입니다.
사용자의 메시지를 읽고, 아래 7가지 의도 중 하나로 정확히 분류하세요.

의도 목록:
- upload_form: 사용자가 .hwpx 형식의 공문서 양식을 업로드하였거나 업로드 의사를 밝힌 경우
- upload_material: 사용자가 이력서, 연구계획서, 논문 등 참고자료를 업로드하였거나 업로드 의사를 밝힌 경우
- start_fill: 사용자가 양식 자동 채우기를 시작하길 원하는 경우
- rewrite_item: 사용자가 특정 항목의 내용을 다시 작성하거나 수정하길 원하는 경우
- change_tone: 사용자가 특정 항목의 어조(격식체, 논문체 등)를 변경하길 원하는 경우
- add_material: 사용자가 추가 참고자료를 제공하거나 추가하길 원하는 경우
- general_qa: 양식 작성과 무관한 일반 질문인 경우

응답 규칙:
1. 반드시 JSON 형식으로만 응답하세요.
2. 기본 형식: {"intent": "<의도>", "confidence": <0.0–1.0>}
3. confidence가 0.7 미만이면 disambiguation 필드를 추가하고, 사용자에게 의도를 확인하는 질문을 한국어로 작성하세요.
   예: {"intent": "start_fill", "confidence": 0.55, "disambiguation": "양식 자동 채우기를 시작하시겠습니까?"}
4. intent 값은 위 7가지 중 하나여야 하며, 추가 설명 없이 JSON만 반환하세요.
"""

PLANNER_SYS: str = """\
당신은 연구비 신청 양식의 각 항목을 분석하고 작성 계획을 수립하는 플래너입니다.
사용자가 제공한 양식 항목 목록과 참고자료 목록을 바탕으로, 각 항목에 대한 작성 계획을 JSON 배열로 반환하세요.

각 항목(ItemPlan)의 구조:
{
  "item_id": "항목 ID",
  "source_evidence": ["참고자료 파일명1", "참고자료 파일명2"],
  "confidence": 0.0–1.0,
  "needs_question": true 또는 false,
  "question": "사용자에게 물어볼 질문 (needs_question이 true인 경우)" 또는 null
}

규칙:
1. source_evidence는 해당 항목 작성에 활용 가능한 참고자료 파일명 목록입니다.
2. confidence는 현재 참고자료만으로 항목을 작성할 수 있는 자신감 수준입니다.
3. confidence가 0.6 미만이면 needs_question을 true로 설정하고, 항목 작성에 필요한 추가 정보를 묻는 질문을 한국어로 작성하세요.
4. 모든 항목에 대해 ItemPlan을 반환하며, JSON 배열 형태로만 응답하세요.
5. PII 항목(is_pii=true)은 source_evidence를 빈 배열로, confidence를 0.0으로, needs_question을 false로 설정하세요.
"""

GENERATOR_SYS: str = """\
당신은 대한민국 국가 연구비 지원사업 신청서를 작성하는 전문 작성자입니다.
제공된 참고자료를 바탕으로 지정된 양식 항목의 내용을 한국어로 작성하세요.

작성 규칙:
1. 학술적이고 격식 있는 한국어 문어체로 작성하세요.
2. 모든 주장은 제공된 참고자료(출처)에 근거해야 합니다.
3. 반드시 JSON 형식으로 응답하세요: {"text": "작성된 내용", "citations": ["참고자료ID1", "참고자료ID2"]}
4. citations 배열에는 실제로 참조한 참고자료의 파일명을 포함하세요. 인용되지 않은 주장을 포함하지 마세요.
5. 절대로 개인정보를 포함하지 마세요: 이름, 주민번호, 연락처, 이메일, 주소, 계좌번호 등 모든 개인정보(이하 PII)는 절대 작성하지 마세요.
6. 개인정보(이름, 주민번호, 연락처, 이메일, 주소 등)가 포함되어야 할 것 같은 경우에는 해당 부분을 비워두거나 [본인 직접 입력]으로 표시하세요.
7. 예상 글자 수(expected_chars)가 명시된 경우, 해당 범위 내로 작성하세요.
"""

VERIFIER_SYS: str = """\
당신은 AI가 작성한 연구비 신청서 항목 내용을 검토하는 검증자입니다.
작성된 텍스트가 정확하고, 인용이 적절하며, 양식 요건에 부합하는지 확인하세요.

검토 기준:
1. 작성된 내용이 제공된 참고자료(citations)에 근거하는가?
2. 인용되지 않은 주장이나 허구의 사실이 포함되어 있지 않은가?
3. 개인정보(이름, 주민번호, 연락처 등)가 포함되어 있지 않은가?
4. 한국어 학술 문어체로 적절히 작성되었는가?
5. 양식 항목의 목적과 부합하는가?

응답 규칙:
- 반드시 JSON 형식으로만 응답하세요: {"verdict": "<판정>", "reason": "<이유>"}
- verdict 값:
  - "ok": 내용이 정확하고 인용이 유효하며 요건에 부합함
  - "retry": 수정이 필요한 구체적 문제가 발견됨 (reason에 수정 방향을 명시)
  - "soft_fail": 문제가 있으나 경고 후 진행 가능한 수준임
- reason은 한국어로 간결하게 작성하세요.
"""

# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

_MAX_HISTORY_TURNS = 5


def build_router_messages(history: list[dict], user_msg: str) -> list[dict]:
    """Build message list for the Router node.

    Includes up to the last _MAX_HISTORY_TURNS turns from history, sandwiched
    between the system prompt and the final user message.
    """
    messages: list[dict] = [{"role": "system", "content": ROUTER_SYS}]
    recent = history[-_MAX_HISTORY_TURNS:] if history else []
    messages.extend({"role": m["role"], "content": m["content"]} for m in recent)
    messages.append({"role": "user", "content": user_msg})
    return messages


def build_planner_messages(form_doc: FormDoc, materials: list[dict]) -> list[dict]:
    """Build message list for the Planner node."""
    items_summary = "\n".join(
        f"- item_id: {item.item_id} | label: {item.label} | section: {item.section}"
        + (f" | expected_chars: {item.expected_chars}" if item.expected_chars is not None else "")
        + (f" | is_pii: {item.is_pii}" if item.is_pii else "")
        for item in form_doc.items
    )

    materials_summary = "\n".join(
        f"- filename: {mat['filename']} | summary: {mat.get('summary', '')}"
        for mat in materials
    ) if materials else "참고자료 없음"

    user_content = f"""\
## 양식 항목 목록
{items_summary}

## 참고자료 목록
{materials_summary}

위 항목 목록에 대해 ItemPlan 배열을 JSON으로 반환하세요.
"""
    return [
        {"role": "system", "content": PLANNER_SYS},
        {"role": "user", "content": user_content},
    ]


def build_generator_messages(
    item_plan: dict,
    materials: list[dict],
    form_doc: FormDoc,
) -> list[dict]:
    """Build message list for the Generator node."""
    item_id = item_plan["item_id"]
    target_item = next((i for i in form_doc.items if i.item_id == item_id), None)

    if target_item is not None:
        item_detail = (
            f"label: {target_item.label}\n"
            f"section: {target_item.section}\n"
            + (f"expected_chars: {target_item.expected_chars}\n" if target_item.expected_chars is not None else "")
        )
    else:
        item_detail = f"item_id: {item_id}"

    source_ids: set[str] = set(item_plan.get("source_evidence", []))
    relevant_mats = [m for m in materials if m["filename"] in source_ids] if source_ids else materials

    materials_text = "\n\n".join(
        f"[{mat['filename']}]\n{mat.get('masked_text', mat.get('summary', ''))}"
        for mat in relevant_mats
    ) if relevant_mats else "참고자료 없음"

    user_content = f"""\
## 작성 대상 항목
{item_detail}

## 참고자료
{materials_text}

위 참고자료를 바탕으로 항목 내용을 작성하고, 반드시 JSON 형식으로 반환하세요.
형식: {{"text": "작성된 내용", "citations": ["참고자료 파일명1", ...]}}
인용(citations)은 실제 참조한 참고자료 파일명만 포함하세요.
"""
    return [
        {"role": "system", "content": GENERATOR_SYS},
        {"role": "user", "content": user_content},
    ]


def build_verifier_messages(
    draft: dict,
    form_doc: FormDoc,
    materials: list[dict],
) -> list[dict]:
    """Build message list for the Verifier node."""
    item_id = draft.get("item_id", "")
    target_item = next((i for i in form_doc.items if i.item_id == item_id), None)

    item_context = ""
    if target_item is not None:
        item_context = (
            f"label: {target_item.label}\n"
            f"section: {target_item.section}\n"
            + (f"expected_chars: {target_item.expected_chars}\n" if target_item.expected_chars is not None else "")
        )

    citations: list[str] = draft.get("citations", [])
    citations_str = ", ".join(citations) if citations else "없음"

    user_content = f"""\
## 검토 대상 항목
{item_context}

## 작성된 내용
{draft.get("text", "")}

## 인용된 참고자료
{citations_str}

위 내용을 검토하고, 반드시 JSON 형식으로 반환하세요.
형식: {{"verdict": "ok" | "retry" | "soft_fail", "reason": "판정 이유"}}
"""
    return [
        {"role": "system", "content": VERIFIER_SYS},
        {"role": "user", "content": user_content},
    ]
