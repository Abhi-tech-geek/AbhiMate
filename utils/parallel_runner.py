"""Parallel execution helpers for Feature #8.

The sequential executor in :mod:`agents.automation_executor_agent` runs N
cases in one Chrome process. With a 10-case suite where each case takes
6 s, that's a full minute of wall time.

This module fans out across W workers — each worker owns its own
``BrowserPort`` and processes a subset of the case list. The main thread
reads a shared queue and yields events in order of arrival.

Trade-offs we deliberately make
-------------------------------
* **No worker pool reuse** — each call to :func:`run_parallel` spins up
  fresh ports and tears them down. Simpler to reason about than a
  persistent pool, and Chrome's cold-start (~1 s) is small compared to
  the per-case cost it offsets.
* **No browser sharing** — every worker has its own context. Avoids the
  cookie / localStorage cross-pollination headaches that come with one
  Chrome handling concurrent tabs.
* **Forced headless** — opening 4 visible Chromes at once is chaotic.
  Workers >1 always run headless regardless of the global setting.
* **Round-robin split** — keeps category diversity in each worker so a
  positive/negative/security mix doesn't end up all on one worker.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from typing import Callable, Iterable, Iterator, List, Optional

from utils.models import TestCase


def split_round_robin(items: List[TestCase], workers: int) -> List[List[TestCase]]:
    """Distribute ``items`` across ``workers`` bins, item-index modulo W.

    Why round-robin and not contiguous chunks? If the suite is sorted by
    category, contiguous chunks would put all Positive tests on worker 0
    and all Security on worker 3 — uneven load if security tests are
    slower. Round-robin keeps the mix flat.

    If ``workers`` exceeds ``len(items)`` we trim it back so we don't
    spin up empty workers.
    """
    if not items:
        return []
    n = max(1, min(int(workers or 1), len(items)))
    chunks: List[List[TestCase]] = [[] for _ in range(n)]
    for i, tc in enumerate(items):
        chunks[i % n].append(tc)
    return chunks


def run_parallel(
    chunks: List[List[TestCase]],
    *,
    worker_fn: Callable,
    cancel_event: Optional[threading.Event] = None,
    queue_timeout: float = 0.5,
) -> Iterator[dict]:
    """Spawn one thread per chunk, yield events as they arrive.

    ``worker_fn`` is invoked as ``worker_fn(worker_id, chunk, event_q, cancel_event)``
    and is expected to push event dicts into ``event_q``. The worker
    MUST push a sentinel ``{"type": "worker_done", "worker_id": id}``
    when it's about to exit so the main loop knows to stop waiting.

    The queue-based design decouples worker speed from yield speed —
    a fast worker can post 10 events while a slow worker is mid-test.
    """
    event_q: "queue.Queue[dict]" = queue.Queue()
    threads: List[threading.Thread] = []

    for worker_id, chunk in enumerate(chunks):
        t = threading.Thread(
            target=_worker_wrapper,
            args=(worker_id, chunk, event_q, cancel_event, worker_fn),
            name=f"abhimate-worker-{worker_id}",
            daemon=True,
        )
        threads.append(t)
        t.start()

    remaining_workers = len(chunks)
    while remaining_workers > 0:
        try:
            evt = event_q.get(timeout=queue_timeout)
        except queue.Empty:
            # Heartbeat tick — let the caller check cancel_event etc.
            if cancel_event is not None and cancel_event.is_set():
                # Workers honour cancel_event themselves; just keep draining
                # until they emit worker_done.
                pass
            continue
        if evt.get("type") == "worker_done":
            remaining_workers -= 1
            continue
        yield evt

    for t in threads:
        t.join(timeout=1.0)


def _worker_wrapper(
    worker_id: int,
    chunk: List[TestCase],
    event_q: "queue.Queue[dict]",
    cancel_event: Optional[threading.Event],
    worker_fn: Callable,
) -> None:
    """Outer try/except so a worker crash can't silently hang the main thread.

    If ``worker_fn`` raises before emitting ``worker_done`` itself, we
    emit one here with the error attached. The main loop counts it as a
    completed worker and the run moves on.
    """
    try:
        worker_fn(worker_id, chunk, event_q, cancel_event)
    except Exception as e:                              # noqa: BLE001
        event_q.put({
            "type": "worker_error",
            "worker_id": worker_id,
            "error": f"{type(e).__name__}: {e}",
        })
    finally:
        event_q.put({"type": "worker_done", "worker_id": worker_id})


# ---------------------------------------------------------------------
# Convenience: aggregate per-worker metrics into one ExecutionMetrics
# ---------------------------------------------------------------------

def metrics_delta_for(status: str) -> str:
    """Map a TestCase status to which metric bucket it belongs in.

    Returns one of ``"passed"`` / ``"failed"`` / ``"skipped"`` /
    ``"flaky"``. Unknown statuses default to ``"skipped"`` so they don't
    distort the pass-rate.
    """
    if status == "Pass":
        return "passed"
    if status in ("Fail",):
        return "failed"
    if status == "Flaky":
        return "flaky"
    return "skipped"
