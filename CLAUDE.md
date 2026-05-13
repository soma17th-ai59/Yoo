# HwpAgent — Claude Working Notes

## What this is
LangGraph-based chatbot that auto-fills `.hwpx` Korean national-funding-program forms (BK21, 학부생연구지원, 한국연구재단 등) from user materials (CV, prior proposals, research records). Uses Upstage **Solar** LLM. 2-week MVP, 5-person team. Spec lives in `plan.pdf` (28 pages); implementation plan lives at `~/.claude/plans/read-plan-pdf-and-make-greedy-waffle.md`.

The killer feature is **양식 자동 채우기** (form auto-fill) — *not* generic Hangul editing.

## Run
- Backend:  `uvicorn backend.app.main:app --reload --port 8000`
- Frontend: `streamlit run frontend/streamlit_app.py`
- Tests:    `pytest -q`
- KPIs:     `python eval/run_kpi.py`
- Lint:     `ruff check . && ruff format --check .`
- Compose:  `docker compose up --build`

## Hard rules (spec §7 — non-negotiable)
1. **Never send PII to the LLM.** All material text passes through `pii.regex_masker` → `pii.presidio_masker` → `pii.mask_all` *before* any Solar call. Verify with the spy in `tests/unit/test_node_material_ingestor.py`.
2. **Never auto-fill PII form fields via the LLM.** Items whose `label` contains 성명/주민등록번호/연락처/주소/계좌/학번/사번/이메일/카드/외국인등록번호 must be flagged `is_pii=True` by `pii.form_detector`. The Generator emits an *empty* `DraftItem(status="pii", is_pii=True)` for these — Solar is never called for them. The user types their value via the UI (`PUT /drafts`) and the Renderer writes that typed text. `item-chat` rejects PII items (LLM path). Net invariant: PII text **never** appears in any LLM prompt — only in the user's browser, in-memory session state, and the final .hwpx.
3. **Memory-only sessions.** No disk persistence of user files, materials, or chat history. `SessionStore` is an in-memory dict with TTL. The only files that may touch disk are `tests/fixtures/`.
4. **Evidence-only generation.** Generator must emit `{text, citations[]}` with citations referencing material IDs. Verifier rejects any draft with un-cited claims.
5. **Output guard catches regressions.** `pii.output_guard` scans Generator output for jumin/account/card/phone/email patterns; on hit, retry up to 2× then mark `[확인 필요]`.

## LangGraph nodes (each has a single responsibility)

```
form_parser → material_ingestor → planner → generator → verifier → END
```

Straight-line pipeline. Runs **only** when `POST /api/sessions/{sid}/fill` is called (SSE stream).

- **Router/Question nodes are gone.** Adaptive intent routing was refactored away. Per-item actions (적용/수정/대화/다시) now live as `/api/sessions/{sid}/items/*` endpoints that bypass the graph entirely.
- **Renderer is not a graph node.** `graph/nodes/renderer.py::render_output` is a plain function called lazily by `GET /output.hwpx`. Default writes only locked drafts; `?include_unlocked=true` writes every generated draft.
- **Error cutoff.** Every edge is conditional on `state.errors`; any node appending an error short-circuits the rest of the pipeline to `END`.
- **Module purity preserved.** Only `graph.py` imports LangGraph; nodes are `(state) -> dict` plain functions.

See `backend/app/graph/graph.py` for the canonical wiring.

## Code conventions
- **Module purity.** `hwpx/`, `materials/`, `pii/`, `llm/` import nothing from `langgraph` / `graph/`. They're plain Python and unit-testable in isolation.
- **Thin nodes.** `graph/nodes/*` take `GraphState`, call into pure modules, return state diffs. Don't hide business logic in nodes.
- **Type hints everywhere.** Pydantic v2 (`BaseModel`) for anything that crosses HTTP or graph boundaries.
- **One test file per module.** Fixtures in `backend/tests/fixtures/`. PII tests must total ≥50 across `tests/unit/test_pii_*.py` (KPI K5 / 정성 KPI).
- **Korean copy stays Korean.** Don't translate UX strings, prompt instructions, or fixture labels to English.
- **No new comments unless WHY is non-obvious.** The code base follows the global "no narration comments" rule.

## Stack
- Python 3.11+ · FastAPI · Streamlit · LangGraph 0.2+ · Upstage Solar (OpenAI-compatible)
- `lxml` + `zipfile` for HWPX (HWPX is a ZIP of XML; `Contents/section*.xml` is the body)
- `pypdf` / `python-docx` / `pdfplumber` for material extraction
- Microsoft Presidio + Korean custom recognizers for PII pass 2
- `pytest` + `pytest-asyncio` + `httpx`

## KPIs (spec §8)
- K1 form-blank F1 ≥ 0.85
- K2 Router intent accuracy ≥ 0.90 (50-command test set)
- K3 auto-fill rate ≥ 0.60
- K4 Verifier first-pass ≥ 0.75
- K5 PII leak count = 0  ← blocking
- K6 first-preview latency ≤ 30s p50

`python eval/run_kpi.py` exits non-zero if K5 ≠ 0 or K1 < 0.85.

## Scope reminders (V1 MVP only)
**In:** F1–F6 from spec §4.1 — form auto-fill, table fill, format preservation, conversational info-gathering, follow-up routing, PII masking.
**Out:** legacy `.hwp` (V1.5), char-count auto-validation (V2), undo/redo, user accounts, persistent KB, real-time collaboration.

## Spec
Authoritative: `plan.pdf`. Re-read before executing each phase:
- §3 (Agent role — administrative-assistant metaphor; **no** autonomous form mutation)
- §5.3 (GraphState fields + node IO contracts)
- §5.6 (prompt structures — copy verbatim)
- §7 (PII absolute rules)
- §8 (KPI definitions)
