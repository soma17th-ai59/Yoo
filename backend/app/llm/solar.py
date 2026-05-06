"""Thin OpenAI-compatible wrapper for Upstage Solar LLM.

Callers MUST apply pii.mask_all() to all text before passing messages here.
This module has zero LangGraph imports.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

import openai

from backend.app.config import settings

_BASE_URL: str = settings.solar_base_url

_client: openai.OpenAI = openai.OpenAI(
    api_key=settings.solar_api_key,
    base_url=_BASE_URL,
)

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds; doubled each attempt


def _sleep(seconds: float) -> None:  # thin wrapper so tests can patch it
    time.sleep(seconds)


def complete(
    messages: list[dict],
    json_mode: bool = False,
) -> dict | str:
    """Call Solar chat completions with optional retry logic.

    Returns parsed dict when json_mode=True, raw str otherwise.
    Retries up to _MAX_RETRIES times on 5xx or timeout, then re-raises.
    """
    kwargs: dict = dict(
        model=settings.solar_model,
        messages=messages,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = _client.chat.completions.create(**kwargs)
            content: str = response.choices[0].message.content
            if json_mode:
                return json.loads(content)
            return content
        except openai.APIStatusError as exc:
            if exc.status_code < 500:
                raise  # 4xx errors are not retryable
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                _sleep(_BACKOFF_BASE * (2**attempt))
        except openai.APITimeoutError as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                _sleep(_BACKOFF_BASE * (2**attempt))

    raise last_exc  # type: ignore[misc]


def stream(messages: list[dict]) -> Iterator[str]:
    """Yield text chunks from a streaming Solar call.

    No retry — streaming cannot resume mid-stream; callers must re-invoke on error.
    """
    response = _client.chat.completions.create(
        model=settings.solar_model,
        messages=messages,
        stream=True,
    )
    for chunk in response:
        content = chunk.choices[0].delta.content
        if content is not None:
            yield content
