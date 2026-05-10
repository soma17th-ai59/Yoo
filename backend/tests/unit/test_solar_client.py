"""Tests for the Solar LLM client (backend.app.llm.solar)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import openai
import pytest

from backend.app.config import settings
from backend.app.llm.solar import complete, stream

# ---------------------------------------------------------------------------
# Helpers to build mock OpenAI response objects
# ---------------------------------------------------------------------------


def _make_response(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_stream_chunks(texts: list[str]) -> list[MagicMock]:
    chunks = []
    for text in texts:
        delta = MagicMock()
        delta.content = text
        choice = MagicMock()
        choice.delta = delta
        chunk = MagicMock()
        chunk.choices = [choice]
        chunks.append(chunk)
    # trailing chunk with None content (EOS)
    delta_eos = MagicMock()
    delta_eos.content = None
    choice_eos = MagicMock()
    choice_eos.delta = delta_eos
    chunk_eos = MagicMock()
    chunk_eos.choices = [choice_eos]
    chunks.append(chunk_eos)
    return chunks


# ---------------------------------------------------------------------------
# Tests for complete()
# ---------------------------------------------------------------------------


class TestComplete:
    def test_returns_string_when_json_mode_false(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_response("안녕하세요")

        with patch("backend.app.llm.solar._client", mock_client):
            result = complete([{"role": "user", "content": "hello"}], json_mode=False)

        assert isinstance(result, str)
        assert result == "안녕하세요"

    def test_returns_dict_when_json_mode_true(self):
        payload = {"name": "홍길동", "score": 95}
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_response(json.dumps(payload))

        with patch("backend.app.llm.solar._client", mock_client):
            result = complete([{"role": "user", "content": "hello"}], json_mode=True)

        assert isinstance(result, dict)
        assert result == payload

    def test_json_mode_passes_response_format(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_response('{"ok": true}')

        with patch("backend.app.llm.solar._client", mock_client):
            complete([{"role": "user", "content": "hi"}], json_mode=True)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("response_format") == {"type": "json_object"}

    def test_retries_on_5xx_status_error(self):
        """Raises APIStatusError twice, then succeeds on third attempt."""
        mock_client = MagicMock()

        status_error = openai.APIStatusError(
            message="Internal Server Error",
            response=MagicMock(status_code=500),
            body=None,
        )
        mock_client.chat.completions.create.side_effect = [
            status_error,
            status_error,
            _make_response("recovered"),
        ]

        with (
            patch("backend.app.llm.solar._client", mock_client),
            patch("backend.app.llm.solar._sleep"),
        ):  # skip real sleeps
            result = complete([{"role": "user", "content": "hi"}])

        assert result == "recovered"
        assert mock_client.chat.completions.create.call_count == 3

    def test_retries_on_timeout(self):
        """Raises APITimeoutError once, then succeeds."""
        mock_client = MagicMock()
        timeout_error = openai.APITimeoutError(request=MagicMock())
        mock_client.chat.completions.create.side_effect = [
            timeout_error,
            _make_response("ok"),
        ]

        with (
            patch("backend.app.llm.solar._client", mock_client),
            patch("backend.app.llm.solar._sleep"),
        ):
            result = complete([{"role": "user", "content": "hi"}])

        assert result == "ok"
        assert mock_client.chat.completions.create.call_count == 2

    def test_raises_after_three_consecutive_failures(self):
        """All 3 attempts raise; the last exception must propagate."""
        mock_client = MagicMock()
        status_error = openai.APIStatusError(
            message="Service Unavailable",
            response=MagicMock(status_code=503),
            body=None,
        )
        mock_client.chat.completions.create.side_effect = [
            status_error,
            status_error,
            status_error,
        ]

        with (
            patch("backend.app.llm.solar._client", mock_client),
            patch("backend.app.llm.solar._sleep"),
            pytest.raises(openai.APIStatusError),
        ):
            complete([{"role": "user", "content": "hi"}])

        assert mock_client.chat.completions.create.call_count == 3

    def test_4xx_raises_immediately_without_retry(self):
        """4xx errors must propagate immediately — they are not retryable."""
        mock_client = MagicMock()
        bad_request = openai.APIStatusError(
            message="Bad Request",
            response=MagicMock(status_code=400),
            body=None,
        )
        mock_client.chat.completions.create.side_effect = bad_request

        with (
            patch("backend.app.llm.solar._client", mock_client),
            patch("backend.app.llm.solar._sleep") as mock_sleep,
            pytest.raises(openai.APIStatusError),
        ):
            complete([{"role": "user", "content": "hi"}])

        assert mock_client.chat.completions.create.call_count == 1
        mock_sleep.assert_not_called()

    def test_base_url_matches_settings(self):
        """The client stored in _client must have been created with settings.SOLAR_BASE_URL."""
        from backend.app.llm import solar

        # The module-level _client is an openai.OpenAI instance (or mock).
        # In real code we only verify the kwarg; here we check the settings value is sane.
        assert settings.solar_base_url  # non-empty
        # The solar module's _BASE_URL constant (if any) or settings must agree.
        assert solar._BASE_URL == settings.solar_base_url


# ---------------------------------------------------------------------------
# Tests for stream()
# ---------------------------------------------------------------------------


class TestStream:
    def test_yields_text_chunks(self):
        mock_client = MagicMock()
        chunks = _make_stream_chunks(["Hello", ", ", "world"])
        mock_client.chat.completions.create.return_value = iter(chunks)

        with patch("backend.app.llm.solar._client", mock_client):
            result = list(stream([{"role": "user", "content": "hi"}]))

        assert result == ["Hello", ", ", "world"]

    def test_stream_passes_stream_true(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = iter(_make_stream_chunks(["x"]))

        with patch("backend.app.llm.solar._client", mock_client):
            list(stream([{"role": "user", "content": "hi"}]))

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("stream") is True
