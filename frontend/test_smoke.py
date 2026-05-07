"""Smoke test — Streamlit app loads and renders core widgets without error."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_app_loads_without_exception(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "http://localhost-test")
    at = AppTest.from_file("frontend/streamlit_app.py", default_timeout=10)
    at.run()
    assert not at.exception, f"App raised: {at.exception}"


def test_app_renders_title_and_session_button(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "http://localhost-test")
    at = AppTest.from_file("frontend/streamlit_app.py", default_timeout=10)
    at.run()
    titles = [t.value for t in at.title]
    assert any("HwpAgent" in t for t in titles), f"title not found: {titles}"
    button_labels = [b.label for b in at.sidebar.button]
    assert any("새 세션" in lbl for lbl in button_labels), button_labels


def test_chat_input_present(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "http://localhost-test")
    at = AppTest.from_file("frontend/streamlit_app.py", default_timeout=10)
    at.run()
    assert at.chat_input, "chat input widget not rendered"


def test_chat_input_warns_without_session(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "http://localhost-test")
    at = AppTest.from_file("frontend/streamlit_app.py", default_timeout=10)
    at.run()
    at.chat_input[0].set_value("안녕하세요").run()
    warnings = [w.value for w in at.warning]
    assert any("새 세션" in w for w in warnings), warnings
