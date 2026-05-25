"""Self-healing locator layer (Feature #9).

Goal: when a fallback selector saves a test, **remember which one worked**
and try it first next time. The original primary is kept as a fallback in
case the DOM shifts again.

Design points
-------------
* Cache is keyed by (host, primary_by, primary_value). Host scoping prevents
  localhost vs prod from polluting each other.
* Cache is **global**, not per-user — the winning selector is a property of
  the page DOM, not the person running the test.
* Graceful degrade: any DB error returns "no cache". Tests without a DB just
  see no-op behavior; existing 198 tests stay green.
* Only **fallback wins** are recorded. If the primary already worked, there's
  nothing to learn.
"""

from __future__ import annotations

from typing import Optional, Tuple
from urllib.parse import urlparse

from utils.models import Locator


def host_from_url(url: str) -> str:
    """Pull a stable bucket key from a URL. 'https://x.com/login' -> 'x.com'."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return (parsed.hostname or "").lower()
    except Exception:
        return ""


def parse_used_strategy(used: str) -> Optional[Tuple[str, str]]:
    """Convert 'id=email' (port.find return shape) into ('id', 'email').
    Returns None for unparseable input.
    """
    if not isinstance(used, str) or "=" not in used:
        return None
    by, value = used.split("=", 1)
    return by.strip(), value


def enhance_locator(locator: Locator, host: str, db) -> Locator:
    """Prepend a cached winning locator to the front of the fallback chain.

    If the cache has a record of what worked last time for this host +
    primary, we make that the new primary. The original primary (and its
    fallbacks) follow — so a fresh DOM still resolves even if the cached
    winner is now stale.
    """
    if not host or db is None:
        return locator
    try:
        cached = db.lookup_locator(host, locator.by, locator.value)
    except Exception:
        return locator
    if not cached:
        return locator

    # If the cached winner IS the primary already, nothing to enhance.
    if cached["winning_by"] == locator.by and cached["winning_value"] == locator.value:
        return locator

    # Build: [cached winner] -> [original primary] -> [original fallbacks]
    new_fallbacks = [
        Locator(by=locator.by, value=locator.value),
        *list(locator.fallbacks or []),
    ]
    return Locator(
        by=cached["winning_by"],
        value=cached["winning_value"],
        fallbacks=new_fallbacks,
    )


def record_winning(
    original: Locator,
    used: str,
    host: str,
    db,
) -> None:
    """Persist the strategy that actually worked, if it differs from the
    original primary. No-op on errors so the test run isn't disrupted."""
    if not host or db is None:
        return
    parsed = parse_used_strategy(used)
    if parsed is None:
        return
    winning_by, winning_value = parsed

    # Only record fallback wins. If the primary worked, there's nothing to learn.
    if winning_by == original.by and winning_value == original.value:
        return

    try:
        db.record_locator(host, original.by, original.value, winning_by, winning_value)
    except Exception:
        # Stay invisible — caching is best-effort, never breaks a test.
        pass
