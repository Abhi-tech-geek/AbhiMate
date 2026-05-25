"""Feature #10 - Record + replay import.

Three layers:
1. recording_importer (pure parser/validator)
2. Pydantic round-trip (TestCase + Action models accept the recorded ops)
3. Flask endpoint (auth, quota, size cap, error shapes)
"""

from __future__ import annotations

import json
import os
import time
import uuid

import pytest


def _valid_payload(**overrides):
    base = {
        "version": 1,
        "feature": "Login flow",
        "url": "https://app.example.com/login",
        "actions": [
            {"op": "goto", "url": "https://app.example.com/login"},
            {"op": "fill",
             "locator": {"by": "id", "value": "email",
                         "fallbacks": [{"by": "name", "value": "email"}]},
             "value": "user@example.com"},
            {"op": "click", "locator": {"by": "text", "value": "Sign in"}},
            {"op": "assert_visible", "locator": {"by": "id", "value": "dashboard"}},
        ],
    }
    base.update(overrides)
    return base


# ======================================================================
# 1. recording_importer pure parser
# ======================================================================

def test_import_recording_builds_session_with_one_case():
    from utils.recording_importer import import_recording
    session, info = import_recording(_valid_payload(), user_id=11)
    assert session.user_id == 11
    assert session.state == "GENERATED"
    assert len(session.test_cases) == 1
    tc = session.test_cases[0]
    assert tc.tags == ["@recorded"]
    assert [a.op for a in tc.action_plan] == ["goto", "fill", "click", "assert_visible"]
    assert info["action_count"] == 4


def test_import_recording_derives_feature_from_host_when_label_missing():
    from utils.recording_importer import import_recording
    payload = _valid_payload(feature="")
    session, info = import_recording(payload)
    assert "example.com" in session.feature
    assert info["source_url"] == "https://app.example.com/login"


def test_import_recording_falls_back_to_generic_label_when_no_url():
    from utils.recording_importer import import_recording
    payload = {
        "version": 1, "feature": "",
        "actions": [{"op": "click", "locator": {"by": "text", "value": "x"}}],
    }
    session, _ = import_recording(payload)
    assert session.feature == "Recorded session"


def test_import_recording_generates_gherkin_for_each_action():
    from utils.recording_importer import import_recording
    session, _ = import_recording(_valid_payload())
    tc = session.test_cases[0]
    assert len(tc.gherkin_steps) == 4
    # Sanity-check keywords map correctly
    keywords = [s.keyword for s in tc.gherkin_steps]
    assert keywords[0] == "Given"     # goto -> Given
    assert "When" in keywords          # fill/click
    assert "Then" in keywords          # assert_visible


def test_import_recording_rejects_non_dict_payload():
    from utils.recording_importer import import_recording, RecordingImportError
    with pytest.raises(RecordingImportError):
        import_recording("just a string")  # type: ignore[arg-type]


def test_import_recording_rejects_missing_actions():
    from utils.recording_importer import import_recording, RecordingImportError
    with pytest.raises(RecordingImportError, match="non-empty"):
        import_recording({"feature": "x"})


def test_import_recording_rejects_empty_actions_list():
    from utils.recording_importer import import_recording, RecordingImportError
    with pytest.raises(RecordingImportError, match="non-empty"):
        import_recording({"feature": "x", "actions": []})


def test_import_recording_caps_action_count():
    from utils.recording_importer import import_recording, RecordingImportError, MAX_ACTIONS
    huge = {
        "actions": [{"op": "click", "locator": {"by": "id", "value": "x"}}
                    for _ in range(MAX_ACTIONS + 1)],
    }
    with pytest.raises(RecordingImportError, match="too many"):
        import_recording(huge)


def test_import_recording_rejects_unknown_op():
    from utils.recording_importer import import_recording, RecordingImportError
    payload = {"actions": [{"op": "exfiltrate", "url": "x"}]}
    with pytest.raises(RecordingImportError, match="unsupported"):
        import_recording(payload)


def test_import_recording_rejects_malformed_action():
    from utils.recording_importer import import_recording, RecordingImportError
    payload = {"actions": ["not-a-dict"]}
    with pytest.raises(RecordingImportError):
        import_recording(payload)


def test_import_recording_preserves_locator_fallbacks():
    """The fallback chain is what makes recordings survive small UI changes —
    make sure it round-trips through the importer unchanged."""
    from utils.recording_importer import import_recording
    payload = {"actions": [{
        "op": "click",
        "locator": {
            "by": "id", "value": "submit",
            "fallbacks": [
                {"by": "testid", "value": "submit-btn"},
                {"by": "text", "value": "Submit"},
            ],
        },
    }]}
    session, _ = import_recording(payload)
    loc = session.test_cases[0].action_plan[0].locator
    assert loc.by == "id" and loc.value == "submit"
    assert len(loc.fallbacks) == 2
    assert loc.fallbacks[0].by == "testid"


def test_import_recording_truncates_overly_long_feature_label():
    from utils.recording_importer import import_recording
    long_name = "x" * 500
    session, _ = import_recording(_valid_payload(feature=long_name))
    assert len(session.feature) <= 200


# ======================================================================
# 2. Flask endpoint
# ======================================================================

def test_endpoint_requires_auth(anonymous_client):
    r = anonymous_client.post("/api/import/recording", json=_valid_payload())
    assert r.status_code == 401


def test_endpoint_imports_valid_recording(auth_client, app_module):
    client, uid = auth_client
    payload = _valid_payload()
    r = client.post("/api/import/recording", json=payload)
    assert r.status_code == 200
    body = r.get_json()
    assert body["feature"] == "Login flow"
    assert body["imported"]["action_count"] == 4
    assert "session_id" in body
    # Loading the new session round-trips
    got = app_module.memory_agent.load_session(body["session_id"], user_id=uid)
    assert got.user_id == uid
    assert got.test_cases[0].tags == ["@recorded"]


def test_endpoint_returns_400_on_invalid_payload(auth_client):
    client, _ = auth_client
    r = client.post("/api/import/recording", json={"feature": "no actions"})
    assert r.status_code == 400
    body = r.get_json()
    assert body["code"] == "recording_invalid"


def test_endpoint_returns_400_on_unsupported_op(auth_client):
    client, _ = auth_client
    r = client.post(
        "/api/import/recording",
        json={"actions": [{"op": "drop_table", "url": "x"}]},
    )
    assert r.status_code == 400


def test_endpoint_rejects_oversize_body(auth_client):
    client, _ = auth_client
    huge = "A" * (600 * 1024)
    r = client.post(
        "/api/import/recording",
        data=huge,
        content_type="application/json",
    )
    assert r.status_code == 413
    assert r.get_json()["code"] == "recording_too_large"


def test_endpoint_enforces_session_quota(auth_client, app_module):
    """Once the user is at 5/5 the endpoint must 409 — no silent overwrite."""
    client, uid = auth_client
    from utils.models import TestSession
    for i in range(5):
        app_module.memory_agent.save_session(
            TestSession(
                session_id=f"prefilled-{i}-{uuid.uuid4().hex[:6]}",
                user_id=uid, feature=f"f{i}",
                state="GENERATED", timestamp=time.time(), test_cases=[],
            ),
            user_id=uid,
        )
    r = client.post("/api/import/recording", json=_valid_payload())
    assert r.status_code == 409
    body = r.get_json()
    assert body["code"] == "quota_exceeded"
    assert "quota" in body


def test_endpoint_imports_are_user_scoped(auth_client, app_module):
    """A recording imported by user A is not visible to user B."""
    client_a, uid_a = auth_client
    r = client_a.post("/api/import/recording", json=_valid_payload())
    sid = r.get_json()["session_id"]
    # Forge a second user via the DB directly
    other_email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    other_uid = app_module.memory_agent.db.create_user(
        email=other_email,
        password_hash=app_module.hash_password("ValidPass123!"),
        display_name="Other",
    )
    client_b = app_module.app.test_client()
    with client_b.session_transaction() as sess:
        sess["user_id"] = int(other_uid)
    # B cannot fetch A's session
    r_b = client_b.get(f"/api/sessions/{sid}")
    assert r_b.status_code in (403, 404)


# ======================================================================
# 3. Chrome extension manifest sanity
# ======================================================================

def test_extension_manifest_is_valid_v3():
    """The shipped manifest must be MV3 and declare the perms we use."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    manifest_path = os.path.join(here, "chrome_extension", "manifest.json")
    assert os.path.isfile(manifest_path)
    with open(manifest_path, "r", encoding="utf-8") as fh:
        m = json.load(fh)
    assert m.get("manifest_version") == 3
    perms = set(m.get("permissions") or [])
    assert {"scripting", "tabs", "storage", "webNavigation"}.issubset(perms)
    # Service worker, popup, content script must exist on disk
    sw = os.path.join(here, "chrome_extension", m["background"]["service_worker"])
    assert os.path.isfile(sw)
    popup = os.path.join(here, "chrome_extension", m["action"]["default_popup"])
    assert os.path.isfile(popup)
    assert os.path.isfile(os.path.join(here, "chrome_extension", "content.js"))
