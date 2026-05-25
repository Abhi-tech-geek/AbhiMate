"""Feature #9 — self-healing locator cache.

Three layers covered:
1. DB CRUD on locator_cache table
2. enhance_locator / record_winning helpers
3. End-to-end via fake port — fallback wins once, primary swaps next run
"""

import pytest

from database.db_core import SQLiteDB
from utils.action_engine import execute_plan, ActionContext
from utils.models import Action, Locator
from utils.self_healing import (
    enhance_locator, record_winning, host_from_url, parse_used_strategy,
)


# ---------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------

def fresh_db(tmp_path):
    return SQLiteDB(db_path=str(tmp_path / "lc.db"))


# ---------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://example.com/login",         "example.com"),
    ("http://localhost:5000/x",            "localhost"),
    ("https://sub.example.com/a/b?x=1",   "sub.example.com"),
    ("",                                   ""),
    ("not-a-url",                          ""),
])
def test_host_from_url(url, expected):
    assert host_from_url(url) == expected


def test_parse_used_strategy():
    assert parse_used_strategy("id=email") == ("id", "email")
    assert parse_used_strategy("css=button[type=submit]") == ("css", "button[type=submit]")
    assert parse_used_strategy("invalid") is None
    assert parse_used_strategy(None) is None


# ---------------------------------------------------------------------
# DB CRUD
# ---------------------------------------------------------------------

def test_lookup_returns_none_for_missing(tmp_path):
    db = fresh_db(tmp_path)
    assert db.lookup_locator("example.com", "id", "email") is None


def test_record_then_lookup_round_trip(tmp_path):
    db = fresh_db(tmp_path)
    db.record_locator("example.com", "id", "email", "name", "email")
    hit = db.lookup_locator("example.com", "id", "email")
    assert hit is not None
    assert hit["winning_by"] == "name"
    assert hit["winning_value"] == "email"
    assert hit["success_count"] == 1


def test_record_same_winner_bumps_count(tmp_path):
    db = fresh_db(tmp_path)
    db.record_locator("example.com", "id", "email", "name", "email")
    db.record_locator("example.com", "id", "email", "name", "email")
    db.record_locator("example.com", "id", "email", "name", "email")
    hit = db.lookup_locator("example.com", "id", "email")
    assert hit["success_count"] == 3


def test_record_different_winner_resets(tmp_path):
    db = fresh_db(tmp_path)
    db.record_locator("example.com", "id", "email", "name", "email")
    db.record_locator("example.com", "id", "email", "name", "email")
    db.record_locator("example.com", "id", "email", "css", "input[type=email]")
    hit = db.lookup_locator("example.com", "id", "email")
    assert hit["winning_by"] == "css"
    assert hit["winning_value"] == "input[type=email]"
    assert hit["success_count"] == 1  # reset


def test_host_scoping(tmp_path):
    db = fresh_db(tmp_path)
    db.record_locator("prod.com", "id", "email", "name", "email")
    db.record_locator("staging.com", "id", "email", "testid", "email-input")
    assert db.lookup_locator("prod.com", "id", "email")["winning_by"] == "name"
    assert db.lookup_locator("staging.com", "id", "email")["winning_by"] == "testid"


def test_list_locator_cache_orders_by_recency(tmp_path):
    db = fresh_db(tmp_path)
    db.record_locator("a.com", "id", "1", "name", "1")
    db.record_locator("b.com", "id", "2", "name", "2")
    db.record_locator("a.com", "id", "3", "css", ".x")
    rows = db.list_locator_cache()
    assert len(rows) == 3
    # Most recently inserted first
    assert rows[0]["primary_value"] == "3"


def test_list_filter_by_host(tmp_path):
    db = fresh_db(tmp_path)
    db.record_locator("a.com", "id", "1", "name", "1")
    db.record_locator("b.com", "id", "2", "name", "2")
    rows = db.list_locator_cache(host="a.com")
    assert len(rows) == 1
    assert rows[0]["host"] == "a.com"


def test_clear_all_or_by_host(tmp_path):
    db = fresh_db(tmp_path)
    db.record_locator("a.com", "id", "1", "name", "1")
    db.record_locator("b.com", "id", "2", "name", "2")
    db.clear_locator_cache(host="a.com")
    assert db.lookup_locator("a.com", "id", "1") is None
    assert db.lookup_locator("b.com", "id", "2") is not None
    db.clear_locator_cache()  # wipe
    assert db.lookup_locator("b.com", "id", "2") is None


# ---------------------------------------------------------------------
# enhance_locator
# ---------------------------------------------------------------------

def test_enhance_locator_no_cache_returns_original(tmp_path):
    db = fresh_db(tmp_path)
    loc = Locator(by="id", value="email", fallbacks=[Locator(by="name", value="email")])
    out = enhance_locator(loc, "example.com", db)
    assert out is loc   # untouched


def test_enhance_locator_prepends_cached_winner(tmp_path):
    db = fresh_db(tmp_path)
    db.record_locator("example.com", "id", "email", "name", "email")

    original = Locator(by="id", value="email",
                       fallbacks=[Locator(by="css", value="input[type=email]")])
    out = enhance_locator(original, "example.com", db)

    # New primary = cached winner
    assert out.by == "name"
    assert out.value == "email"
    # Original primary becomes first fallback
    assert out.fallbacks[0].by == "id"
    assert out.fallbacks[0].value == "email"
    # Then the original's own fallbacks follow
    assert out.fallbacks[1].by == "css"


def test_enhance_locator_no_op_when_cache_matches_primary(tmp_path):
    """If we cached (id, email) as the winner of (id, email) — that's a no-op."""
    db = fresh_db(tmp_path)
    db.record_locator("example.com", "id", "email", "id", "email")
    loc = Locator(by="id", value="email")
    out = enhance_locator(loc, "example.com", db)
    assert out is loc


def test_enhance_locator_returns_original_without_host():
    loc = Locator(by="id", value="email")
    # No host (e.g. before any goto) -> no cache lookup possible
    assert enhance_locator(loc, "", db=None) is loc


# ---------------------------------------------------------------------
# record_winning
# ---------------------------------------------------------------------

def test_record_winning_only_records_fallback_wins(tmp_path):
    db = fresh_db(tmp_path)
    original = Locator(by="id", value="email")
    record_winning(original, "id=email", "example.com", db)
    # Primary won — nothing recorded
    assert db.lookup_locator("example.com", "id", "email") is None


def test_record_winning_persists_fallback_strategy(tmp_path):
    db = fresh_db(tmp_path)
    original = Locator(by="id", value="email",
                       fallbacks=[Locator(by="name", value="email")])
    record_winning(original, "name=email", "example.com", db)
    hit = db.lookup_locator("example.com", "id", "email")
    assert hit is not None
    assert hit["winning_by"] == "name"


def test_record_winning_graceful_on_bad_input(tmp_path):
    db = fresh_db(tmp_path)
    original = Locator(by="id", value="email")
    # Malformed used_strategy — should be silent, no crash, no row
    record_winning(original, "not-parseable", "example.com", db)
    record_winning(original, "id=email", "", db)         # empty host
    record_winning(original, "id=email", "example.com", db=None)  # no db
    assert db.lookup_locator("example.com", "id", "email") is None


# ---------------------------------------------------------------------
# End-to-end via fake port
# ---------------------------------------------------------------------

class _HealPort:
    """A port that simulates DOM drift: primary 'id=email' always misses;
    'name=email' (the first fallback) always wins."""

    def __init__(self, current_url="https://example.com/login"):
        self._url = current_url
        self.find_calls = []
        self.driver = None

    @property
    def current_url(self): return self._url

    def find(self, locator, timeout_ms):
        self.find_calls.append((locator.by, locator.value,
                               [(f.by, f.value) for f in (locator.fallbacks or [])]))
        # Whatever the engine asks first, the FIRST locator that matches
        # (id=email OR name=email pattern) wins. Simulate: id=email never
        # matches; name=email always matches.
        candidates = [(locator.by, locator.value)] + [(f.by, f.value) for f in (locator.fallbacks or [])]
        for by, value in candidates:
            if by == "name" and value == "email":
                el = _FakeEl()
                return el, f"{by}={value}"
        # Nothing matched — raise like the real port would
        raise LookupError("no locator hit")


class _FakeEl:
    def click(self): pass
    def clear(self): pass
    def send_keys(self, v): pass
    def fill(self, v): pass
    @property
    def text(self): return ""
    def is_displayed(self): return True
    def get_attribute(self, name): return None


def test_first_run_records_fallback_winner(tmp_path):
    db = fresh_db(tmp_path)
    port = _HealPort()
    ctx = ActionContext(port=port, locator_db=db)

    primary = Locator(by="id", value="email",
                      fallbacks=[Locator(by="name", value="email")])
    execute_plan([Action(op="click", locator=primary)], ctx, retries=1)

    # Cache should now know that name=email is the winner for id=email on this host.
    hit = db.lookup_locator("example.com", "id", "email")
    assert hit is not None
    assert hit["winning_by"] == "name"
    assert hit["winning_value"] == "email"
    assert hit["success_count"] == 1


def test_second_run_tries_cached_winner_first(tmp_path):
    db = fresh_db(tmp_path)
    # Seed cache as if a prior run learned the mapping.
    db.record_locator("example.com", "id", "email", "name", "email")

    port = _HealPort()
    ctx = ActionContext(port=port, locator_db=db)

    primary = Locator(by="id", value="email",
                      fallbacks=[Locator(by="css", value="input[type=email]")])
    execute_plan([Action(op="click", locator=primary)], ctx, retries=1)

    # The port should have been asked with 'name=email' AS PRIMARY this time.
    first_call = port.find_calls[0]
    assert first_call[0] == "name"
    assert first_call[1] == "email"
    # The original id=email should be the FIRST in the fallback chain.
    assert ("id", "email") in first_call[2]


def test_cache_bumps_count_on_repeated_wins(tmp_path):
    """Every fallback win re-records → count tracks confidence in the cached
    selector. Three runs of the same plan = count of 3."""
    db = fresh_db(tmp_path)
    port = _HealPort()
    ctx = ActionContext(port=port, locator_db=db)

    primary = Locator(by="id", value="email",
                      fallbacks=[Locator(by="name", value="email")])
    for _ in range(3):
        execute_plan([Action(op="click", locator=primary)], ctx, retries=1)

    hit = db.lookup_locator("example.com", "id", "email")
    assert hit["winning_by"] == "name"
    assert hit["success_count"] == 3


def test_self_heal_disabled_when_no_db(tmp_path):
    """Old test patterns (no locator_db) keep working with no overhead."""
    port = _HealPort()
    ctx = ActionContext(port=port)   # no locator_db

    primary = Locator(by="id", value="email",
                      fallbacks=[Locator(by="name", value="email")])
    execute_plan([Action(op="click", locator=primary)], ctx, retries=1)
    # No db means no enhance + no record — port saw the original primary first.
    first_call = port.find_calls[0]
    assert first_call[0] == "id"
    assert first_call[1] == "email"


def test_endpoint_lists_cache(auth_client, app_module):
    """/api/locator_cache returns the persisted entries."""
    client, _ = auth_client
    # Seed via the agent's own DB (same path as the app).
    app_module.memory_agent.db.record_locator(
        "example.com", "id", "email", "name", "email",
    )
    r = client.get("/api/locator_cache?host=example.com")
    assert r.status_code == 200
    data = r.get_json()
    # Cache row may have been planted by other tests — filter to ours.
    matching = [e for e in data["entries"]
                if e["primary_by"] == "id" and e["primary_value"] == "email"]
    assert any(m["winning_by"] == "name" for m in matching)


def test_endpoint_requires_auth(anonymous_client):
    r = anonymous_client.get("/api/locator_cache")
    assert r.status_code == 401


def test_endpoint_clear_by_host(auth_client, app_module):
    client, _ = auth_client
    db = app_module.memory_agent.db
    db.record_locator("clearme.test", "id", "x", "name", "x")
    db.record_locator("keepme.test", "id", "y", "name", "y")

    r = client.delete("/api/locator_cache?host=clearme.test")
    assert r.status_code == 200
    assert r.get_json()["deleted"] >= 1
    # Surviving host unaffected
    assert db.lookup_locator("keepme.test", "id", "y") is not None
    assert db.lookup_locator("clearme.test", "id", "x") is None
