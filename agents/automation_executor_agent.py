from utils.models import TestCase, ExecutionMetrics
from utils.automation_drivers import WebSeleniumDriver
from utils.safe_exec import safe_run, SandboxViolation
from utils.gherkin import expand_examples
from utils.action_engine import (
    execute_plan, ActionContext, used_flaky_retry,
)
from utils.parallel_runner import split_round_robin, run_parallel
from typing import List, Tuple, Iterator, Optional
import os
import json
import queue
import threading
import time

PER_TEST_TIMEOUT_SECONDS = 30.0
MAX_WORKERS = 8                # safety cap so users can't request 100 Chromes


def _drain_browser_logs(driver) -> list:
    """Pull buffered console logs from Chrome (best-effort, may be unavailable)."""
    try:
        return driver.get_log("browser")
    except Exception:
        return []


def _write_trace(session_id: str, tc: TestCase, started_at: float, ended_at: float, logs: list) -> str:
    out_dir = f"data/traces/{session_id}"
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{tc.id}.json")
    payload = {
        "id": tc.id,
        "status": tc.status,
        "duration_ms": int((ended_at - started_at) * 1000),
        "started_at": started_at,
        "engine": "action_plan" if tc.action_plan else "legacy",
        "action_results": [r.model_dump() for r in (tc.action_results or [])],
        "console_logs": logs,
        "error": tc.error,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def _apply_metric_delta(metrics: ExecutionMetrics, status: Optional[str]) -> None:
    """Bump the right metric bucket for ``status``.

    Used by both the sequential and parallel paths so the final
    ``ExecutionMetrics`` is computed identically regardless of fan-out.
    Unknown statuses fall through to ``skipped`` so they don't inflate
    pass-rate.
    """
    if status == "Pass" or status == "Flaky":
        metrics.passed += 1
    elif status == "Fail":
        metrics.failed += 1
    else:
        metrics.skipped += 1


def _build_port_and_ctx(
    backend: str,
    *,
    user_id: Optional[int],
    session_id: str,
    device: Optional[str],
    force_headless: bool = False,
):
    """Spin up a fresh ``BrowserPort`` + ``ActionContext`` for one execution lane.

    Used by both the sequential and the parallel paths so they share the
    same device-emulation + locator-DB wiring. ``force_headless`` flips
    the env var Chrome consults so parallel workers don't paint multiple
    visible windows on top of each other.
    """
    from utils.engines import build_port
    if force_headless:
        os.environ["ABHIMATE_HEADLESS"] = "1"
    port = build_port(backend)
    port.start()

    # Optional device emulation: per-run argument wins, env fallback otherwise.
    try:
        from config import settings
        from utils.engines.devices import get_device
        effective = device or getattr(settings, "DEVICE", "Desktop")
        if effective and effective != "Desktop":
            preset = get_device(effective)
            if preset and hasattr(port, "emulate_device"):
                port.emulate_device(preset)
    except Exception:
        pass

    try:
        from database.db_core import SQLiteDB
        locator_db = SQLiteDB()
    except Exception:
        locator_db = None

    action_ctx = ActionContext(
        driver=getattr(port, "driver", None),
        port=port,
        locator_db=locator_db,
        user_id=user_id,
        session_id=session_id,
    )
    return port, action_ctx


def _execute_one_case(
    tc: TestCase,
    *,
    port,
    action_ctx: ActionContext,
    session_id: str,
    out_dir: str,
) -> Tuple[float, list]:
    """Run a single TestCase and stamp ``tc`` with status/error/screenshot.

    Returns ``(started_at, console_logs)`` so the caller can write a trace.
    Never raises — exceptions are translated into ``tc.status`` + ``tc.error``.
    """
    started_at = time.time()
    if not tc.action_plan and not tc.selenium_action:
        tc.status = "Skipped"
        tc.error = "No executable action provided."
        return started_at, []

    # Selenium legacy snippets need the raw driver context; action_plan path
    # just uses the BrowserPort.
    if port and hasattr(port, "_driver_wrap") and port._driver_wrap is not None:
        driver_instance = port._driver_wrap
        context = driver_instance.get_context()
    else:
        driver_instance = port
        context = {}

    try:
        _run_case(tc, driver_instance, context, action_ctx)
        if tc.status != "Flaky":
            tc.status = "Pass"
        tc.error = None
    except SandboxViolation as e:
        tc.status = "Blocked"
        tc.error = f"SandboxViolation: {e}"
    except TimeoutError as e:
        tc.status = "Fail"
        tc.error = f"Timeout: {e}"
        _capture_failure_screenshot(tc, port, out_dir)
    except Exception as e:                              # noqa: BLE001
        tc.status = "Fail"
        tc.error = f"{type(e).__name__}: {str(e)}"
        _capture_failure_screenshot(tc, port, out_dir)

    try:
        console_logs = port.drain_console_logs()
    except Exception:
        console_logs = []
    return started_at, console_logs


def _capture_failure_screenshot(tc: TestCase, port, out_dir: str) -> None:
    """Best-effort failure screenshot — never raises."""
    ss_path = os.path.join(out_dir, f"failure_{tc.id}.png")
    try:
        port.screenshot(ss_path)
        tc.screenshot = ss_path
    except Exception:
        pass


def _run_case(tc: TestCase, driver_instance, context: dict, ctx: ActionContext) -> None:
    """Pick the execution path based on the case payload.

    Preference order:
      1. ``action_plan`` (Phase A engine-agnostic plan) — safest, structured.
      2. ``selenium_action`` (Phase 0 legacy snippet) — sandboxed exec.
    """
    if tc.action_plan:
        ctx.console_logs = []  # reset per case
        ctx.visual_artifacts = []  # per-case reset so artifacts don't leak across runs
        try:
            results = execute_plan(tc.action_plan, ctx)
            tc.action_results = results
            if used_flaky_retry(results):
                tc.status = "Flaky"
        finally:
            # Surface visual artifacts even when the case fails — the UI
            # needs the diff PNG path on the failure card.
            if ctx.visual_artifacts:
                tc.visual_artifacts = list(ctx.visual_artifacts)
        return
    if tc.selenium_action:
        safe_run(tc.selenium_action, context, timeout_seconds=PER_TEST_TIMEOUT_SECONDS)
        return
    raise RuntimeError("No action_plan or selenium_action to execute")


class AutomationExecutorAgent:
    def __init__(self, mode="web"):
        self.mode = mode

    # ------------------------------------------------------------------
    # Streaming entry point — yields lifecycle events for SSE.
    #
    # Yielded shapes:
    #   {"type": "start", "total": N}
    #   {"type": "case_start", "index": i, "id": ..., "description": ...}
    #   {"type": "case_done", "index": i, "id": ..., "status": ..., "error": ..., "screenshot": ...}
    #   {"type": "cancelled", "remaining": k}
    #   {"type": "done", "metrics": {...}, "test_cases": [...]}
    # ------------------------------------------------------------------
    def execute_streaming(
        self,
        test_cases: List[TestCase],
        session_id: str,
        cancel_event: Optional[threading.Event] = None,
        device: Optional[str] = None,
        user_id: Optional[int] = None,
        workers: int = 1,
    ) -> Iterator[dict]:
        # Expand Scenario-Outline rows, then drop user-skipped cases.
        expanded: List[TestCase] = []
        for tc in test_cases:
            if getattr(tc, "user_skipped", False):
                continue
            expanded.extend(expand_examples(tc))
        runnable = expanded

        metrics = ExecutionMetrics(total=len(runnable))

        if self.mode != "web":
            yield {"type": "error", "message": "Only 'web' mode is implemented."}
            return

        # Pick the BrowserPort — Selenium (default) or Playwright if configured.
        try:
            from config import settings
            backend = getattr(settings, "BACKEND", "selenium")
        except Exception:
            backend = "selenium"

        # Clamp the worker count: 1 = legacy sequential path, >1 = fan-out.
        try:
            workers = max(1, min(int(workers or 1), MAX_WORKERS))
        except (TypeError, ValueError):
            workers = 1
        effective_workers = min(workers, max(1, len(runnable)))

        out_dir = f"data/screenshots/{session_id}"
        os.makedirs(out_dir, exist_ok=True)

        if effective_workers > 1:
            yield from self._execute_parallel(
                runnable, session_id=session_id, backend=backend,
                device=device, user_id=user_id, workers=effective_workers,
                cancel_event=cancel_event, metrics=metrics, out_dir=out_dir,
            )
            return

        # ---- Sequential path (legacy default) ---------------------------
        port, action_ctx = _build_port_and_ctx(
            backend, user_id=user_id, session_id=session_id, device=device,
        )

        yield {"type": "start", "total": metrics.total, "backend": backend,
               "workers": 1}

        try:
            for i, tc in enumerate(runnable):
                if cancel_event is not None and cancel_event.is_set():
                    yield {"type": "cancelled", "remaining": len(runnable) - i}
                    break

                yield {
                    "type": "case_start",
                    "index": i,
                    "id": tc.id,
                    "description": tc.description,
                    "engine": "action_plan" if tc.action_plan else "legacy",
                }

                started_at, logs = _execute_one_case(
                    tc, port=port, action_ctx=action_ctx,
                    session_id=session_id, out_dir=out_dir,
                )
                tc.trace_path = _write_trace(session_id, tc, started_at, time.time(), logs)
                _apply_metric_delta(metrics, tc.status)

                yield {
                    "type": "case_done",
                    "index": i,
                    "id": tc.id,
                    "status": tc.status,
                    "error": tc.error,
                    "screenshot": tc.screenshot,
                    "action_results": [r.model_dump() for r in (tc.action_results or [])],
                }
        finally:
            try: port.quit()
            except Exception: pass

        yield {
            "type": "done",
            "metrics": metrics.model_dump(),
            "test_cases": [tc.model_dump() for tc in runnable],
        }

    # ------------------------------------------------------------------
    # Parallel path (Feature #8)
    # ------------------------------------------------------------------

    def _execute_parallel(
        self,
        runnable: List[TestCase],
        *,
        session_id: str,
        backend: str,
        device: Optional[str],
        user_id: Optional[int],
        workers: int,
        cancel_event: Optional[threading.Event],
        metrics: ExecutionMetrics,
        out_dir: str,
    ) -> Iterator[dict]:
        """Fan ``runnable`` out across ``workers`` Chrome instances.

        Each worker drains its slice independently, posting events into
        a queue. The main thread yields events in arrival order — that
        gives the UI a smooth interleaved progress feed.
        """
        chunks = split_round_robin(runnable, workers)
        # Map tc.id -> tc so the workers' status flips are visible from here
        # (workers operate on the same TestCase objects we yield at the end).
        by_id = {tc.id: tc for tc in runnable}

        yield {"type": "start", "total": metrics.total, "backend": backend,
               "workers": len(chunks), "parallel": True}

        def worker_fn(worker_id: int, chunk: List[TestCase],
                      event_q, w_cancel: Optional[threading.Event]) -> None:
            # Force headless so we don't paint a dozen visible Chromes.
            port, action_ctx = _build_port_and_ctx(
                backend, user_id=user_id, session_id=session_id,
                device=device, force_headless=True,
            )
            try:
                for tc in chunk:
                    if w_cancel is not None and w_cancel.is_set():
                        event_q.put({"type": "cancelled",
                                     "worker_id": worker_id})
                        return
                    event_q.put({
                        "type": "case_start",
                        "worker_id": worker_id,
                        "id": tc.id,
                        "description": tc.description,
                        "engine": "action_plan" if tc.action_plan else "legacy",
                    })
                    started_at, logs = _execute_one_case(
                        tc, port=port, action_ctx=action_ctx,
                        session_id=session_id, out_dir=out_dir,
                    )
                    tc.trace_path = _write_trace(
                        session_id, tc, started_at, time.time(), logs,
                    )
                    event_q.put({
                        "type": "case_done",
                        "worker_id": worker_id,
                        "id": tc.id,
                        "status": tc.status,
                        "error": tc.error,
                        "screenshot": tc.screenshot,
                        "action_results": [r.model_dump() for r in (tc.action_results or [])],
                    })
            finally:
                try: port.quit()
                except Exception: pass

        # Aggregate events; update metrics on case_done so the final 'done'
        # has authoritative counts even when workers finish out of order.
        for evt in run_parallel(chunks, worker_fn=worker_fn,
                                cancel_event=cancel_event):
            if evt.get("type") == "case_done":
                _apply_metric_delta(metrics, evt.get("status"))
            yield evt

        yield {
            "type": "done",
            "metrics": metrics.model_dump(),
            "test_cases": [tc.model_dump() for tc in runnable],
        }

    # ------------------------------------------------------------------
    # Original synchronous entry — preserved for direct/legacy callers.
    # ------------------------------------------------------------------
    def execute(
        self,
        test_cases: List[TestCase],
        session_id: str,
        device: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Tuple[List[TestCase], ExecutionMetrics]:
        """Synchronous run used by /api/execute and the auto-run pipeline.

        Routes through the same Action Plan engine as ``execute_streaming``
        (via ``_build_port_and_ctx`` + ``_execute_one_case``) so generated
        ``action_plan`` cases actually run instead of being skipped for
        lacking a legacy ``selenium_action`` snippet.
        """
        # Honour user_skipped before Scenario-Outline expansion.
        runnable = [tc for tc in test_cases if not getattr(tc, "user_skipped", False)]

        expanded: List[TestCase] = []
        for tc in runnable:
            expanded.extend(expand_examples(tc))
        test_cases = expanded

        print(f"-> Executing {len(test_cases)} tests in {self.mode} environment...")

        metrics = ExecutionMetrics(total=len(test_cases))

        if self.mode != "web":
            raise NotImplementedError("Android/API not yet implemented.")

        # Same BrowserPort selection as the streaming path.
        try:
            from config import settings
            backend = getattr(settings, "BACKEND", "selenium")
        except Exception:
            backend = "selenium"

        out_dir = f"data/screenshots/{session_id}"
        os.makedirs(out_dir, exist_ok=True)

        port, action_ctx = _build_port_and_ctx(
            backend, user_id=user_id, session_id=session_id, device=device,
        )
        try:
            for tc in test_cases:
                started_at, logs = _execute_one_case(
                    tc, port=port, action_ctx=action_ctx,
                    session_id=session_id, out_dir=out_dir,
                )
                tc.trace_path = _write_trace(session_id, tc, started_at, time.time(), logs)
                _apply_metric_delta(metrics, tc.status)
        finally:
            try: port.quit()
            except Exception: pass

        return test_cases, metrics
