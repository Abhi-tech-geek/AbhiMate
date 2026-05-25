"""Feature #6 — Screenshot → tests (vision LLM).

Three layers covered:
1. LLMNode.query_vision_json builds the right multimodal payload
2. TestCaseGeneratorAgent.generate_from_screenshot normalizes vision output
3. /api/smart_input_image endpoint — multipart + JSON shapes, auth, quota,
   size + mime validation, quota gate before token spend
"""

import base64
import json
import uuid
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


# Tiny valid PNG (1x1 transparent) — enough to flow through validation
_PNG_1X1 = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4"
    "890000000A49444154789C6300010000000500017A4E2F230000000049454E44AE426082"
)
_PNG_1X1_B64 = base64.b64encode(_PNG_1X1).decode("ascii")


def make_vision_response(num_cases: int = 2) -> dict:
    cases = []
    for i in range(num_cases):
        cases.append({
            "id": f"TC{i+1:03d}",
            "type": "Positive",
            "tags": ["@vision"],
            "scenario": f"Click visible button {i+1}",
            "description": f"Vision case {i+1}",
            "gherkin_steps": [
                {"keyword": "Given", "text": "the user is on the visible UI"},
                {"keyword": "When", "text": "the user clicks the primary button"},
                {"keyword": "Then", "text": "an expected outcome happens"},
            ],
            "action_plan": [
                {"op": "click", "locator": {"by": "text", "value": "Sign in"}},
                {"op": "assert_visible", "locator": {"by": "text", "value": "Dashboard"}},
            ],
            "expected": "Dashboard visible",
        })
    return {"test_cases": cases}


# ----------------------------------------------------------------------
# LLMNode.query_vision_json
# ----------------------------------------------------------------------

def _build_llm_with_canned_response(canned_response, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with patch("utils.llm_node.Groq") as GroqCls:
        client = MagicMock()
        msg = MagicMock(); msg.content = json.dumps(canned_response)
        choice = MagicMock(); choice.message = msg
        completion = MagicMock(); completion.choices = [choice]
        client.chat.completions.create = MagicMock(return_value=completion)
        GroqCls.return_value = client
        from utils.llm_node import LLMNode
        node = LLMNode()
    return node, client


def test_vision_call_uses_multimodal_message_shape(monkeypatch):
    node, client = _build_llm_with_canned_response(make_vision_response(1), monkeypatch)
    out = node.query_vision_json("sys", "user", _PNG_1X1_B64, mime_type="image/png")
    assert "test_cases" in out

    call = client.chat.completions.create.call_args
    msgs = call.kwargs["messages"]
    # Two messages: system + user
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    # User payload is a list of content parts: text + image_url
    parts = msgs[1]["content"]
    assert isinstance(parts, list)
    kinds = [p["type"] for p in parts]
    assert "text" in kinds and "image_url" in kinds
    img_part = next(p for p in parts if p["type"] == "image_url")
    assert img_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_vision_call_rejects_empty_image(monkeypatch):
    node, _ = _build_llm_with_canned_response(make_vision_response(), monkeypatch)
    with pytest.raises(ValueError, match="image_b64"):
        node.query_vision_json("sys", "user", image_b64="")


def test_vision_call_wraps_lists_into_items(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with patch("utils.llm_node.Groq") as GroqCls:
        client = MagicMock()
        msg = MagicMock(); msg.content = '[{"id": "1"}]'
        choice = MagicMock(); choice.message = msg
        completion = MagicMock(); completion.choices = [choice]
        client.chat.completions.create = MagicMock(return_value=completion)
        GroqCls.return_value = client
        from utils.llm_node import LLMNode
        out = LLMNode().query_vision_json("sys", "user", _PNG_1X1_B64)
    # Lists at top-level get wrapped so downstream .get() never crashes
    assert "items" in out


def test_vision_call_falls_back_on_model_404(monkeypatch):
    """First-choice vision model gets 404 -> try the fallback variant."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    from groq import APIError as _APIError
    fail = MagicMock(side_effect=_APIError(
        message="The model `llama-3.2-90b-vision-preview` does not exist",
        body={}, request=MagicMock(),
    ))
    succeed_msg = MagicMock(); succeed_msg.content = json.dumps(make_vision_response(1))
    succeed_choice = MagicMock(); succeed_choice.message = succeed_msg
    succeed_completion = MagicMock(); succeed_completion.choices = [succeed_choice]
    succeed = MagicMock(return_value=succeed_completion)

    call_count = {"n": 0}

    def side(**kwargs):
        call_count["n"] += 1
        if kwargs["model"] == "llama-3.2-90b-vision-preview":
            return fail(**kwargs)
        return succeed(**kwargs)

    with patch("utils.llm_node.Groq") as GroqCls:
        client = MagicMock()
        client.chat.completions.create = MagicMock(side_effect=side)
        GroqCls.return_value = client
        from utils.llm_node import LLMNode
        out = LLMNode().query_vision_json("sys", "user", _PNG_1X1_B64)
    assert "test_cases" in out
    assert call_count["n"] >= 2   # tried at least two models


# ----------------------------------------------------------------------
# Generator.generate_from_screenshot
# ----------------------------------------------------------------------

def test_generate_from_screenshot_yields_validated_cases(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    from utils.models import TestCase
    with patch("utils.llm_node.Groq"):
        from agents.test_case_generator_agent import TestCaseGeneratorAgent
        agent = TestCaseGeneratorAgent()
        with patch.object(agent.llm, "query_vision_json",
                          return_value=make_vision_response(3)):
            out = agent.generate_from_screenshot(_PNG_1X1_B64, count=3)
    assert len(out) == 3
    assert all(isinstance(c, TestCase) for c in out)
    assert out[0].action_plan[0].op == "click"


def test_generate_from_screenshot_clamps_count(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    captured = {}

    def capture(system, user, image_b64, mime_type, model=None):
        captured["prompt"] = user
        return make_vision_response(1)

    with patch("utils.llm_node.Groq"):
        from agents.test_case_generator_agent import TestCaseGeneratorAgent
        agent = TestCaseGeneratorAgent()
        with patch.object(agent.llm, "query_vision_json", side_effect=capture):
            agent.generate_from_screenshot(_PNG_1X1_B64, count=999)
    # 999 must be clamped to the upper bound (30). The screenshot path
    # inlines GHERKIN_RULES which renders "distribute the 30 cases...".
    assert "distribute the 30 cases" in captured["prompt"]
    assert "999" not in captured["prompt"]


def test_generate_from_screenshot_passes_hint_into_prompt(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    captured = {}

    def capture(system, user, image_b64, mime_type, model=None):
        captured["prompt"] = user
        return make_vision_response(1)

    with patch("utils.llm_node.Groq"):
        from agents.test_case_generator_agent import TestCaseGeneratorAgent
        agent = TestCaseGeneratorAgent()
        with patch.object(agent.llm, "query_vision_json", side_effect=capture):
            agent.generate_from_screenshot(
                _PNG_1X1_B64, count=2,
                hint="Focus on the payment form",
            )
    assert "Focus on the payment form" in captured["prompt"]


# ----------------------------------------------------------------------
# /api/smart_input_image endpoint
# ----------------------------------------------------------------------

def test_endpoint_requires_auth(anonymous_client):
    r = anonymous_client.post("/api/smart_input_image",
                              json={"image_b64": _PNG_1X1_B64})
    assert r.status_code == 401


def test_endpoint_rejects_missing_image(auth_client):
    client, _ = auth_client
    r = client.post("/api/smart_input_image", json={})
    assert r.status_code == 400


def test_endpoint_rejects_bad_base64(auth_client):
    client, _ = auth_client
    # Passing JSON requires us to bypass base64 validation guard — feed a
    # raw `image_b64` that decode() will tolerate but contains junk.
    r = client.post("/api/smart_input_image",
                    json={"image_b64": "###not-base64!@#"})
    assert r.status_code == 400


def test_endpoint_rejects_oversize_json(auth_client):
    client, _ = auth_client
    # 7 MB of junk base64 (decodes to ~5 MB → fine, so go bigger)
    huge = "A" * (9 * 1024 * 1024)
    r = client.post("/api/smart_input_image", json={"image_b64": huge})
    assert r.status_code == 413


def test_endpoint_quota_gate(auth_client, app_module):
    """When user is already at 5/5 sessions, the vision call is NOT made."""
    client, user_id = auth_client
    from utils.models import TestSession
    # Seed 5 sessions to hit quota
    for i in range(5):
        s = TestSession(
            session_id=f"q-{i}-{uuid.uuid4().hex[:6]}",
            user_id=user_id, feature=f"f{i}",
            state="GENERATED", timestamp=1.0, test_cases=[],
        )
        app_module.memory_agent.save_session(s, user_id=user_id)

    with patch.object(app_module.generator_agent, "generate_from_screenshot") as gen:
        r = client.post("/api/smart_input_image",
                        json={"image_b64": _PNG_1X1_B64})
    assert r.status_code == 409
    gen.assert_not_called()    # never burned a vision token


def test_endpoint_multipart_happy_path(auth_client, app_module, monkeypatch):
    client, user_id = auth_client

    with patch.object(app_module.generator_agent.llm, "query_vision_json",
                      return_value=make_vision_response(2)):
        r = client.post(
            "/api/smart_input_image",
            data={
                "image": (BytesIO(_PNG_1X1), "shot.png", "image/png"),
                "count": "2",
                "hint": "Login form",
            },
            content_type="multipart/form-data",
        )
    assert r.status_code == 200
    body = r.get_json()
    assert body["from_screenshot"] is True
    assert body["session"]["feature"].startswith("From screenshot")
    assert len(body["session"]["test_cases"]) == 2


def test_endpoint_multipart_rejects_unsupported_mime(auth_client):
    client, _ = auth_client
    r = client.post(
        "/api/smart_input_image",
        data={"image": (BytesIO(b"GIF89a fakegif"), "shot.gif", "image/gif")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 415


def test_endpoint_json_happy_path(auth_client, app_module):
    client, _ = auth_client
    with patch.object(app_module.generator_agent.llm, "query_vision_json",
                      return_value=make_vision_response(3)):
        r = client.post("/api/smart_input_image", json={
            "image_b64": _PNG_1X1_B64, "count": 3, "hint": "Some screen",
        })
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["session"]["test_cases"]) == 3


def test_endpoint_strips_data_uri_prefix(auth_client, app_module):
    """Front-end FileReader.readAsDataURL gives 'data:image/png;base64,...'.
    The endpoint should accept that form too."""
    client, _ = auth_client
    full = f"data:image/png;base64,{_PNG_1X1_B64}"
    with patch.object(app_module.generator_agent.llm, "query_vision_json",
                      return_value=make_vision_response(1)):
        r = client.post("/api/smart_input_image",
                        json={"image_b64": full, "count": 1})
    assert r.status_code == 200


def test_endpoint_502_when_no_cases_returned(auth_client, app_module):
    """If the vision model returns zero usable cases, surface a 502."""
    client, _ = auth_client
    with patch.object(app_module.generator_agent.llm, "query_vision_json",
                      return_value={"test_cases": []}):
        r = client.post("/api/smart_input_image",
                        json={"image_b64": _PNG_1X1_B64})
    assert r.status_code == 502


def test_endpoint_llm_config_error_returns_friendly_payload(auth_client, app_module):
    """When Groq vision model is misconfigured we route through the global
    LLMConfigError handler that ships a banner-ready payload."""
    from utils.llm_node import LLMConfigError
    client, _ = auth_client
    with patch.object(app_module.generator_agent.llm, "query_vision_json",
                      side_effect=LLMConfigError("Groq vision unavailable",
                                                  hint="Try a different model",
                                                  http_status=502)):
        r = client.post("/api/smart_input_image",
                        json={"image_b64": _PNG_1X1_B64})
    assert r.status_code == 502
    body = r.get_json()
    assert body["code"] == "llm_unavailable"
    assert body["hint"] == "Try a different model"
