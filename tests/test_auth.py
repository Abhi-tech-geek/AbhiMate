"""Phase C — signup, login, logout, password hashing, route gating."""

import uuid

import pytest


def _signup_payload(email_prefix="alice"):
    return {
        "email": f"{email_prefix}-{uuid.uuid4().hex[:6]}@example.com",
        "password": "ValidPass123!",
        "display_name": "Alice",
    }


# ---------- password helpers ----------

def test_hash_password_roundtrip():
    from utils.auth import hash_password, verify_password
    h = hash_password("super-secret")
    assert verify_password("super-secret", h) is True
    assert verify_password("wrong", h) is False
    assert verify_password("", h) is False


def test_hash_password_rejects_empty():
    from utils.auth import hash_password
    with pytest.raises(ValueError):
        hash_password("")


# ---------- signup ----------

def test_signup_creates_user_and_logs_in(anonymous_client):
    payload = _signup_payload()
    r = anonymous_client.post("/api/auth/signup", json=payload)
    assert r.status_code == 201
    data = r.get_json()
    assert data["email"] == payload["email"]
    # Subsequent /api/auth/me should now succeed.
    me = anonymous_client.get("/api/auth/me").get_json()
    assert me["user"]["email"] == payload["email"]
    assert me["quota"]["limit"] == 5


def test_signup_rejects_bad_email(anonymous_client):
    r = anonymous_client.post("/api/auth/signup",
                              json={"email": "not-an-email", "password": "ValidPass1"})
    assert r.status_code == 400


def test_signup_rejects_short_password(anonymous_client):
    r = anonymous_client.post("/api/auth/signup",
                              json={"email": "x@y.com", "password": "short"})
    assert r.status_code == 400


def test_signup_rejects_duplicate(anonymous_client):
    payload = _signup_payload()
    r1 = anonymous_client.post("/api/auth/signup", json=payload)
    assert r1.status_code == 201
    # Need a fresh client so the cookie from the first signup doesn't matter.
    r2 = anonymous_client.post("/api/auth/signup", json=payload)
    assert r2.status_code == 409


# ---------- login / logout ----------

def test_login_with_correct_credentials(anonymous_client, app_module):
    payload = _signup_payload("logintest")
    anonymous_client.post("/api/auth/signup", json=payload)
    anonymous_client.post("/api/auth/logout")
    r = anonymous_client.post("/api/auth/login",
                              json={"email": payload["email"], "password": payload["password"]})
    assert r.status_code == 200
    assert r.get_json()["email"] == payload["email"]


def test_login_rejects_wrong_password(anonymous_client):
    payload = _signup_payload()
    anonymous_client.post("/api/auth/signup", json=payload)
    anonymous_client.post("/api/auth/logout")
    r = anonymous_client.post("/api/auth/login",
                              json={"email": payload["email"], "password": "wrong-password"})
    assert r.status_code == 401


def test_login_rejects_unknown_email(anonymous_client):
    r = anonymous_client.post("/api/auth/login",
                              json={"email": "nobody@example.com", "password": "whatever"})
    assert r.status_code == 401


def test_logout_clears_session(auth_client):
    client, _ = auth_client
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    me = client.get("/api/auth/me").get_json()
    assert me["user"] is None


# ---------- route gating ----------

def test_index_redirects_when_anonymous(anonymous_client):
    r = anonymous_client.get("/", follow_redirects=False)
    assert r.status_code in (301, 302)
    assert "/login" in r.headers.get("Location", "")


def test_sessions_endpoint_requires_auth(anonymous_client):
    r = anonymous_client.get("/api/sessions")
    assert r.status_code == 401


def test_authenticated_user_sees_index(auth_client):
    client, _ = auth_client
    r = client.get("/")
    assert r.status_code == 200
    assert b"AbhiMate" in r.data
