"""Feature #8 - Parallel test execution.

Four layers covered:
1. Round-robin splitter (load distribution, edge cases)
2. ``run_parallel`` runner (event ordering, worker isolation, error capture)
3. AutomationExecutorAgent.execute_streaming with workers>1 (end-to-end fan-out)
4. /api/execute_stream POST body honours ``workers``
"""

from __future__ import annotations

import threading
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

from utils.models import TestCase, Action


def _make_tc(_id="TC001", op_url="https://example.test/"):
    return TestCase(
        id=_id, type="Positive", description=f"case {_id}",
        steps=["go"], expected="ok",
        action_plan=[Action(op="goto", url=op_url)],
    )


# ======================================================================
# 1. Splitter
# ======================================================================

def test_split_round_robin_distributes_evenly():
    from utils.parallel_runner import split_round_robin
    items = [_make_tc(f"TC{i:03d}") for i in range(8)]
    chunks = split_round_robin(items, 4)
    assert len(chunks) == 4
    assert all(len(c) == 2 for c in chunks)
    # Round-robin: index 0,4 on worker 0; 1,5 on worker 1; etc.
    assert chunks[0][0].id == "TC000" and chunks[0][1].id == "TC004"
    assert chunks[3][0].id == "TC003" and chunks[3][1].id == "TC007"


def test_split_round_robin_handles_uneven_division():
    from utils.parallel_runner import split_round_robin
    items = [_make_tc(f"TC{i}") for i in range(7)]
    chunks = split_round_robin(items, 3)
    # 7 items, 3 workers -> 3, 2, 2
    sizes = sorted(len(c) for c in chunks)
    assert sizes == [2, 2, 3]


def test_split_round_robin_trims_excess_workers():
    """Asking for 8 workers on a 3-item list spins up 3 - not 8 idle workers."""
    from utils.parallel_runner import split_round_robin
    items = [_make_tc("a"), _make_tc("b"), _make_tc("c")]
    chunks = split_round_robin(items, 8)
    assert len(chunks) == 3


def test_split_round_robin_empty_input():
    from utils.parallel_runner import split_round_robin
    assert split_round_robin([], 4) == []


# ======================================================================
# 2. run_parallel event aggregation
# ======================================================================

def test_run_parallel_collects_events_from_all_workers():
    from utils.parallel_runner import run_parallel

    def worker_fn(worker_id, chunk, event_q, cancel_event):
        for tc in chunk:
            event_q.put({"type": "case_done", "worker_id": worker_id, "id": tc.id})

    items = [_make_tc(f"TC{i}") for i in range(6)]
    chunks = [items[:3], items[3:]]
    events = list(run_parallel(chunks, worker_fn=worker_fn))
    case_dones = [e for e in events if e["type"] == "case_done"]
    assert len(case_dones) == 6
    worker_ids = {e["worker_id"] for e in case_dones}
    assert worker_ids == {0, 1}


def test_run_parallel_emits_worker_error_when_worker_crashes():
    """If a worker raises before emitting, the wrapper still posts an error
    + worker_done so the main loop doesn't hang."""
    from utils.parallel_runner import run_parallel

    def worker_fn(worker_id, chunk, event_q, cancel_event):
        if worker_id == 1:
            raise RuntimeError("worker 1 exploded")
        for tc in chunk:
            event_q.put({"type": "case_done", "worker_id": worker_id, "id": tc.id})

    chunks = [[_make_tc("ok1")], [_make_tc("dead")]]
    events = list(run_parallel(chunks, worker_fn=worker_fn))
    errs = [e for e in events if e["type"] == "worker_error"]
    assert len(errs) == 1 and "exploded" in errs[0]["error"]
    assert any(e["type"] == "case_done" and e["worker_id"] == 0 for e in events)


def test_run_parallel_isolates_workers_one_slow_one_fast():
    """A slow worker must not block events from a fast worker."""
    from utils.parallel_runner import run_parallel

    sequence: list = []

    def worker_fn(worker_id, chunk, event_q, cancel_event):
        if worker_id == 1:
            time.sleep(0.15)
        for tc in chunk:
            event_q.put({"type": "case_done", "worker_id": worker_id, "id": tc.id})

    chunks = [[_make_tc("fast1"), _make_tc("fast2")], [_make_tc("slow1")]]
    for evt in run_parallel(chunks, worker_fn=worker_fn):
        if evt["type"] == "case_done":
            sequence.append((evt["worker_id"], evt["id"]))
    assert sequence[0][0] == 0
    assert "slow1" in [s[1] for s in sequence]


def test_run_parallel_honours_cancel_event_drains_workers():
    """When cancel is set, workers see it and bow out cleanly."""
    from utils.parallel_runner import run_parallel

    cancel = threading.Event()

    def worker_fn(worker_id, chunk, event_q, cancel_event):
        for tc in chunk:
            if cancel_event.is_set():
                event_q.put({"type": "cancelled", "worker_id": worker_id})
                return
            time.sleep(0.02)
            event_q.put({"type": "case_done", "worker_id": worker_id, "id": tc.id})

    chunks = [[_make_tc(f"x{i}") for i in range(5)],
              [_make_tc(f"y{i}") for i in range(5)]]
    cancel.set()
    events = list(run_parallel(chunks, worker_fn=worker_fn, cancel_event=cancel))
    assert not any(e["type"] == "case_done" for e in events)


# ======================================================================
# 3. Executor agent end-to-end with stubbed worker
# ======================================================================

def _stub_executor_internals(monkeypatch, agent_module):
    """Common monkey-patching so tests don't spin up real Chrome."""
    fake_port = MagicMock()
    fake_port.drain_console_logs = MagicMock(return_value=[])
    fake_port.quit = MagicMock()
    monkeypatch.setattr(agent_module, "_build_port_and_ctx",
                        lambda *a, **k: (fake_port, MagicMock(visual_artifacts=[])))

    def stub_one_case(tc, **kw):
        tc.status = "Pass"
        tc.error = None
        return time.time(), []

    monkeypatch.setattr(agent_module, "_execute_one_case", stub_one_case)
    monkeypatch.setattr(agent_module, "_write_trace", lambda *a, **k: "trace.json")
    return fake_port


def test_streaming_workers_one_uses_sequential_path(monkeypatch):
    """workers=1 must not hit the parallel path."""
    from agents import automation_executor_agent as mod
    called = {"parallel": 0}

    def fake_parallel(self, *a, **kw):
        called["parallel"] += 1
        yield {"type": "done",
               "metrics": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
               "test_cases": []}

    _stub_executor_internals(monkeypatch, mod)
    monkeypatch.setattr(mod.AutomationExecutorAgent, "_execute_parallel", fake_parallel)

    agent = mod.AutomationExecutorAgent()
    events = list(agent.execute_streaming([_make_tc("x")], "sess1", workers=1))
    assert called["parallel"] == 0
    assert any(e["type"] == "case_done" for e in events)


def test_streaming_workers_n_fans_out(monkeypatch):
    """workers=3 over 6 cases must produce 6 case_done events with worker_ids."""
    from agents import automation_executor_agent as mod
    _stub_executor_internals(monkeypatch, mod)

    agent = mod.AutomationExecutorAgent()
    cases = [_make_tc(f"TC{i:03d}") for i in range(6)]
    events = list(agent.execute_streaming(cases, "sess1", workers=3))
    starts = [e for e in events if e["type"] == "case_start"]
    dones = [e for e in events if e["type"] == "case_done"]
    final = [e for e in events if e["type"] == "done"][0]

    assert len(starts) == 6 and len(dones) == 6
    assert all("worker_id" in e for e in starts + dones)
    assert {e["worker_id"] for e in dones} == {0, 1, 2}
    assert final["metrics"]["total"] == 6
    assert final["metrics"]["passed"] == 6
    assert final["metrics"]["failed"] == 0


def test_streaming_parallel_start_event_announces_workers(monkeypatch):
    from agents import automation_executor_agent as mod
    _stub_executor_internals(monkeypatch, mod)

    agent = mod.AutomationExecutorAgent()
    events = list(agent.execute_streaming(
        [_make_tc(f"TC{i}") for i in range(4)], "sess1", workers=2,
    ))
    start = [e for e in events if e["type"] == "start"][0]
    assert start["workers"] == 2
    assert start.get("parallel") is True


def test_streaming_clamps_workers_to_case_count(monkeypatch):
    """Asking for 99 workers gets clamped first to MAX_WORKERS=8, then to
    case-count (4 here)."""
    from agents import automation_executor_agent as mod
    _stub_executor_internals(monkeypatch, mod)

    agent = mod.AutomationExecutorAgent()
    events = list(agent.execute_streaming(
        [_make_tc(f"TC{i}") for i in range(4)], "sess1", workers=99,
    ))
    start = [e for e in events if e["type"] == "start"][0]
    assert start["workers"] == 4


def test_metric_delta_helper_buckets_correctly():
    from agents.automation_executor_agent import _apply_metric_delta
    from utils.models import ExecutionMetrics
    m = ExecutionMetrics(total=4)
    _apply_metric_delta(m, "Pass")
    _apply_metric_delta(m, "Flaky")     # flaky counts as passed
    _apply_metric_delta(m, "Fail")
    _apply_metric_delta(m, "Skipped")
    assert m.passed == 2 and m.failed == 1 and m.skipped == 1


# ======================================================================
# 4. Flask endpoint accepts ``workers``
# ======================================================================

def _seed_session(app_module, uid, sid):
    from utils.models import TestSession
    app_module.memory_agent.save_session(
        TestSession(session_id=sid, user_id=uid, feature="x",
                    state="GENERATED", timestamp=time.time(),
                    test_cases=[_make_tc("TC001")]),
        user_id=uid,
    )


def _make_streamer(captured: dict):
    """Build a fake execute_streaming that records the kwargs it received.

    The Flask test client iterates the streaming response synchronously, so
    by the time ``client.post(...)`` returns, the generator body has run
    and ``captured`` is populated. Avoids the "factory.attr never set"
    trap from the previous attempt.
    """
    def _gen(test_cases, session_id, **kwargs):
        captured.update(kwargs)
        yield {"type": "done",
               "metrics": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
               "test_cases": [_make_tc("TC001").model_dump()]}
    return _gen


def test_endpoint_passes_workers(auth_client, app_module):
    """POST workers=4 should reach the executor as workers=4."""
    client, uid = auth_client
    sid = "par-" + uuid.uuid4().hex[:8]
    _seed_session(app_module, uid, sid)
    captured: dict = {}
    with patch.object(app_module.executor_agent, "execute_streaming",
                      side_effect=_make_streamer(captured)):
        resp = client.post(f"/api/execute_stream/{sid}",
                           json={"environment": "web", "workers": 4})
        resp.get_data()  # force the streaming body to materialise
    assert resp.status_code == 200
    assert captured.get("workers") == 4


def test_endpoint_defaults_to_one_worker(auth_client, app_module):
    client, uid = auth_client
    sid = "par-" + uuid.uuid4().hex[:8]
    _seed_session(app_module, uid, sid)
    captured: dict = {}
    with patch.object(app_module.executor_agent, "execute_streaming",
                      side_effect=_make_streamer(captured)):
        resp = client.post(f"/api/execute_stream/{sid}", json={})
        resp.get_data()
    assert captured.get("workers") == 1


def test_endpoint_rejects_nonsense_workers(auth_client, app_module):
    client, uid = auth_client
    sid = "par-" + uuid.uuid4().hex[:8]
    _seed_session(app_module, uid, sid)
    captured: dict = {}
    with patch.object(app_module.executor_agent, "execute_streaming",
                      side_effect=_make_streamer(captured)):
        resp = client.post(f"/api/execute_stream/{sid}", json={"workers": "garbage"})
        resp.get_data()
    # Garbage falls back to 1 - never crashes the endpoint
    assert captured.get("workers") == 1
