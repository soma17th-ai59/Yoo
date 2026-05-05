# HwpAgent

LangGraph-based chatbot that auto-fills `.hwpx` Korean national-funding-program forms from your existing materials (CV, prior proposals, research records). Powered by Upstage **Solar** LLM.

> 학부연구생·대학원생을 위한 한글 양식 자동 작성 AI 어시스턴트.
> 자료를 업로드하면 양식 빈칸을 자료 기반으로 채워주고, 부족한 부분만 묻습니다.

## Status

V1 MVP — under construction. See `plan.pdf` for the full v2 spec (28 pages) and `~/.claude/plans/read-plan-pdf-and-make-greedy-waffle.md` for the task-by-task implementation plan.

## Quickstart

```bash
# 1. Python 3.11+ environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # PowerShell
pip install -e ".[dev]"

# 2. Configure Solar API
cp .env.example .env
# edit .env and set SOLAR_API_KEY

# 3. Run (two terminals)
uvicorn backend.app.main:app --reload --port 8000
streamlit run frontend/streamlit_app.py

# 4. Tests + KPIs
pytest -q
python eval/run_kpi.py
```

## Privacy

This service **does not** send personal information to the LLM and **does not** auto-fill PII form fields (성명/주민등록번호/연락처/주소/계좌/학번 etc.). All sessions are memory-only and discarded on close. See [`CLAUDE.md`](./CLAUDE.md) §"Hard rules" for the enforcement chain.

## Tech

Streamlit ↔ FastAPI (SSE) ↔ LangGraph (Router · FormParser · MaterialIngestor · Planner · Generator · Question · Verifier · Renderer) ↔ Solar API. HWPX parsed/edited via `lxml` + `zipfile`.
