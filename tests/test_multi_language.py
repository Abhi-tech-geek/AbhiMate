"""Locale fast-path tests for MultiLanguageAgent."""

from unittest.mock import patch

import pytest


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with patch("agents.multi_language_agent.Groq"):
        from agents.multi_language_agent import MultiLanguageAgent
        return MultiLanguageAgent()


def test_ascii_english_skips_llm(agent):
    with patch.object(agent.client.chat.completions, "create") as create:
        out = agent.adapt_prompt_for_locale("Test the login page", "en-US")
    assert out == "Test the login page"
    create.assert_not_called()


def test_non_ascii_input_calls_llm(agent):
    fake_resp = type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "Login test"})()})()]})()
    with patch.object(agent.client.chat.completions, "create", return_value=fake_resp) as create:
        out = agent.adapt_prompt_for_locale("लॉगिन टेस्ट करो", "en-US")
    create.assert_called_once()
    assert out == "Login test"


def test_non_english_locale_always_translates(agent):
    fake_resp = type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "Translated"})()})()]})()
    with patch.object(agent.client.chat.completions, "create", return_value=fake_resp) as create:
        out = agent.adapt_prompt_for_locale("Hello", "fr-FR")
    create.assert_called_once()
    assert out == "Translated"
