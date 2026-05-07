FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY frontend ./frontend
COPY backend/app/__init__.py ./backend/app/__init__.py

RUN pip install --upgrade pip \
 && pip install streamlit==1.36.* httpx==0.27.*

EXPOSE 8501

CMD ["streamlit", "run", "frontend/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
