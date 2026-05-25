"""Phase C — per-user 5-session quota + isolation between users."""

import time
import uuid

import pytest


def _make_dummy_session(app_module, user_id):
    from utils.models import TestSession
    sid = f"q-{uuid.uuid4().hex[:8]}"
    s = TestSession(
        session_id=sid,
        user_id=user_id,
        feature=f"feat-{sid}",
        state="GENERATED",
        timestamp=time.time(),
        test_cases=[],
    )
    app_module.memory_agent.save_session(s, user_id=user_id)
    return sid


def test_quota_reports_used_and_remaining(auth_client, app_module):
    _, user_id = auth_client
    q0 = app_module.memory_agent.quota_info(user_id)
    assert q0["limit"] == 5
    assert q0["used"] == 0
    assert q0["remaining"] == 5
    assert q0["at_limit"] is False

    for _ in range(3):
        _make_dummy_session(app_module, user_id)

    q1 = app_module.memory_agent.quota_info(user_id)
    assert q1["used"] == 3
    assert q1["remaining"] == 2
    assert q1["at_limit"] is False


def test_quota_blocks_sixth_session(auth_client, app_module):
    from agents.memory_manager_agent import QuotaExceeded
    _, user_id = auth_client
    for _ in range(5):
        _make_dummy_session(app_module, user_id)

    q = app_module.memory_agent.quota_info(user_id)
    assert q["at_limit"] is True

    with pytest.raises(QuotaExceeded):
        _make_dummy_session(app_module, user_id)


def test_delete_frees_quota_slot(auth_client, app_module):
    _, user_id = auth_client
    sids = [_make_dummy_session(app_module, user_id) for _ in range(5)]
    app_module.memory_agent.delete_session(sids[0], user_id=user_id)
    q = app_module.memory_agent.quota_info(user_id)
    assert q["used"] == 4
    assert q["at_limit"] is False
    # And we can now create one more without error.
    _make_dummy_session(app_module, user_id)


def test_users_dont_see_each_others_sessions(app_module):
    from utils.auth import hash_password
    db = app_module.memory_agent.db
    uid_a = db.create_user(f"a-{uuid.uuid4().hex[:6]}@x.com", hash_password("pwa"))
    uid_b = db.create_user(f"b-{uuid.uuid4().hex[:6]}@x.com", hash_password("pwb"))
    _make_dummy_session(app_module, uid_a)
    _make_dummy_session(app_module, uid_a)
    _make_dummy_session(app_module, uid_b)

    a_list = app_module.memory_agent.list_all_sessions(user_id=uid_a)
    b_list = app_module.memory_agent.list_all_sessions(user_id=uid_b)
    assert len(a_list) == 2
    assert len(b_list) == 1


def test_cross_user_load_is_forbidden(app_module):
    from utils.auth import hash_password
    from agents.memory_manager_agent import NotOwner

    db = app_module.memory_agent.db
    uid_a = db.create_user(f"a-{uuid.uuid4().hex[:6]}@x.com", hash_password("pwa"))
    uid_b = db.create_user(f"b-{uuid.uuid4().hex[:6]}@x.com", hash_password("pwb"))
    sid = _make_dummy_session(app_module, uid_a)

    # Owner can load
    app_module.memory_agent.load_session(sid, user_id=uid_a)
    # Stranger gets NotOwner
    with pytest.raises(NotOwner):
        app_module.memory_agent.load_session(sid, user_id=uid_b)


def test_quota_endpoint_blocks_smart_input(auth_client, app_module):
    client, user_id = auth_client
    for _ in range(5):
        _make_dummy_session(app_module, user_id)
    r = client.post("/api/smart_input", json={"prompt": "Test the login page"})
    assert r.status_code == 409
    body = r.get_json()
    assert "quota" in body
    assert body["quota"]["used"] == 5
