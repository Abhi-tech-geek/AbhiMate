"""Generator agent shape test — LLM is mocked, we verify validation + plumbing."""

from unittest.mock import patch

import pytest

from utils.models import TestCase


@pytest.fixture
def fake_llm_response():
    return {
        "test_cases": [
            {
                "id": "TC001",
                "type": "Positive",
                "tags": ["@smoke"],
                "scenario": "Valid login",
                "description": "Login with valid creds",
                "gherkin_steps": [
                    {"keyword": "Given", "text": "user on /login",
                     "code": "driver.get('https://x.com')"},
                    {"keyword": "Then", "text": "dashboard loads",
                     "code": "assert True"},
                ],
                "expected": "User reaches dashboard",
            },
            {
                "id": "TC002",
                "type": "Bogus",  # invalid -> should be dropped silently
                "description": "broken",
                "gherkin_steps": [],
                "expected": "n/a",
            },
        ]
    }


def test_generator_validates_and_drops_invalid(fake_llm_response, monkeypatch):
    # Avoid real Groq client init — patch the LLMNode used by the agent.
    with patch("utils.llm_node.Groq"):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        from agents.test_case_generator_agent import TestCaseGeneratorAgent

        agent = TestCaseGeneratorAgent()

        with patch.object(agent.llm, "query_json", return_value=fake_llm_response):
            out = agent.generate("Test feature")

    assert len(out) == 1
    assert isinstance(out[0], TestCase)
    assert out[0].id == "TC001"
    assert "driver.get" in out[0].selenium_action
    assert out[0].tags == ["@smoke"]


def test_generator_passes_model_through(fake_llm_response, monkeypatch):
    with patch("utils.llm_node.Groq"):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        from agents.test_case_generator_agent import TestCaseGeneratorAgent

        agent = TestCaseGeneratorAgent()
        with patch.object(agent.llm, "query_json", return_value=fake_llm_response) as q:
            agent.generate("X", model="llama-3.1-8b-instant", count=3)
            _, kwargs = q.call_args
            assert kwargs.get("model") == "llama-3.1-8b-instant"


def test_generator_clamps_count(fake_llm_response, monkeypatch):
    with patch("utils.llm_node.Groq"):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        from agents.test_case_generator_agent import TestCaseGeneratorAgent

        agent = TestCaseGeneratorAgent()
        with patch.object(agent.llm, "query_json", return_value=fake_llm_response) as q:
            agent.generate("X", count=999)  # Out-of-range
            user_prompt = q.call_args[0][1]
            # Clamps to 50 max.
            assert "exactly 50" in user_prompt
