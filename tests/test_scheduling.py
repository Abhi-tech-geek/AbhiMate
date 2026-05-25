"""Feature #7 — Scheduled runs + Slack notifications.

Five layers covered:
1. Schedule expression parser (intervals, daily, error cases)
2. DB CRUD (slack creds + schedules + claim/finalize race semantics)
3. Slack notifier (block kit shape, webhook validation, transport errors)
4. Scheduler.tick (happy path + missing-session + broken-expression + Slack fail)
5. Flask endpoints (auth scoped, parser errors, cross-tenant 404)
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, patch

import pytest


# ======================================================================
# 1. Parser
# ======================================================================

@pytest.mark.parametrize("expr,expected_sec", [
    ("every 5m",  300),
    ("every 30m", 1800),
    ("every 2h",  7200),
    ("every 1d",  86400),
    ("EVERY 6H",  21600),
])
def test_parse_interval(expr, expected_sec):
    from utils.schedule_expr import parse
    s = parse(expr)
    assert s.kind == "interval"
    assert s.seconds == expected_sec
    assert s.next_after(1000) == 1000 + expected_sec


def test_parse_daily_advances_to_tomorrow_if_past():
    from utils.schedule_expr import parse
    import datetime
    # Pick "daily 00:00" and feed a "now" of 12:00 — next firing must be the
    # next day at 00:00 UTC.
    base = datetime.datetime(2026, 5, 25, 12, 0, tzinfo=datetime.timezone.utc).timestamp()
    s = parse("daily 00:00")
    nxt = s.next_after(base)
    dt = datetime.datetime.fromtimestamp(nxt, tz=datetime.timezone.utc)
    assert dt.day == 26 and dt.hour == 0 and dt.minute == 0


def test_parse_daily_today_when_future():
    from utils.schedule_expr import parse
    import datetime
    base = datetime.datetime(2026, 5, 25, 6, 30, tzinfo=datetime.timezone.utc).timestamp()
    s = parse("daily 09:00")
    dt = datetime.datetime.fromtimestamp(s.next_after(base), tz=datetime.timezone.utc)
    assert dt.day == 25 and dt.hour == 9


@pytest.mark.parametrize("bad", [
    "", "garbage", "every", "every 10",
    "every 30s",        # below 1-minute floor
    "every 999d",       # above 7-day ceiling
    "daily 25:00",      # bad hour
    "daily 09:99",      # bad minute
])
def test_parse_rejects_bad_input(bad):
    from utils.schedule_expr import parse, ScheduleExprError
    with pytest.raises(ScheduleExprError):
        parse(bad)


def test_humanize_round_trip():
    from utils.schedule_expr import parse
    assert "minute" in parse("every 30m").humanize()
    assert "hour" in parse("every 6h").humanize()
    assert "day" in parse("every 2d").humanize()
    assert "09:00 UTC" in parse("daily 09:00").humanize()


# ======================================================================
# 2. DB CRUD
# ======================================================================

@pytest.fixture
def db(tmp_db_path):
    from database.db_core import SQLiteDB
    return SQLiteDB(tmp_db_path)


def test_slack_set_get_delete(db):
    db.set_slack_credentials(7, "https://hooks.slack.com/services/T/B/secret",
                              default_channel="#qa", mention_on_fail="<!here>")
    row = db.get_slack_credentials(7)
    assert row["webhook_url"].endswith("/secret")
    assert row["default_channel"] == "#qa"
    pub = db.get_slack_credentials_public(7)
    # Public view masks the secret
    assert "secret" not in pub["webhook_mask"]
    assert db.delete_slack_credentials(7) is True
    assert db.get_slack_credentials(7) is None


def test_slack_set_rejects_non_slack_url(db):
    with pytest.raises(ValueError, match="hooks.slack.com"):
        db.set_slack_credentials(7, "https://example.com/webhook")


def test_schedule_upsert_then_list_and_get(db):
    sid = db.upsert_schedule(
        user_id=4, session_id="s-aaa",
        expression="every 1h", next_run_at=time.time() + 3600,
        slack_notify=True,
    )
    rows = db.list_schedules(4)
    assert len(rows) == 1 and rows[0]["id"] == sid
    assert db.get_schedule(sid, user_id=4)["session_id"] == "s-aaa"
    # Cross-user must not see it
    assert db.get_schedule(sid, user_id=9999) is None


def test_schedule_toggle_enabled(db):
    sid = db.upsert_schedule(2, "s1", "every 1h", time.time() + 3600)
    assert db.set_schedule_enabled(sid, 2, False) is True
    assert db.get_schedule(sid, 2)["enabled"] is False


def test_schedule_delete_user_scoped(db):
    sid = db.upsert_schedule(2, "s1", "every 1h", time.time() + 3600)
    assert db.delete_schedule(sid, user_id=99) is False  # wrong user
    assert db.delete_schedule(sid, user_id=2) is True


def test_claim_due_atomically_pushes_next_run_at(db):
    """A second concurrent tick must not re-claim the same row."""
    now = time.time()
    sid = db.upsert_schedule(1, "s1", "every 1h", now - 10)   # already due
    db.upsert_schedule(1, "s2", "every 1h", now + 1000)        # not yet due

    first = db.claim_due_schedules(now)
    second = db.claim_due_schedules(now)

    assert [c["id"] for c in first] == [sid]
    assert second == []  # row's next_run_at was pushed by claim_due


def test_finalize_schedule_run_persists_status(db):
    sid = db.upsert_schedule(1, "s1", "every 1h", time.time() - 10)
    db.finalize_schedule_run(sid, time.time() + 3600, "ok", error=None)
    row = db.get_schedule(sid, 1)
    assert row["last_status"] == "ok"
    assert row["last_run_at"] is not None


# ======================================================================
# 3. Slack notifier
# ======================================================================

def test_build_payload_passing_run_uses_green():
    from utils.slack_notifier import build_run_payload
    payload = build_run_payload(
        session_feature="Login",
        session_id="abcd1234",
        metrics={"total": 3, "passed": 3, "failed": 0, "skipped": 0},
        test_cases=[],
    )
    assert "blocks" in payload
    headline = payload["blocks"][1]["text"]["text"]
    assert "3/3 passed" in headline
    assert ":large_green_circle:" in headline


def test_build_payload_lists_failures():
    from utils.slack_notifier import build_run_payload

    class Fake:
        def __init__(self, _id, status, error):
            self.id = _id; self.status = status; self.error = error

    cases = [
        Fake("TC001", "Pass", None),
        Fake("TC002", "Fail", "AssertionError: button missing\nstack trace…"),
        Fake("TC003", "Fail", "TimeoutError: locator never visible"),
    ]
    payload = build_run_payload(
        session_feature="Checkout",
        session_id="s",
        metrics={"total": 3, "passed": 1, "failed": 2, "skipped": 0},
        test_cases=cases,
        mention_on_fail="<!channel>",
    )
    text_blob = "\n".join(b.get("text", {}).get("text", "") for b in payload["blocks"]
                          if b.get("type") == "section")
    assert "TC002" in text_blob and "TC003" in text_blob
    # Mention only fires when there are failures
    assert "<!channel>" in text_blob
    # Multiline error is collapsed to first line only
    assert "stack trace" not in text_blob


def test_build_payload_includes_session_link():
    from utils.slack_notifier import build_run_payload
    payload = build_run_payload(
        session_feature="x", session_id="s",
        metrics={"total": 1, "passed": 1, "failed": 0, "skipped": 0},
        test_cases=[], session_url="https://abhi.test/?session=s",
    )
    action_blocks = [b for b in payload["blocks"] if b.get("type") == "actions"]
    assert action_blocks and action_blocks[0]["elements"][0]["url"] == "https://abhi.test/?session=s"


def test_validate_webhook_url():
    from utils.slack_notifier import validate_webhook_url, SlackError
    validate_webhook_url("https://hooks.slack.com/services/T/B/secret")
    with pytest.raises(SlackError):
        validate_webhook_url("")
    with pytest.raises(SlackError):
        validate_webhook_url("https://example.com/webhook")


def test_post_payload_raises_on_non_2xx():
    from utils.slack_notifier import post_payload, SlackError
    fake_resp = MagicMock(status_code=500, text="boom")
    fake_session = MagicMock(); fake_session.post = MagicMock(return_value=fake_resp)
    with pytest.raises(SlackError, match="500"):
        post_payload("https://hooks.slack.com/services/T/B/x",
                     {"text": "hi"}, session=fake_session)


def test_post_payload_passes_through_ok():
    from utils.slack_notifier import post_payload
    ok_resp = MagicMock(status_code=200, text="ok")
    fake_session = MagicMock(); fake_session.post = MagicMock(return_value=ok_resp)
    post_payload("https://hooks.slack.com/services/T/B/x",
                 {"text": "hi"}, session=fake_session)
    fake_session.post.assert_called_once()


# ======================================================================
# 4. Scheduler.tick
# ======================================================================

class _FakeSession:
    def __init__(self, sid, feature="hello", cases=None):
        self.session_id = sid; self.feature = feature
        self.test_cases = cases or []


def _build_scheduler(db, *, exec_events=None, exec_raises=None, slack_post=None):
    from utils.scheduler import Scheduler

    memory = MagicMock()
    memory.load_session = MagicMock(side_effect=lambda sid, user_id=None: _FakeSession(sid))

    executor = MagicMock()
    if exec_raises:
        executor.execute_streaming = MagicMock(side_effect=exec_raises)
    else:
        events = exec_events or [{"type": "done",
                                  "metrics": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                                  "test_cases": []}]
        executor.execute_streaming = MagicMock(return_value=iter(events))

    sched = Scheduler(memory, executor, db, tick_seconds=60)
    # Slack post is opt-in per test
    if slack_post is not None:
        import utils.slack_notifier as sn
        sched._slack_patch = patch.object(sn, "post_run_result", side_effect=slack_post)
        sched._slack_patch.start()
    return sched, memory, executor


def test_tick_fires_due_schedule_and_updates_next_run(db):
    sid = db.upsert_schedule(1, "s-x", "every 1h", time.time() - 10, slack_notify=False)
    sched, _, executor = _build_scheduler(db)
    fired = sched.tick(time.time())
    assert [f["id"] for f in fired] == [sid]
    executor.execute_streaming.assert_called_once()
    row = db.get_schedule(sid, 1)
    assert row["last_status"] == "ok"
    assert row["next_run_at"] > time.time() + 3500   # ~ +1h from now


def test_tick_skips_future_schedules(db):
    db.upsert_schedule(1, "s-x", "every 1h", time.time() + 1000)
    sched, _, executor = _build_scheduler(db)
    fired = sched.tick(time.time())
    assert fired == []
    executor.execute_streaming.assert_not_called()


def test_tick_broken_expression_marks_row(db):
    # Hand-write a broken expression directly into the row.
    sid = db.upsert_schedule(1, "s-x", "every 1h", time.time() - 5)
    import sqlite3
    with sqlite3.connect(db.db_path) as c:
        c.execute("UPDATE schedules SET expression = ? WHERE id = ?", ("not-an-expr", sid))
    sched, _, executor = _build_scheduler(db)
    sched.tick(time.time())
    row = db.get_schedule(sid, 1)
    assert row["last_status"] == "broken"
    executor.execute_streaming.assert_not_called()


def test_tick_missing_session_marks_row(db):
    sid = db.upsert_schedule(1, "ghost", "every 1h", time.time() - 5)
    sched, memory, _ = _build_scheduler(db)
    memory.load_session.side_effect = LookupError("no such session")
    sched.tick(time.time())
    row = db.get_schedule(sid, 1)
    assert row["last_status"] == "missing-session"


def test_tick_executor_error_marked(db):
    db.upsert_schedule(1, "s", "every 1h", time.time() - 5)
    sched, _, _ = _build_scheduler(db, exec_raises=RuntimeError("chrome dead"))
    sched.tick(time.time())
    row = db.list_schedules(1)[0]
    assert row["last_status"] == "error"
    assert "chrome dead" in (row["last_error"] or "")


def test_tick_calls_slack_notifier_with_metrics(db):
    db.upsert_schedule(1, "s", "every 1h", time.time() - 5, slack_notify=True)
    db.set_slack_credentials(1, "https://hooks.slack.com/services/T/B/secret")
    captured = {}

    def fake_post(*args, **kwargs):
        # The scheduler passes the webhook URL as a positional, then everything
        # else as kwargs — accept both shapes so the mock never raises.
        captured["webhook_url"] = args[0] if args else kwargs.get("webhook_url")
        captured.update(kwargs)

    with patch("utils.slack_notifier.post_run_result", side_effect=fake_post):
        sched, _, _ = _build_scheduler(db)
        sched.tick(time.time())
    assert captured.get("metrics") == {"total": 1, "passed": 1, "failed": 0, "skipped": 0}
    assert captured.get("schedule_expr") == "every 1h"
    assert captured.get("webhook_url", "").startswith("https://hooks.slack.com/")


def test_tick_slack_failure_annotates_row(db):
    db.upsert_schedule(1, "s", "every 1h", time.time() - 5, slack_notify=True)
    db.set_slack_credentials(1, "https://hooks.slack.com/services/T/B/secret")

    from utils.slack_notifier import SlackError
    def boom(*_args, **_kwargs):
        raise SlackError("Slack 500")

    with patch("utils.slack_notifier.post_run_result", side_effect=boom):
        sched, _, _ = _build_scheduler(db)
        sched.tick(time.time())
    row = db.list_schedules(1)[0]
    # Run itself succeeded; only the slack post failed.
    assert row["last_status"] == "ok"
    assert "Slack 500" in (row["last_error"] or "")


# ======================================================================
# 5. Flask endpoints
# ======================================================================

def test_slack_endpoints_require_auth(anonymous_client):
    assert anonymous_client.get("/api/notifications/slack").status_code == 401
    assert anonymous_client.put("/api/notifications/slack", json={"webhook_url": ""}).status_code == 401
    assert anonymous_client.delete("/api/notifications/slack").status_code == 401
    assert anonymous_client.post("/api/notifications/slack/test").status_code == 401


def test_slack_put_rejects_bad_url(auth_client):
    client, _ = auth_client
    r = client.put("/api/notifications/slack", json={"webhook_url": "https://evil.example/x"})
    assert r.status_code == 400
    assert "hooks.slack.com" in r.get_json()["error"]


def test_slack_put_then_get_masks(auth_client):
    client, _ = auth_client
    r = client.put("/api/notifications/slack",
                   json={"webhook_url": "https://hooks.slack.com/services/T/B/topsecret"})
    assert r.status_code == 200
    g = client.get("/api/notifications/slack").get_json()
    assert "topsecret" not in g["slack"]["webhook_mask"]


def test_slack_test_returns_400_when_not_configured(auth_client):
    client, _ = auth_client
    r = client.post("/api/notifications/slack/test")
    assert r.status_code == 400


def test_slack_test_posts_when_configured(auth_client):
    client, _ = auth_client
    client.put("/api/notifications/slack",
               json={"webhook_url": "https://hooks.slack.com/services/T/B/x"})
    with patch("utils.slack_notifier.post_test_message") as posted:
        r = client.post("/api/notifications/slack/test")
    assert r.status_code == 200
    posted.assert_called_once()


def test_schedules_endpoints_require_auth(anonymous_client):
    assert anonymous_client.get("/api/schedules").status_code == 401
    assert anonymous_client.post("/api/schedules", json={}).status_code == 401


def test_schedule_create_rejects_bad_expression(auth_client, app_module):
    client, uid = auth_client
    from utils.models import TestSession
    # Need a real session so the validity check passes
    sid = "sch-" + uuid.uuid4().hex[:8]
    app_module.memory_agent.save_session(
        TestSession(session_id=sid, user_id=uid, feature="x",
                    state="GENERATED", timestamp=time.time(), test_cases=[]),
        user_id=uid,
    )
    r = client.post("/api/schedules", json={"session_id": sid, "expression": "garbage"})
    assert r.status_code == 400


def test_schedule_create_404_for_missing_session(auth_client):
    client, _ = auth_client
    r = client.post("/api/schedules",
                    json={"session_id": "does-not-exist", "expression": "every 1h"})
    assert r.status_code == 404


def test_schedule_create_404_when_session_belongs_to_other_user(auth_client, app_module):
    client, uid = auth_client
    from utils.models import TestSession
    sid = "sch-" + uuid.uuid4().hex[:8]
    other_uid = uid + 5000
    app_module.memory_agent.save_session(
        TestSession(session_id=sid, user_id=other_uid, feature="x",
                    state="GENERATED", timestamp=time.time(), test_cases=[]),
        user_id=other_uid,
    )
    r = client.post("/api/schedules",
                    json={"session_id": sid, "expression": "every 1h"})
    assert r.status_code == 404


def test_schedule_lifecycle(auth_client, app_module):
    client, uid = auth_client
    from utils.models import TestSession
    sid = "sch-" + uuid.uuid4().hex[:8]
    app_module.memory_agent.save_session(
        TestSession(session_id=sid, user_id=uid, feature="x",
                    state="GENERATED", timestamp=time.time(), test_cases=[]),
        user_id=uid,
    )

    r = client.post("/api/schedules",
                    json={"session_id": sid, "expression": "every 6h"})
    assert r.status_code == 200
    body = r.get_json()
    schedule_id = body["schedule"]["id"]
    assert body["schedule"]["enabled"] is True
    assert "6 hours" in body["human"]

    # Toggle off
    r = client.put(f"/api/schedules/{schedule_id}/toggle", json={"enabled": False})
    assert r.status_code == 200
    assert r.get_json()["schedule"]["enabled"] is False

    # List
    rows = client.get("/api/schedules").get_json()["schedules"]
    assert any(s["id"] == schedule_id for s in rows)

    # Delete
    r = client.delete(f"/api/schedules/{schedule_id}")
    assert r.status_code == 200
    assert client.delete(f"/api/schedules/{schedule_id}").status_code == 404


def test_schedule_toggle_cross_user_404(auth_client, app_module):
    """A user cannot toggle another user's schedule."""
    client, uid = auth_client
    other_uid = uid + 1000
    other_sched = app_module.memory_agent.db.upsert_schedule(
        other_uid, "their-session", "every 1h", time.time() + 3600,
    )
    r = client.put(f"/api/schedules/{other_sched}/toggle", json={"enabled": False})
    assert r.status_code == 404
