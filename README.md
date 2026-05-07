# HwpAgent

LangGraph-based chatbot that auto-fills `.hwpx` Korean national-funding-program forms (BK21, 학부생연구지원, 한국연구재단 등) from your existing materials (CV, prior proposals, research records). Powered by Upstage **Solar** LLM.

> 학부연구생·대학원생을 위한 한글 양식 자동 작성 AI 어시스턴트.
> 자료를 업로드하면 양식 빈칸을 자료 기반으로 채워주고, 부족한 부분만 묻습니다.

## Architecture

```
Streamlit chat UI ──HTTP/SSE──▶ FastAPI ──▶ LangGraph
                                              │
        Router → FormParser → MaterialIngestor → Planner →
        (Generator | Question) → Verifier → Renderer
                                              │
                                          Upstage Solar
```

`hwpx/`, `materials/`, `pii/`, `llm/` are pure Python modules (zero LangGraph imports). `graph/nodes/*` lift them into `GraphState` transitions. The wiring is in `backend/app/graph/graph.py`. HWPX is a ZIP-of-XML parsed/edited with `lxml`.

Sessions are **memory-only**: nothing user-supplied is written to disk.

## Prerequisites

- Python 3.11+
- An Upstage Solar API key (`SOLAR_API_KEY`)
- `uv` (recommended) or pip
- Docker + Compose (for the docker run mode)

## Run — local

```powershell
# 1. environment + dependencies
uv sync                         # or: python -m venv .venv ; pip install -e ".[dev]"

# 2. configure Solar
Copy-Item .env.example .env
# edit .env: SOLAR_API_KEY=...

# 3. run (two terminals)
uv run uvicorn backend.app.main:app --reload --port 8000
uv run streamlit run frontend/streamlit_app.py
```

Open http://localhost:8501.

## Run — docker

```bash
cp .env.example .env            # edit SOLAR_API_KEY
docker compose up --build
```

- backend: http://localhost:8000 (FastAPI + SSE)
- frontend: http://localhost:8501 (Streamlit)

The `frontend` container talks to `backend` on the internal Compose network via `BACKEND_URL=http://backend:8000`. Neither container mounts a volume for user data — sessions are in-memory only.

## Tests + KPIs

```powershell
uv run pytest -q                # full suite (backend + frontend smoke + eval harness)
uv run pytest backend/tests/integration/test_scenarios.py -q
uv run python eval/run_kpi.py   # K1 + K5 (offline)
SOLAR_API_KEY=... uv run python eval/run_kpi.py --live   # adds K2 (live)
```

The KPI script exits non-zero if K1 < 0.85 or K5 > 0.

### KPI snapshot (offline, fixture-only)

| KPI | Target | Actual |
| --- | --- | --- |
| K1 form-blank F1 | ≥ 0.85 | 1.000 (3 fixture forms) |
| K5 PII leak count | = 0 | 0 (3 fixture material sets) |
| K2 router accuracy | ≥ 0.90 | live-only (run with `--live`) |
| K3 auto-fill rate | ≥ 0.60 | live-only |
| K4 verifier first-pass | ≥ 0.75 | live-only |
| K6 first-preview latency p50 | ≤ 30s | live-only |

## Hard rules (PII safety, spec §7)

1. All material text passes `pii.regex_masker → pii.presidio_masker → pii.mask_all` before any Solar call.
2. Form items whose label contains 성명/주민등록번호/연락처/주소/계좌/학번/사번/이메일 are flagged `is_pii=True`. Generator skips them; Renderer writes `[본인 직접 입력]`.
3. `pii.output_guard` scans Generator output for jumin/account/card/phone/email patterns. On hit, retry up to 2× then mark `[확인 필요]`.
4. Sessions are in-memory only with a 2-hour TTL. Nothing is persisted to disk.

See [`CLAUDE.md`](./CLAUDE.md) for full conventions, scope, and the canonical task plan.
