"""Feature #2 — save_auth / load_auth round-trip.

We mock the port save_auth_state / load_auth_state methods so the test
doesn't actually need a browser. The handler is responsible for naming,
path-traversal defense, and dispatch.
"""

import json
import os

import pytest

from utils.action_engine import (
    execute_plan, ActionContext, known_ops,
    _auth_state_path, AUTH_STATES_DIR,
)
from utils.models import Action


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

class _StubAuthPort:
    """Minimum BrowserPort enough to exercise save_auth / load_auth."""

    def __init__(self):
        self.saved_to = None
        self.loaded_from = None
        self.driver = None

    # save: write a tiny known snapshot so we can re-read it
    def save_auth_state(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"engine": "stub", "cookies": [{"name": "sid", "value": "abc"}],
                       "local_storage": {"theme": "dark"}, "url": "https://x.com/home"}, f)
        self.saved_to = path

    def load_auth_state(self, path):
        with open(path, "r", encoding="utf-8") as f:
            self.loaded_payload = json.load(f)
        self.loaded_from = path


# ---------------------------------------------------------------------
# Registration + naming
# ---------------------------------------------------------------------

def test_auth_ops_registered():
    assert "save_auth" in known_ops()
    assert "load_auth" in known_ops()


@pytest.mark.parametrize("name,ok", [
    ("logged_in",         True),
    ("admin_session.v1",  True),
    ("user-2024",         True),
    ("CamelCase",         True),
    ("",                  False),
    ("../escape",         False),
    ("with space",        False),
    ("../../etc/passwd",  False),
    ("name;rm",           False),
    ("name\nnewline",     False),
])
def test_auth_state_path_validation(name, ok, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    if ok:
        path = _auth_state_path(name)
        assert path.startswith(os.path.abspath(AUTH_STATES_DIR))
        assert path.endswith(".json")
    else:
        with pytest.raises(ValueError):
            _auth_state_path(name)


def test_auth_state_path_adds_json_extension(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = _auth_state_path("my_session")
    assert p.endswith("my_session.json")


def test_auth_state_path_keeps_explicit_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = _auth_state_path("my_session.json")
    assert p.endswith("my_session.json")
    # Not double-appended:
    assert not p.endswith(".json.json")


# ---------------------------------------------------------------------
# save_auth + load_auth via fake port
# ---------------------------------------------------------------------

def test_save_auth_writes_via_port(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    port = _StubAuthPort()
    ctx = ActionContext(port=port)
    execute_plan([Action(op="save_auth", value="my_login")], ctx, retries=1)
    assert port.saved_to is not None
    assert os.path.isfile(port.saved_to)
    on_disk = json.load(open(port.saved_to))
    assert on_disk["cookies"][0]["name"] == "sid"


def test_save_auth_then_load_auth_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    port = _StubAuthPort()
    ctx = ActionContext(port=port)
    execute_plan([
        Action(op="save_auth", value="round_trip"),
        Action(op="load_auth", value="round_trip"),
    ], ctx, retries=1)
    assert port.loaded_from is not None
    assert port.loaded_payload["cookies"][0]["value"] == "abc"


def test_load_auth_missing_file_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    port = _StubAuthPort()
    ctx = ActionContext(port=port)
    with pytest.raises(FileNotFoundError):
        execute_plan([Action(op="load_auth", value="never_saved")], ctx, retries=1)


def test_save_auth_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    port = _StubAuthPort()
    ctx = ActionContext(port=port)
    with pytest.raises(ValueError):
        execute_plan([Action(op="save_auth", value="../../etc/passwd")], ctx, retries=1)


def test_save_auth_uses_name_field_as_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    port = _StubAuthPort()
    ctx = ActionContext(port=port)
    # LLM might put the name on Action.name instead of Action.value
    execute_plan([Action(op="save_auth", name="from_name_field")], ctx, retries=1)
    assert port.saved_to.endswith("from_name_field.json")


def test_save_auth_requires_a_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    port = _StubAuthPort()
    ctx = ActionContext(port=port)
    with pytest.raises(ValueError):
        execute_plan([Action(op="save_auth")], ctx, retries=1)


# ---------------------------------------------------------------------
# Realistic plan — login once, reuse across two scenarios
# ---------------------------------------------------------------------

def test_realistic_save_then_load_skips_login(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    port = _StubAuthPort()
    ctx = ActionContext(port=port)
    # Scenario 1 — "login" then save_auth
    execute_plan([Action(op="save_auth", value="user_a")], ctx, retries=1)

    # Scenario 2 — fresh ctx, just load_auth. No re-login needed.
    port2 = _StubAuthPort()
    ctx2 = ActionContext(port=port2)
    execute_plan([Action(op="load_auth", value="user_a")], ctx2, retries=1)
    assert port2.loaded_from.endswith("user_a.json")
    assert port2.loaded_payload["local_storage"]["theme"] == "dark"
