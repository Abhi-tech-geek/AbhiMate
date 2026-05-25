"""Shared pytest fixtures for AbhiMate test suite.

Adds the project root to sys.path so ``import agents.x`` works when pytest is
invoked from inside ``tests/``.

Phase C: auth gates most routes, so test client fixtures sign up + log in a
throwaway user automatically. Tests that need anonymous access pull
``anonymous_client`` instead.
"""

import os
import sys
import uuid
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def tmp_db_path(tmp_path):
    """SQLite path inside a per-test temp dir."""
    return str(tmp_path / "abhimate_test.db")


@pytest.fixture
def sample_test_case_dict():
    return {
        "id": "TC001",
        "type": "Positive",
        "description": "Sample positive case",
        "steps": ["Open page", "Click button"],
        "selenium_action": "print('hello')",
        "expected": "Page opens",
    }


@pytest.fixture
def app_module(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-dummy")
    import app as _app
    return _app


@pytest.fixture
def anonymous_client(app_module):
    """Flask test client with no logged-in user."""
    return app_module.app.test_client()


@pytest.fixture
def auth_client(app_module):
    """Test client pre-authenticated as a fresh throwaway user.

    Yields (client, user_id). The user is created directly via the DB to keep
    the fixture cheap and predictable.
    """
    email = f"tester-{uuid.uuid4().hex[:8]}@example.com"
    user_id = app_module.memory_agent.db.create_user(
        email=email,
        password_hash=app_module.hash_password("ValidPass123!"),
        display_name="Test User",
    )
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
    yield client, user_id


@pytest.fixture
def authed_html(auth_client):
    """Convenience: the rendered HTML of `/` as an authenticated user."""
    client, _ = auth_client
    return client.get("/").data.decode("utf-8")
