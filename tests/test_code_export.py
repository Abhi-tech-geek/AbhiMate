"""Feature #1 — export Action Plans as runnable test code.

Two layers:
1. code_export pure generator (per-framework translation + filenames)
2. Flask endpoint (auth, framework param, content-disposition, user scope)
"""

from __future__ import annotations

import time
import uuid

import pytest

from utils.models import Action, Locator, TestCase, TestSession


def _sample_session(user_id=1):
    tc = TestCase(
        id="TC001",
        type="Positive",
        description="Login with valid credentials",
        steps=["go", "fill", "click", "assert"],
        scenario="Successful login",
        expected="Dashboard visible",
        action_plan=[
            Action(op="goto", url="https://app.example.com/login"),
            Action(op="fill",
                   locator=Locator(by="id", value="email"),
                   value="user@example.com"),
            Action(op="click", locator=Locator(by="text", value="Sign in")),
            Action(op="assert_visible", locator=Locator(by="id", value="dashboard")),
        ],
    )
    return TestSession(
        session_id=f"sess-{uuid.uuid4().hex[:8]}",
        user_id=user_id, feature="Login flow",
        state="GENERATED", timestamp=time.time(), test_cases=[tc],
    )


# ======================================================================
# 1. Pure generator
# ======================================================================

def test_playwright_output_has_key_lines():
    from utils.code_export import generate_code
    code = generate_code(_sample_session(), "playwright")
    assert "from playwright.sync_api import" in code
    assert "page.goto('https://app.example.com/login')" in code
    assert "page.locator('#email').fill('user@example.com')" in code
    assert "page.get_by_text('Sign in').click()" in code
    assert "expect(page.locator('#dashboard')).to_be_visible()" in code
    assert "def test_tc001_" in code


def test_selenium_output_has_key_lines():
    from utils.code_export import generate_code
    code = generate_code(_sample_session(), "selenium")
    assert "from selenium import webdriver" in code
    assert "driver.get('https://app.example.com/login')" in code
    assert "By.ID, 'email'" in code
    assert "@pytest.fixture" in code
    assert "def driver():" in code


def test_cypress_output_has_key_lines():
    from utils.code_export import generate_code
    code = generate_code(_sample_session(), "cypress")
    assert "describe(" in code
    assert "cy.visit('https://app.example.com/login')" in code
    assert "cy.get('#email').clear().type('user@example.com');" in code
    assert "cy.contains('Sign in').click();" in code
    assert "should('be.visible')" in code


def test_unsupported_op_becomes_comment():
    from utils.code_export import generate_code
    s = _sample_session()
    s.test_cases[0].action_plan.append(Action(op="assert_a11y", expected="AA"))
    code = generate_code(s, "playwright")
    assert "TODO" in code and "assert_a11y" in code


def test_unknown_framework_raises():
    from utils.code_export import generate_code
    with pytest.raises(ValueError, match="Unknown framework"):
        generate_code(_sample_session(), "robot")


def test_empty_action_plan_is_safe():
    from utils.code_export import generate_code
    s = _sample_session()
    s.test_cases[0].action_plan = []
    code = generate_code(s, "playwright")
    assert "no action plan" in code


def test_value_with_quotes_is_escaped():
    from utils.code_export import generate_code
    s = _sample_session()
    s.test_cases[0].action_plan = [
        Action(op="fill", locator=Locator(by="id", value="q"), value="O'Brien"),
    ]
    code = generate_code(s, "playwright")
    # Single quote escaped, so the file stays valid Python.
    assert "O\\'Brien" in code


def test_filename_extensions():
    from utils.code_export import filename_for
    s = _sample_session()
    assert filename_for(s, "playwright").endswith("_playwright.py")
    assert filename_for(s, "selenium").endswith("_selenium.py")
    assert filename_for(s, "cypress").endswith(".cy.js")


# ======================================================================
# 2. Flask endpoint
# ======================================================================

def test_endpoint_requires_auth(anonymous_client):
    r = anonymous_client.get("/api/sessions/whatever/export.code?framework=playwright")
    assert r.status_code == 401


def test_endpoint_exports_playwright(auth_client, app_module):
    client, uid = auth_client
    s = _sample_session(user_id=uid)
    app_module.memory_agent.save_session(s, user_id=uid)
    r = client.get(f"/api/sessions/{s.session_id}/export.code?framework=playwright")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "page.goto(" in body
    cd = r.headers.get("Content-Disposition", "")
    assert ".py" in cd and "attachment" in cd


def test_endpoint_defaults_to_playwright(auth_client, app_module):
    client, uid = auth_client
    s = _sample_session(user_id=uid)
    app_module.memory_agent.save_session(s, user_id=uid)
    r = client.get(f"/api/sessions/{s.session_id}/export.code")
    assert r.status_code == 200
    assert "playwright" in r.headers.get("Content-Disposition", "")


def test_endpoint_rejects_unknown_framework(auth_client, app_module):
    client, uid = auth_client
    s = _sample_session(user_id=uid)
    app_module.memory_agent.save_session(s, user_id=uid)
    r = client.get(f"/api/sessions/{s.session_id}/export.code?framework=robot")
    assert r.status_code == 400
    assert r.get_json()["code"] == "bad_framework"


def test_endpoint_is_user_scoped(auth_client, app_module):
    client_a, uid_a = auth_client
    s = _sample_session(user_id=uid_a)
    app_module.memory_agent.save_session(s, user_id=uid_a)

    other = app_module.memory_agent.db.create_user(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=app_module.hash_password("ValidPass123!"),
        display_name="Other",
    )
    client_b = app_module.app.test_client()
    with client_b.session_transaction() as sess:
        sess["user_id"] = int(other)
    r = client_b.get(f"/api/sessions/{s.session_id}/export.code?framework=cypress")
    assert r.status_code in (403, 404)
