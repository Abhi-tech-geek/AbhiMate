"""Feature #11 — JIRA / Linear ticket creator.

Three layers covered:
1. SQLite credentials CRUD (set / get / list-with-mask / delete)
2. Provider adapters (Jira REST + Linear GraphQL) with mocked HTTP
3. Body composer for a known failed-case fixture
4. End-to-end via Flask test client (auth + cross-user 403)
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from database.db_core import SQLiteDB
from utils.ticket_body import compose_title, compose_body, compose_all
from utils.ticket_providers import (
    JiraProvider, LinearProvider, TicketProviderError, build_provider,
    _markdown_to_adf,
)


# ---------------------------------------------------------------------
# DB credentials CRUD
# ---------------------------------------------------------------------

def fresh_db(tmp_path):
    return SQLiteDB(db_path=str(tmp_path / "tc.db"))


def test_set_then_get_credentials_round_trip(tmp_path):
    db = fresh_db(tmp_path)
    db.set_ticket_credentials(
        user_id=1, provider="jira",
        base_url="https://x.atlassian.net",
        auth_email="me@x.com",
        auth_token="tok-1234",
        default_project="QA",
    )
    got = db.get_ticket_credentials(1, "jira")
    assert got["base_url"] == "https://x.atlassian.net"
    assert got["auth_email"] == "me@x.com"
    assert got["auth_token"] == "tok-1234"
    assert got["default_project"] == "QA"


def test_upsert_replaces_fields(tmp_path):
    db = fresh_db(tmp_path)
    db.set_ticket_credentials(1, "jira", auth_token="first")
    db.set_ticket_credentials(1, "jira", auth_token="second", default_project="P2")
    got = db.get_ticket_credentials(1, "jira")
    assert got["auth_token"] == "second"
    assert got["default_project"] == "P2"


def test_list_masks_token(tmp_path):
    db = fresh_db(tmp_path)
    db.set_ticket_credentials(1, "jira", auth_email="a@x.com",
                              auth_token="abcd-efgh-ijkl-1234")
    db.set_ticket_credentials(1, "linear", auth_token="lin_qwe123rty456")
    rows = db.list_ticket_credentials(1)
    assert len(rows) == 2
    for r in rows:
        # The raw token must NEVER come back from the listing endpoint.
        assert "auth_token" not in r
        assert r["token_mask"]


def test_list_is_user_scoped(tmp_path):
    db = fresh_db(tmp_path)
    # Use tokens whose first-4/last-4 differ so the masks are distinguishable.
    db.set_ticket_credentials(1, "jira", auth_email="a@x.com", auth_token="aaaa1234abcd")
    db.set_ticket_credentials(2, "jira", auth_email="b@x.com", auth_token="zzzz5678wxyz")
    a = db.list_ticket_credentials(1)
    b = db.list_ticket_credentials(2)
    assert len(a) == 1 and len(b) == 1
    assert a[0]["auth_email"] == "a@x.com"
    assert b[0]["auth_email"] == "b@x.com"
    assert a[0]["token_mask"] != b[0]["token_mask"]


def test_delete_removes_one_provider(tmp_path):
    db = fresh_db(tmp_path)
    db.set_ticket_credentials(1, "jira", auth_token="j")
    db.set_ticket_credentials(1, "linear", auth_token="l")
    assert db.delete_ticket_credentials(1, "jira") is True
    assert db.get_ticket_credentials(1, "jira") is None
    assert db.get_ticket_credentials(1, "linear") is not None


def test_unknown_provider_rejected(tmp_path):
    db = fresh_db(tmp_path)
    with pytest.raises(ValueError):
        db.set_ticket_credentials(1, "github", auth_token="x")


# ---------------------------------------------------------------------
# JiraProvider — mocked HTTP
# ---------------------------------------------------------------------

def _mock_response(status_code, json_body=None, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text or json.dumps(json_body or {})
    r.json = MagicMock(return_value=json_body or {})
    return r


def test_jira_create_issue_happy_path():
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(
        201, {"id": "10001", "key": "QA-42", "self": "https://x.atlassian.net/rest/.../10001"}
    ))
    j = JiraProvider("https://x.atlassian.net", "me@x.com", "tok", session=session)
    out = j.create_issue("Title", "Body **md**", project_or_team="QA")
    assert out["provider"] == "jira"
    assert out["key"] == "QA-42"
    assert out["url"] == "https://x.atlassian.net/browse/QA-42"
    # Verify auth + payload shape
    args = session.post.call_args
    assert "Authorization" in args.kwargs["headers"]
    assert args.kwargs["headers"]["Authorization"].startswith("Basic ")
    body = json.loads(args.kwargs["data"])
    assert body["fields"]["project"]["key"] == "QA"
    assert body["fields"]["summary"] == "Title"
    assert body["fields"]["issuetype"]["name"] == "Bug"
    # ADF content was generated
    assert body["fields"]["description"]["type"] == "doc"


def test_jira_requires_project_key():
    session = MagicMock()
    j = JiraProvider("https://x.atlassian.net", "me@x.com", "tok", session=session)
    with pytest.raises(TicketProviderError):
        j.create_issue("T", "B")


def test_jira_propagates_4xx_with_body():
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(
        401, {"errorMessages": ["bad creds"]},
        text='{"errorMessages":["bad creds"]}'))
    j = JiraProvider("https://x.atlassian.net", "me@x.com", "tok",
                     default_project="QA", session=session)
    with pytest.raises(TicketProviderError) as exc:
        j.create_issue("T", "B")
    assert exc.value.status == 401
    assert "bad creds" in exc.value.body


def test_jira_missing_creds_raises_at_construction():
    with pytest.raises(TicketProviderError):
        JiraProvider("", "me@x.com", "tok")


def test_markdown_to_adf_simple_paragraphs():
    out = _markdown_to_adf("first paragraph\n\nsecond one")
    assert out["type"] == "doc"
    assert len(out["content"]) == 2
    assert out["content"][0]["type"] == "paragraph"
    assert out["content"][0]["content"][0]["text"] == "first paragraph"


def test_markdown_to_adf_code_fence():
    out = _markdown_to_adf("intro\n\n```python\nx = 1\n```\n\nafter")
    types = [c["type"] for c in out["content"]]
    assert "codeBlock" in types
    code_node = next(c for c in out["content"] if c["type"] == "codeBlock")
    assert code_node["attrs"]["language"] == "python"


def test_markdown_to_adf_empty_input_gives_blank_doc():
    out = _markdown_to_adf("")
    assert out["type"] == "doc"
    assert len(out["content"]) >= 1


# ---------------------------------------------------------------------
# LinearProvider — mocked GraphQL
# ---------------------------------------------------------------------

def test_linear_create_issue_happy_path():
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(200, {
        "data": {"issueCreate": {"success": True, "issue": {
            "id": "iss-uuid", "identifier": "ENG-99",
            "url": "https://linear.app/x/issue/ENG-99",
            "title": "Title",
        }}}
    }))
    l = LinearProvider(auth_token="lin_tok", default_project="team-uuid",
                       session=session)
    out = l.create_issue("Title", "Body in **markdown**")
    assert out["key"] == "ENG-99"
    assert out["url"].endswith("/ENG-99")
    args = session.post.call_args
    # Auth header — Linear uses bare token, not 'Bearer ...'
    assert args.kwargs["headers"]["Authorization"] == "lin_tok"
    body = json.loads(args.kwargs["data"])
    assert "issueCreate" in body["query"]
    assert body["variables"]["teamId"] == "team-uuid"


def test_linear_graphql_errors_propagate():
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(200, {
        "errors": [{"message": "team not found"}]
    }))
    l = LinearProvider("tok", default_project="team", session=session)
    with pytest.raises(TicketProviderError) as exc:
        l.create_issue("T", "B")
    assert "GraphQL" in exc.value.message


def test_linear_success_false():
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(200, {
        "data": {"issueCreate": {"success": False, "issue": None}}
    }))
    l = LinearProvider("tok", default_project="team", session=session)
    with pytest.raises(TicketProviderError, match="refused"):
        l.create_issue("T", "B")


def test_linear_requires_team_id():
    session = MagicMock()
    l = LinearProvider("tok", session=session)  # no default team
    with pytest.raises(TicketProviderError):
        l.create_issue("T", "B")


def test_linear_missing_token():
    with pytest.raises(TicketProviderError):
        LinearProvider(auth_token="")


# ---------------------------------------------------------------------
# build_provider factory
# ---------------------------------------------------------------------

def test_build_provider_returns_jira():
    p = build_provider({
        "provider": "jira", "base_url": "https://x.atlassian.net",
        "auth_email": "me@x.com", "auth_token": "tok", "default_project": "QA",
    })
    assert p.__class__.__name__ == "JiraProvider"


def test_build_provider_returns_linear():
    p = build_provider({
        "provider": "linear", "auth_token": "tok", "default_project": "team-uuid",
    })
    assert p.__class__.__name__ == "LinearProvider"


def test_build_provider_rejects_unknown():
    with pytest.raises(TicketProviderError):
        build_provider({"provider": "github"})


def test_build_provider_rejects_empty():
    with pytest.raises(TicketProviderError):
        build_provider(None)


# ---------------------------------------------------------------------
# Body composer
# ---------------------------------------------------------------------

FAILING_CASE = {
    "id": "TC003",
    "type": "Positive",
    "description": "Login with valid credentials",
    "expected": "Dashboard loads",
    "status": "Fail",
    "error": "TimeoutException: button[type=submit] not found",
    "bug_insight": "Likely a selector mismatch after UI refresh.",
    "action_plan": [
        {"op": "goto", "url": "https://app.example.com/login"},
        {"op": "fill", "locator": {"by": "id", "value": "email"}, "value": "u@x.com"},
        {"op": "click", "locator": {"by": "css", "value": "button[type=submit]"}},
    ],
    "action_results": [
        {"op": "goto",  "success": True,  "duration_ms": 320, "attempts": 1},
        {"op": "click", "success": False, "duration_ms": 10000, "attempts": 1,
         "error": "TimeoutException"},
    ],
    "screenshot": "data/screenshots/abc/failure_TC003.png",
}

SAMPLE_SESSION = {
    "session_id": "abc-123",
    "feature": "Login feature",
}


def test_compose_title_default():
    t = compose_title(FAILING_CASE, SAMPLE_SESSION)
    assert "TC003" in t
    assert "Login feature" in t
    assert "Login with valid credentials" in t


def test_compose_title_override_wins():
    t = compose_title(FAILING_CASE, SAMPLE_SESSION, override="Custom title")
    assert t == "Custom title"


def test_compose_body_includes_all_signals():
    body = compose_body(FAILING_CASE, SAMPLE_SESSION)
    assert "TimeoutException" in body
    assert "Likely a selector mismatch" in body          # bug_insight
    assert "## Test failure" in body                      # heading
    assert "### Error" in body
    assert "### Per-op results" in body
    assert "data/screenshots/abc/failure_TC003.png" in body
    assert "### Action plan" in body                      # full plan included
    assert "Filed automatically by AbhiMate" in body      # footer


def test_compose_body_handles_minimal_case():
    minimal = {"id": "TC1", "status": "Fail"}
    body = compose_body(minimal, SAMPLE_SESSION)
    assert "TC1" in body
    assert "Filed automatically" in body


def test_compose_body_renders_deep_dive():
    body = compose_body(FAILING_CASE, SAMPLE_SESSION, deep_dive={
        "summary": "DD summary",
        "root_cause": "DD root cause",
        "why_now": "DD why now",
        "pattern": "DD pattern",
        "suggested_fix": "DD fix",
        "suggested_action_plan_patch": {"op": "click", "locator": {"by": "testid", "value": "submit"}},
        "confidence": "high",
    })
    assert "DD summary" in body
    assert "DD root cause" in body
    assert "Confidence: high" in body
    assert '"op": "click"' in body
    assert '"testid"' in body


def test_compose_all_returns_both():
    out = compose_all(FAILING_CASE, SAMPLE_SESSION)
    assert "title" in out and "body" in out
    assert "TC003" in out["title"]
    assert "## Test failure" in out["body"]


# ---------------------------------------------------------------------
# Endpoint: credentials management
# ---------------------------------------------------------------------

def test_credentials_endpoint_requires_auth(anonymous_client):
    assert anonymous_client.get("/api/tickets/credentials").status_code == 401
    assert anonymous_client.put("/api/tickets/credentials/jira",
                                json={"auth_token": "x"}).status_code == 401


def test_credentials_unknown_provider_400(auth_client):
    client, _ = auth_client
    r = client.put("/api/tickets/credentials/github", json={"auth_token": "x"})
    assert r.status_code == 400


def test_credentials_put_then_list_then_delete(auth_client, app_module):
    client, _ = auth_client
    r = client.put("/api/tickets/credentials/jira", json={
        "base_url": "https://x.atlassian.net",
        "auth_email": "me@x.com",
        "auth_token": "abcd-1234-efgh-5678",
        "default_project": "QA",
    })
    assert r.status_code == 200
    data = r.get_json()
    jira_row = next(p for p in data["providers"] if p["provider"] == "jira")
    assert jira_row["base_url"] == "https://x.atlassian.net"
    assert "token_mask" in jira_row
    # auth_token must never come back in the list endpoint
    assert "auth_token" not in jira_row

    # Delete
    r = client.delete("/api/tickets/credentials/jira")
    assert r.status_code == 200
    assert r.get_json()["deleted"] is True


# ---------------------------------------------------------------------
# Endpoint: create_ticket
# ---------------------------------------------------------------------

def test_create_ticket_requires_auth(anonymous_client):
    r = anonymous_client.post("/api/cases/x/y/create_ticket",
                              json={"provider": "jira"})
    assert r.status_code == 401


def test_create_ticket_400_when_provider_missing(auth_client):
    client, _ = auth_client
    r = client.post("/api/cases/x/y/create_ticket", json={})
    assert r.status_code == 400


def test_create_ticket_400_when_no_creds(auth_client):
    client, _ = auth_client
    r = client.post("/api/cases/x/y/create_ticket", json={"provider": "jira"})
    # No creds yet -> 400 with helpful pointer
    assert r.status_code == 400
    assert "Settings" in r.get_json()["error"]


def test_create_ticket_happy_path(auth_client, app_module, monkeypatch):
    client, user_id = auth_client
    from utils.models import TestSession, TestCase

    # Seed creds
    app_module.memory_agent.db.set_ticket_credentials(
        user_id, "jira",
        base_url="https://x.atlassian.net",
        auth_email="me@x.com",
        auth_token="tok",
        default_project="QA",
    )

    # Seed a failed session/case
    sid = "t-" + uuid.uuid4().hex[:6]
    sess = TestSession(
        session_id=sid, user_id=user_id, feature="Login feature",
        state="EXECUTED", timestamp=1.0,
        test_cases=[TestCase(
            id="TC1", type="Positive", description="login",
            steps=["s"], selenium_action="", expected="ok",
            status="Fail", error="boom",
        )],
    )
    app_module.memory_agent.save_session(sess, user_id=user_id)

    # Mock JiraProvider.create_issue so we don't hit the network
    fake_result = {"provider": "jira", "key": "QA-42", "id": "10001",
                   "url": "https://x.atlassian.net/browse/QA-42"}
    monkeypatch.setattr(
        "agents.deep_dive_agent.DeepDiveAgent.analyze",
        lambda self, c, ctx, model=None: {
            "summary": "x", "root_cause": "y", "why_now": "z", "pattern": "p",
            "suggested_fix": "f", "suggested_action_plan_patch": None,
            "confidence": "low",
        },
    )
    with patch("utils.ticket_providers.JiraProvider.create_issue",
               return_value=fake_result):
        r = client.post(f"/api/cases/{sid}/TC1/create_ticket", json={
            "provider": "jira", "include_deep_dive": True,
        })

    assert r.status_code == 200
    body = r.get_json()
    assert body["provider"] == "jira"
    assert body["key"] == "QA-42"
    assert body["url"].endswith("/QA-42")
    assert body["deep_dive_attached"] is True


def test_create_ticket_404_when_case_missing(auth_client, app_module):
    client, user_id = auth_client
    from utils.models import TestSession

    app_module.memory_agent.db.set_ticket_credentials(
        user_id, "jira",
        base_url="https://x.atlassian.net", auth_email="m@x.com",
        auth_token="tok", default_project="QA",
    )
    sid = "tk-" + uuid.uuid4().hex[:6]
    sess = TestSession(session_id=sid, user_id=user_id, feature="x",
                       state="EXECUTED", timestamp=1.0, test_cases=[])
    app_module.memory_agent.save_session(sess, user_id=user_id)

    r = client.post(f"/api/cases/{sid}/MISSING/create_ticket",
                    json={"provider": "jira"})
    assert r.status_code == 404


def test_create_ticket_cross_user_403(app_module):
    """User B can't file a ticket against User A's session."""
    from utils.models import TestSession, TestCase
    from utils.auth import hash_password

    db = app_module.memory_agent.db
    uid_a = db.create_user(f"a-{uuid.uuid4().hex[:6]}@x.com", hash_password("p"))
    uid_b = db.create_user(f"b-{uuid.uuid4().hex[:6]}@x.com", hash_password("p"))

    # B has creds but tries to ticket A's case
    db.set_ticket_credentials(uid_b, "jira",
                              base_url="https://x.atlassian.net",
                              auth_email="b@x.com", auth_token="tok",
                              default_project="QA")

    sid = "x-" + uuid.uuid4().hex[:6]
    sess = TestSession(session_id=sid, user_id=uid_a, feature="A's run",
                       state="EXECUTED", timestamp=1.0,
                       test_cases=[TestCase(id="TC1", type="Positive",
                                            description="x", steps=["s"],
                                            selenium_action="", expected="ok",
                                            status="Fail", error="boom")])
    db.save_session(sess.session_id, sess.feature, sess.state, sess.timestamp,
                    sess.model_dump(), user_id=uid_a)

    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = int(uid_b)

    r = client.post(f"/api/cases/{sid}/TC1/create_ticket",
                    json={"provider": "jira"})
    assert r.status_code == 403


def test_create_ticket_502_when_provider_errors(auth_client, app_module):
    client, user_id = auth_client
    from utils.models import TestSession, TestCase

    app_module.memory_agent.db.set_ticket_credentials(
        user_id, "jira",
        base_url="https://x.atlassian.net", auth_email="m@x.com",
        auth_token="tok", default_project="QA",
    )
    sid = "err-" + uuid.uuid4().hex[:6]
    sess = TestSession(
        session_id=sid, user_id=user_id, feature="x",
        state="EXECUTED", timestamp=1.0,
        test_cases=[TestCase(id="TC1", type="Positive", description="d",
                             steps=["s"], selenium_action="", expected="ok",
                             status="Fail", error="b")],
    )
    app_module.memory_agent.save_session(sess, user_id=user_id)

    with patch("utils.ticket_providers.JiraProvider.create_issue",
               side_effect=TicketProviderError("auth", status=401, body="x")):
        r = client.post(f"/api/cases/{sid}/TC1/create_ticket",
                        json={"provider": "jira", "include_deep_dive": False})
    assert r.status_code == 502
    assert "auth" in r.get_json()["error"]
