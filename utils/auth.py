"""Authentication utilities — bcrypt hashing + Flask session glue.

Avoids `passlib` dependency: we use Python's stdlib + `bcrypt` directly. Falls
back to a salted-SHA256 PBKDF2 if bcrypt isn't installed (e.g. on the CI image
before deps are pinned). PBKDF2 is acceptable for a dev fallback; bcrypt is
preferred in production.
"""

from __future__ import annotations

import functools
import hmac
import os
import re
import secrets
from hashlib import pbkdf2_hmac
from typing import Optional, Callable

from flask import session, jsonify, request, redirect, url_for


_BCRYPT_AVAILABLE: Optional[bool] = None


def _bcrypt():
    global _BCRYPT_AVAILABLE
    if _BCRYPT_AVAILABLE is False:
        return None
    try:
        import bcrypt  # type: ignore
        _BCRYPT_AVAILABLE = True
        return bcrypt
    except Exception:
        _BCRYPT_AVAILABLE = False
        return None


# ----------------------------------------------------------------------
# Password hashing
# ----------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Hash a password. Returns a string like ``bcrypt$...`` or ``pbkdf2$...``."""
    if not isinstance(plain, str) or not plain:
        raise ValueError("password is required")
    b = _bcrypt()
    if b is not None:
        hashed = b.hashpw(plain.encode("utf-8"), b.gensalt(rounds=12))
        return "bcrypt$" + hashed.decode("utf-8")
    # PBKDF2 fallback (200k iterations, SHA-256)
    salt = secrets.token_bytes(16)
    dk = pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, 200_000)
    return "pbkdf2$200000$" + salt.hex() + "$" + dk.hex()


def verify_password(plain: str, stored: str) -> bool:
    if not stored or not isinstance(stored, str):
        return False
    if stored.startswith("bcrypt$"):
        b = _bcrypt()
        if b is None:
            return False
        try:
            return b.checkpw(plain.encode("utf-8"), stored[len("bcrypt$"):].encode("utf-8"))
        except Exception:
            return False
    if stored.startswith("pbkdf2$"):
        try:
            _, iters, salt_hex, dk_hex = stored.split("$", 3)
            dk = pbkdf2_hmac("sha256", plain.encode("utf-8"),
                             bytes.fromhex(salt_hex), int(iters))
            return hmac.compare_digest(dk.hex(), dk_hex)
        except Exception:
            return False
    return False


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MIN_PASSWORD_LEN = 8


def validate_signup(email: str, password: str) -> Optional[str]:
    """Return an error string if invalid, else None."""
    if not email or not _EMAIL_RE.match(email):
        return "Please enter a valid email address."
    if not password or len(password) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    return None


# ----------------------------------------------------------------------
# Flask session glue
# ----------------------------------------------------------------------

SESSION_USER_KEY = "user_id"


def set_session_user(user_id: int) -> None:
    session.clear()
    session[SESSION_USER_KEY] = int(user_id)
    session.permanent = True


def clear_session_user() -> None:
    session.pop(SESSION_USER_KEY, None)


def current_user_id() -> Optional[int]:
    uid = session.get(SESSION_USER_KEY)
    return int(uid) if uid is not None else None


def _wants_json() -> bool:
    if request.is_json:
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept or request.path.startswith("/api/")


def login_required(fn: Callable) -> Callable:
    """Gate a route on a logged-in user. API paths return 401 JSON, HTML
    paths redirect to /login.
    """
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        if current_user_id() is None:
            if _wants_json():
                return jsonify({"error": "Authentication required."}), 401
            return redirect(url_for("auth_page"))
        return fn(*args, **kwargs)
    return wrapped


def configure_flask(app) -> None:
    """Apply auth-related config to the Flask app instance."""
    secret = os.environ.get("ABHIMATE_SECRET")
    if not secret:
        # Per-install random secret persisted in data/ so sessions survive restart.
        secret_path = os.path.join("data", ".session_secret")
        os.makedirs(os.path.dirname(secret_path), exist_ok=True)
        if os.path.exists(secret_path):
            with open(secret_path, "rb") as f:
                secret = f.read().decode("utf-8", errors="ignore")
        if not secret:
            secret = secrets.token_hex(32)
            with open(secret_path, "w", encoding="utf-8") as f:
                f.write(secret)
    app.secret_key = secret
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
