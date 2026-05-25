"""Tiny schedule expression parser for Feature #7.

Supports a deliberately narrow grammar so we can be confident the next-run
math is correct without pulling in a full cron library:

    every 5m            -> every 5 minutes
    every 2h            -> every 2 hours
    every 1d            -> every 24 hours
    daily HH:MM         -> at HH:MM UTC each day

Anything else raises :class:`ScheduleExprError` with a human-readable hint.
The UI surfaces that hint directly so users can correct their input.

Why not full cron?
------------------
* Full cron forces us to ship (or write) a parser, handle DST, weekday
  semantics, and a much bigger edge-case test surface.
* AbhiMate's scheduling use case is "run my smoke suite every 6 hours"
  or "kick this off every morning" — a 4-token grammar covers it.

The parser is pure / stateless: ``parse(expr)`` returns a
:class:`Schedule` whose ``.next_after(t)`` computes the next firing time
in epoch seconds.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass


class ScheduleExprError(ValueError):
    """Raised when a schedule expression can't be parsed."""


# Bound the cadence so a typo like ``every 1s`` doesn't carpet-bomb the
# executor. 1-minute floor matches the scheduler tick interval.
_MIN_INTERVAL_SEC = 60
_MAX_INTERVAL_SEC = 7 * 24 * 60 * 60   # one week

_INTERVAL_RE = re.compile(r"^every\s+(\d+)\s*([smhd])$", re.IGNORECASE)
_DAILY_RE = re.compile(r"^daily\s+(\d{1,2}):(\d{2})$", re.IGNORECASE)

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


@dataclass(frozen=True)
class Schedule:
    """Parsed schedule. Two flavours via ``kind``: ``interval`` or ``daily``.

    ``next_after(t)`` returns epoch seconds for the next firing strictly
    after ``t`` (we add +1 second when ``t`` already matches so we don't
    misfire twice within the same wall-clock second).
    """

    kind: str           # "interval" | "daily"
    seconds: int = 0    # interval flavour
    hour: int = 0       # daily flavour (UTC)
    minute: int = 0     # daily flavour (UTC)

    def next_after(self, t: float) -> float:
        if self.kind == "interval":
            return float(t) + self.seconds
        # daily — anchor in UTC so the test fixture and prod box agree
        now = _dt.datetime.fromtimestamp(float(t), tz=_dt.timezone.utc)
        candidate = now.replace(
            hour=self.hour, minute=self.minute, second=0, microsecond=0,
        )
        if candidate <= now:
            candidate += _dt.timedelta(days=1)
        return candidate.timestamp()

    def humanize(self) -> str:
        if self.kind == "interval":
            return f"every {_humanize_seconds(self.seconds)}"
        return f"daily at {self.hour:02d}:{self.minute:02d} UTC"


def parse(expr: str) -> Schedule:
    """Parse a user-supplied expression. Whitespace-insensitive."""
    if not isinstance(expr, str) or not expr.strip():
        raise ScheduleExprError("schedule expression is required")
    e = expr.strip().lower()

    m = _INTERVAL_RE.match(e)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        seconds = amount * _UNIT_SECONDS[unit]
        if seconds < _MIN_INTERVAL_SEC:
            raise ScheduleExprError(
                f"interval too short: minimum is {_MIN_INTERVAL_SEC // 60} minute"
            )
        if seconds > _MAX_INTERVAL_SEC:
            raise ScheduleExprError("interval too long: maximum is 7 days")
        return Schedule(kind="interval", seconds=seconds)

    m = _DAILY_RE.match(e)
    if m:
        hh = int(m.group(1)); mm = int(m.group(2))
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ScheduleExprError(
                f"daily time out of range: HH must be 00-23, MM 00-59 (got {hh:02d}:{mm:02d})"
            )
        return Schedule(kind="daily", hour=hh, minute=mm)

    raise ScheduleExprError(
        f"can't parse '{expr}'. Try: 'every 30m', 'every 6h', 'every 1d', or 'daily 09:00'"
    )


def _humanize_seconds(s: int) -> str:
    if s % 86400 == 0:
        d = s // 86400
        return f"{d} day" + ("s" if d != 1 else "")
    if s % 3600 == 0:
        h = s // 3600
        return f"{h} hour" + ("s" if h != 1 else "")
    if s % 60 == 0:
        m = s // 60
        return f"{m} minute" + ("s" if m != 1 else "")
    return f"{s} seconds"
