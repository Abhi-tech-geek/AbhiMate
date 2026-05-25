"""Background scheduler for Feature #7.

Single daemon thread that wakes every ``tick_seconds`` and fires any
schedule whose ``next_run_at`` is in the past. Runs are executed
sequentially on the scheduler thread itself — we deliberately avoid a
worker pool here so we never spin up more than one Chrome instance at a
time (the parallel-execution work is Feature #8).

Lifecycle
---------
* :func:`Scheduler.start` is idempotent — calling it twice in the same
  process is a no-op so the Flask reloader can't accidentally launch two
  schedulers.
* :func:`Scheduler.stop` signals the loop and joins. Useful in tests.
* :func:`Scheduler.tick` is the unit the loop calls and what tests poke
  directly — it accepts a ``now`` so the test can drive time without
  monkey-patching ``time.time``.

Crash safety
------------
``db.claim_due_schedules`` atomically pushes the row's ``next_run_at``
+3600s before returning it. If this process dies mid-run, the row will
re-fire after at most one hour — never simultaneously while the run is
still in flight.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, List, Optional

log = logging.getLogger(__name__)


class Scheduler:
    """Run any due schedules using the existing executor.

    Parameters
    ----------
    memory_agent
        Provides ``load_session(session_id, user_id=...)``.
    executor_agent
        Provides ``execute_streaming(test_cases, session_id, user_id=...)``.
    db
        SQLite handle exposing ``claim_due_schedules``, ``finalize_schedule_run``
        and ``get_slack_credentials``.
    tick_seconds
        Wall-clock interval between scans. Tests usually pass a small value
        (or ignore the loop entirely and call :meth:`tick` directly).
    session_url_builder
        Optional ``callable(session_id) -> str`` so the Slack message can
        include a deep link. Production wires this to Flask's ``url_for``.
    """

    def __init__(
        self,
        memory_agent,
        executor_agent,
        db,
        *,
        tick_seconds: float = 30.0,
        session_url_builder: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.memory_agent = memory_agent
        self.executor_agent = executor_agent
        self.db = db
        self.tick_seconds = float(tick_seconds)
        self.session_url_builder = session_url_builder
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Spawn the loop. Safe to call multiple times — extra calls are no-ops."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="abhimate-scheduler"
            )
            self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout)

    def _loop(self) -> None:
        log.info("Scheduler thread started (tick=%.1fs)", self.tick_seconds)
        while not self._stop.is_set():
            try:
                self.tick(time.time())
            except Exception:                       # noqa: BLE001
                log.exception("Scheduler tick crashed")
            self._stop.wait(self.tick_seconds)
        log.info("Scheduler thread stopped")

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def tick(self, now: float) -> List[dict]:
        """Single sweep: claim due schedules and fire each. Returns the
        list of dicts that were processed — useful for assertions."""
        due = self.db.claim_due_schedules(now)
        for item in due:
            self._fire(item, now)
        return due

    def _fire(self, item: dict, started_at: float) -> None:
        from utils.schedule_expr import parse, ScheduleExprError

        # Parse first — a broken expression means the row is unusable.
        try:
            sched = parse(item["expression"])
        except ScheduleExprError as e:
            # Push next_run_at far enough out that we don't spin, but keep
            # the row visible so the user can fix the expression.
            self.db.finalize_schedule_run(
                item["id"], started_at + 86400, "broken", str(e)
            )
            return

        # Load the session as the schedule's owning user.
        try:
            session = self.memory_agent.load_session(
                item["session_id"], user_id=item["user_id"]
            )
        except Exception as e:                       # noqa: BLE001
            next_at = sched.next_after(started_at)
            self.db.finalize_schedule_run(
                item["id"], next_at, "missing-session", str(e)[:240]
            )
            return

        metrics: dict = {}
        cases: list = []
        run_error: Optional[str] = None
        try:
            for evt in self.executor_agent.execute_streaming(
                session.test_cases,
                session.session_id,
                user_id=item["user_id"],
            ):
                if evt.get("type") == "done":
                    metrics = evt.get("metrics") or {}
                    cases = evt.get("test_cases") or []
        except Exception as e:                       # noqa: BLE001
            run_error = f"{type(e).__name__}: {e}"

        # Slack notify — best-effort. Failures here annotate the schedule
        # row but never reraise (the run itself already finished).
        slack_error = None
        if item.get("slack_notify"):
            slack_error = self._notify_slack(
                item, session, metrics, cases, run_error
            )

        status = "ok" if not run_error else "error"
        last_error = run_error
        if slack_error:
            last_error = (last_error + " | " if last_error else "") + f"slack: {slack_error}"
        next_at = sched.next_after(time.time())
        self.db.finalize_schedule_run(item["id"], next_at, status, last_error)

    def _notify_slack(
        self,
        item: dict,
        session,
        metrics: dict,
        cases: list,
        run_error: Optional[str],
    ) -> Optional[str]:
        try:
            creds = self.db.get_slack_credentials(item["user_id"])
        except Exception as e:                       # noqa: BLE001
            return f"creds lookup failed: {e}"
        if not creds or not creds.get("webhook_url"):
            return None

        try:
            from utils.slack_notifier import post_run_result, SlackError
        except Exception as e:                       # noqa: BLE001
            return f"notifier import failed: {e}"

        url = None
        if self.session_url_builder:
            try:
                url = self.session_url_builder(session.session_id)
            except Exception:
                url = None

        try:
            post_run_result(
                creds["webhook_url"],
                session_feature=getattr(session, "feature", "") or "",
                session_id=session.session_id,
                metrics=metrics,
                test_cases=cases,
                session_url=url,
                schedule_expr=item.get("expression"),
                mention_on_fail=creds.get("mention_on_fail"),
                error=run_error,
            )
        except SlackError as e:
            return str(e)
        except Exception as e:                       # noqa: BLE001
            return f"unexpected: {e}"
        return None


# ---------------------------------------------------------------------
# Process-level singleton (so reloader + repeated imports stay safe)
# ---------------------------------------------------------------------

_scheduler_singleton: Optional[Scheduler] = None
_singleton_lock = threading.Lock()


def get_or_start_scheduler(
    memory_agent,
    executor_agent,
    db,
    *,
    tick_seconds: float = 30.0,
    session_url_builder: Optional[Callable[[str], str]] = None,
) -> Optional[Scheduler]:
    """Return the running scheduler instance, creating + starting it on first call.

    Returns ``None`` if Flask's reloader is in the *parent* process — there
    we deliberately skip starting since the child will start its own.
    """
    # Flask reloader: parent sets WERKZEUG_RUN_MAIN unset, child sets it to "true".
    # If the parent is the one importing us, defer to the child.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "":
        return None
    global _scheduler_singleton
    with _singleton_lock:
        if _scheduler_singleton is None:
            _scheduler_singleton = Scheduler(
                memory_agent, executor_agent, db,
                tick_seconds=tick_seconds,
                session_url_builder=session_url_builder,
            )
            _scheduler_singleton.start()
    return _scheduler_singleton


def stop_scheduler() -> None:
    """Tests use this to make sure no thread leaks across test cases."""
    global _scheduler_singleton
    with _singleton_lock:
        if _scheduler_singleton is not None:
            _scheduler_singleton.stop()
            _scheduler_singleton = None
