"""Feature #12 — DeepDiveAgent + /api/cases/<sid>/<cid>/deep_dive endpoint."""

import json
import os
import uuid
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------

def make_failing_case():
    return {
        "id": "TC003",
        "type": "Positive",
        "description": "Login with valid credentials",
        "expected": "Dashboard loads",
        "status": "Fail",
        "error": "TimeoutException: element 'button[type=submit]' not found",
        "bug_insight": "Likely a selector mismatch.",
        "action_plan": [
            {"op": "goto", "url": "https://app.example.com/login"},
            {"op": "fill", "locator": {"by": "id", "value": "email"}, "value": "u@x.com"},
            {"op": "click", "locator": {"by": "css", "value": "button[type=submit]"}},
        ],
        "action_results": [
            {"op": "goto",  "success": True,  "duration_ms": 320, "attempts": 1},
            {"op": "fill",  "success": True,  "duration_ms": 60,  "attempts": 1,
             "locator_used": "id=email"},
            {"op": "click", "success": False, "duration_ms": 10000, "attempts": 1,
             "error": "TimeoutException", "locator_used": None},
        ],
    }


def make_llm_response():
    return {
        "summary": "Submit button selector is stale.",
        "root_cause": "The CSS selector 'button[type=submit]' no longer matches "
                       "because the page now uses '<button data-testid=submit>'.",
        "why_now": "Recent UI refresh — devtools shows the button is now wrapped "
                    "in a <div role=form>.",
        "pattern": "First-time failure for this case.",
        "suggested_fix": "Add a testid fallback locator: "
                          "{by: 'testid', value: 'submit'} as primary.",
        "suggested_action_plan_patch": {
            "op": "click",
            "locator": {"by": "testid", "value": "submit",
                        "fallbacks": [{"by": "css", "value": "button[type=submit]"}]},
        },
        "confidence": "high",
    }


# ---------------------------------------------------------------------
# DeepDiveAgent unit tests
# ---------------------------------------------------------------------

def test_deep_dive_agent_normalizes_full_response(monkeypatch):
    with patch("utils.llm_node.Groq"):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        from agents.deep_dive_agent import DeepDiveAgent
        agent = DeepDiveAgent()
        with patch.object(agent.llm, "query_json", return_value=make_llm_response()):
            out = agent.analyze(make_failing_case(), context={
                "console_logs": [], "prior_runs": [], "locator_cache": [],
            })
    assert out["summary"].startswith("Submit button")
    assert out["confidence"] == "high"
    assert out["suggested_action_plan_patch"]["op"] == "click"


def test_deep_dive_agent_fills_missing_fields(monkeypatch):
    """LLM may drop fields — we fill them with empty defaults, not crash."""
    with patch("utils.llm_node.Groq"):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        from agents.deep_dive_agent import DeepDiveAgent
        agent = DeepDiveAgent()
        with patch.object(agent.llm, "query_json",
                          return_value={"summary": "only this"}):
            out = agent.analyze(make_failing_case(), context={})
    assert out["summary"] == "only this"
    assert out["root_cause"] == ""
    assert out["confidence"] == "low"
    assert out["suggested_action_plan_patch"] is None


def test_deep_dive_agent_clamps_bad_confidence(monkeypatch):
    with patch("utils.llm_node.Groq"):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        from agents.deep_dive_agent import DeepDiveAgent
        agent = DeepDiveAgent()
        with patch.object(agent.llm, "query_json",
                          return_value={"confidence": "VERY HIGH OMG"}):
            out = agent.analyze(make_failing_case(), context={})
    assert out["confidence"] == "low"   # unknown -> low


def test_deep_dive_agent_handles_llm_exception(monkeypatch):
    """Network error / bad key shouldn't crash the request — return a friendly stub."""
    with patch("utils.llm_node.Groq"):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        from agents.deep_dive_agent import DeepDiveAgent
        agent = DeepDiveAgent()
        with patch.object(agent.llm, "query_json",
                          side_effect=RuntimeError("Groq down")):
            out = agent.analyze(make_failing_case(), context={})
    assert "unavailable" in out["summary"].lower()
    assert out["confidence"] == "low"


def test_deep_dive_prompt_includes_action_summary(monkeypatch):
    """Verify the prompt fed to the LLM actually contains run signals."""
    captured = {}

    def capture(system, user, model=None):
        captured["system"] = system
        captured["user"] = user
        return make_llm_response()

    with patch("utils.llm_node.Groq"):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        from agents.deep_dive_agent import DeepDiveAgent
        agent = DeepDiveAgent()
        with patch.object(agent.llm, "query_json", side_effect=capture):
            agent.analyze(make_failing_case(), context={
                "console_logs": [
                    {"level": "SEVERE", "message": "Network 500 on /api/me"},
                ],
                "prior_runs": [
                    {"feature": "Login", "timestamp": 1700000000.0,
                     "error": "Same TimeoutException 3 days ago"},
                ],
                "locator_cache": [],
            })

    prompt = captured["user"]
    # The richer signals must end up in the prompt for the LLM to use them.
    assert "TC003" in prompt
    assert "TimeoutException" in prompt
    assert "Network 500" in prompt
    assert "3 days ago" in prompt
    # And the strict-JSON output schema is in the prompt.
    assert "suggested_action_plan_patch" in prompt


# ---------------------------------------------------------------------
# Context gatherer
# ---------------------------------------------------------------------

def test_gather_context_loads_console_logs_from_trace(tmp_path):
    from agents.deep_dive_agent import gather_deep_dive_context

    sid = "s-" + uuid.uuid4().hex[:6]
    case_id = "TC001"

    # Write a fake trace file at the path the agent will look.
    traces_dir = tmp_path / "data" / "traces" / sid
    traces_dir.mkdir(parents=True)
    (traces_dir / f"{case_id}.json").write_text(json.dumps({
        "id": case_id,
        "status": "Fail",
        "console_logs": [
            {"level": "SEVERE", "message": "Uncaught TypeError: x"},
            {"level": "INFO",   "message": "[react] hydrated"},
        ],
    }))

    class _DummySession:
        session_id = sid

    out = gather_deep_dive_context(
        _DummySession(), case_id, db=None,
        traces_dir=str(tmp_path / "data" / "traces"),
    )
    assert len(out["console_logs"]) == 2
    assert out["console_logs"][0]["message"] == "Uncaught TypeError: x"


def test_gather_context_missing_trace_is_silent(tmp_path):
    from agents.deep_dive_agent import gather_deep_dive_context
    class _DummySession:
        session_id = "missing-sid"
    out = gather_deep_dive_context(
        _DummySession(), "TC001", db=None,
        traces_dir=str(tmp_path / "data" / "traces"),
    )
    assert out["console_logs"] == []
    assert out["prior_runs"] == []
    assert out["locator_cache"] == []


def test_gather_context_pulls_locator_cache(tmp_path):
    from agents.deep_dive_agent import gather_deep_dive_context
    from database.db_core import SQLiteDB

    db = SQLiteDB(db_path=str(tmp_path / "ctx.db"))
    db.record_locator("example.com", "id", "email", "name", "email")
    db.record_locator("example.com", "id", "submit", "testid", "submit")

    class _S:
        session_id = "x"
    out = gather_deep_dive_context(_S(), "TC1", db=db,
                                   traces_dir=str(tmp_path / "no-traces"))
    assert len(out["locator_cache"]) == 2
    assert any(e["primary_value"] == "email" for e in out["locator_cache"])


def test_gather_context_finds_prior_failures(tmp_path):
    """When the same case_id failed in an earlier session, surface it."""
    from agents.deep_dive_agent import gather_deep_dive_context
    from database.db_core import SQLiteDB
    from utils.models import TestSession, TestCase

    db = SQLiteDB(db_path=str(tmp_path / "hist.db"))
    # Earlier session — same case_id failed
    prior = TestSession(
        session_id="prior-s",
        feature="Login feature",
        state="EXECUTED",
        timestamp=1700000000.0,
        test_cases=[TestCase(
            id="TC001", type="Positive", description="login",
            steps=["s"], selenium_action="", expected="ok",
            status="Fail", error="old TimeoutException",
        )],
    )
    db.save_session(prior.session_id, prior.feature, prior.state,
                    prior.timestamp, prior.model_dump())

    class _CurS:
        session_id = "cur-s"      # different from prior — that's the point
    out = gather_deep_dive_context(_CurS(), "TC001", db=db,
                                   traces_dir=str(tmp_path / "no-traces"))
    assert len(out["prior_runs"]) == 1
    assert out["prior_runs"][0]["session_id"] == "prior-s"
    assert "TimeoutException" in out["prior_runs"][0]["error"]


def test_gather_context_skips_current_session_in_history(tmp_path):
    """We don't want the active session counted as 'prior' history."""
    from agents.deep_dive_agent import gather_deep_dive_context
    from database.db_core import SQLiteDB
    from utils.models import TestSession, TestCase

    db = SQLiteDB(db_path=str(tmp_path / "h.db"))
    same = TestSession(
        session_id="same-s",
        feature="Login feature",
        state="EXECUTED",
        timestamp=1700000000.0,
        test_cases=[TestCase(
            id="TC001", type="Positive", description="login",
            steps=["s"], selenium_action="", expected="ok",
            status="Fail", error="self",
        )],
    )
    db.save_session(same.session_id, same.feature, same.state,
                    same.timestamp, same.model_dump())

    class _CurS:
        session_id = "same-s"   # SAME as the row in DB
    out = gather_deep_dive_context(_CurS(), "TC001", db=db,
                                   traces_dir=str(tmp_path / "no"))
    assert out["prior_runs"] == []


# ---------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------

def test_deep_dive_endpoint_auth_required(anonymous_client):
    r = anonymous_client.post("/api/cases/x/y/deep_dive")
    assert r.status_code == 401


def test_deep_dive_endpoint_404_when_session_missing(auth_client):
    client, _ = auth_client
    r = client.post("/api/cases/nope/TC1/deep_dive")
    assert r.status_code == 404


def test_deep_dive_endpoint_404_when_case_missing(auth_client, app_module):
    client, user_id = auth_client
    from utils.models import TestSession

    sid = "dd-" + uuid.uuid4().hex[:6]
    sess = TestSession(
        session_id=sid, user_id=user_id, feature="x",
        state="EXECUTED", timestamp=1.0, test_cases=[],
    )
    app_module.memory_agent.save_session(sess, user_id=user_id)

    r = client.post(f"/api/cases/{sid}/missing/deep_dive")
    assert r.status_code == 404


def test_deep_dive_endpoint_returns_structured_report(auth_client, app_module, monkeypatch):
    client, user_id = auth_client
    from utils.models import TestSession, TestCase

    sid = "dd-" + uuid.uuid4().hex[:6]
    sess = TestSession(
        session_id=sid, user_id=user_id, feature="Login feature",
        state="EXECUTED", timestamp=1.0,
        test_cases=[TestCase(
            id="TC1", type="Positive", description="x",
            steps=["s"], selenium_action="", expected="ok",
            status="Fail", error="boom",
        )],
    )
    app_module.memory_agent.save_session(sess, user_id=user_id)

    # Mock the deep-dive agent's LLM call so we don't hit the network.
    monkeypatch.setattr(
        app_module.deep_dive_agent.llm, "query_json",
        lambda system, user, model=None: make_llm_response(),
    )

    r = client.post(f"/api/cases/{sid}/TC1/deep_dive")
    assert r.status_code == 200
    body = r.get_json()
    assert body["case_id"] == "TC1"
    assert body["session_id"] == sid
    assert body["report"]["confidence"] == "high"
    assert body["report"]["summary"].startswith("Submit button")
    assert "context_used" in body


def test_deep_dive_endpoint_cross_user_is_forbidden(app_module):
    """User B cannot deep-dive User A's case."""
    from utils.models import TestSession, TestCase
    from utils.auth import hash_password

    db = app_module.memory_agent.db
    uid_a = db.create_user(f"a-{uuid.uuid4().hex[:6]}@x.com", hash_password("pwA"))
    uid_b = db.create_user(f"b-{uuid.uuid4().hex[:6]}@x.com", hash_password("pwB"))

    sid = "dd-x-" + uuid.uuid4().hex[:6]
    sess = TestSession(
        session_id=sid, user_id=uid_a, feature="A's feature",
        state="EXECUTED", timestamp=1.0,
        test_cases=[TestCase(
            id="TC1", type="Positive", description="x",
            steps=["s"], selenium_action="", expected="ok",
            status="Fail", error="boom",
        )],
    )
    app_module.memory_agent.save_session(sess, user_id=uid_a)

    # Sign in as user B
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = int(uid_b)

    r = client.post(f"/api/cases/{sid}/TC1/deep_dive")
    assert r.status_code == 403
