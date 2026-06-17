"""Live demo mode — read-only guest account pre-seeded with sample sessions."""

from __future__ import annotations

import pytest


# ======================================================================
# 1. Seed builder
# ======================================================================

def test_build_demo_sessions_are_valid():
    from utils.demo_seed import build_demo_sessions
    sessions = build_demo_sessions(99)
    assert len(sessions) == 2
    for s in sessions:
        assert s.user_id == 99
        assert s.state == "EXECUTED"
        assert s.test_cases and s.report is not None
        # Every case has an action plan and a status (showcase-ready).
        for tc in s.test_cases:
            assert tc.action_plan
            assert tc.status in {"Pass", "Fail", "Flaky", "Skipped"}


def test_ensure_demo_is_idempotent(app_module):
    from utils.demo_seed import ensure_demo, DEMO_EMAIL
    uid1 = ensure_demo(app_module.memory_agent, app_module.hash_password)
    uid2 = ensure_demo(app_module.memory_agent, app_module.hash_password)
    assert uid1 == uid2
    # Reseed keeps exactly the sample sessions (no duplication/growth).
    rows = app_module.memory_agent.db.list_sessions(user_id=uid1)
    assert len(rows) == 2
    u = app_module.memory_agent.db.get_user_by_email(DEMO_EMAIL)
    assert u is not None


# ======================================================================
# 2. Endpoint + login
# ======================================================================

def test_demo_login_works_anonymously(anonymous_client):
    r = anonymous_client.post("/api/auth/demo")
    assert r.status_code == 200
    assert r.get_json().get("demo") is True


def test_demo_sessions_are_visible_after_login(anonymous_client):
    anonymous_client.post("/api/auth/demo")
    r = anonymous_client.get("/api/sessions")
    assert r.status_code == 200
    body = r.get_json()
    features = {s["feature"] for s in body["sessions"]}
    assert any("Login flow" in f for f in features)
    assert any("Checkout flow" in f for f in features)


# ======================================================================
# 3. Read-only guard
# ======================================================================

def test_demo_cannot_generate(anonymous_client):
    anonymous_client.post("/api/auth/demo")
    r = anonymous_client.post("/api/smart_input", json={"prompt": "login flow"})
    assert r.status_code == 403
    assert r.get_json()["code"] == "demo_readonly"


def test_demo_cannot_delete(anonymous_client):
    anonymous_client.post("/api/auth/demo")
    r = anonymous_client.delete("/api/sessions/demo-login-flow")
    assert r.status_code == 403
    assert r.get_json()["code"] == "demo_readonly"


def test_demo_cannot_execute_stream(anonymous_client):
    anonymous_client.post("/api/auth/demo")
    r = anonymous_client.post("/api/execute_stream/demo-login-flow", json={})
    assert r.status_code == 403


def test_demo_can_still_export_code(anonymous_client):
    """Export is read-only — it must stay open so the demo can showcase it."""
    anonymous_client.post("/api/auth/demo")
    r = anonymous_client.get("/api/sessions/demo-login-flow/export.code?framework=playwright")
    assert r.status_code == 200
    assert "page.goto(" in r.get_data(as_text=True)


def test_demo_can_view_markdown_export(anonymous_client):
    anonymous_client.post("/api/auth/demo")
    r = anonymous_client.get("/api/sessions/demo-login-flow/export.md")
    assert r.status_code == 200


def test_regular_user_is_not_blocked(auth_client):
    """The demo guard must only affect the demo account."""
    client, _ = auth_client
    # A non-demo user hitting generate should NOT get the demo 403 (it may
    # fail later for other reasons, but never with demo_readonly).
    r = client.post("/api/smart_input", json={"prompt": ""})
    body = r.get_json() or {}
    assert body.get("code") != "demo_readonly"
