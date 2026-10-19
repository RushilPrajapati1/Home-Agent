"""Injectable time. Every service takes a ``Clock``; nothing calls ``date.today()`` directly."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware."""
        ...

    def today(self) -> date:
        """Current calendar date in the clock's timezone."""
        ...


class SystemClock:
    """The real wall clock."""

    def __init__(self, tz: tzinfo = UTC) -> None:
        self._tz = tz

    def now(self) -> datetime:
        return datetime.now(self._tz)

    def today(self) -> date:
        return self.now().date()


class FixedClock:
    """A clock frozen at one instant; ``advance`` moves it forward for tests."""

    def __init__(self, at: datetime | date, tz: tzinfo = UTC) -> None:
        if isinstance(at, datetime):
            self._now = at if at.tzinfo is not None else at.replace(tzinfo=tz)
        else:
            self._now = datetime.combine(at, time(12, 0), tzinfo=tz)

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.date()

    def advance(self, delta: timedelta) -> None:
        self._now += delta


CLOCK_ENV_VAR = "CLOCK_FIXED_DATE"


def clock_from_env(env: Mapping[str, str] | None = None) -> Clock:
    """``FixedClock`` when ``CLOCK_FIXED_DATE=YYYY-MM-DD`` is set (demos, evals), else system."""
    source = os.environ if env is None else env
    fixed = source.get(CLOCK_ENV_VAR, "").strip()
    if fixed:
        return FixedClock(date.fromisoformat(fixed))
    return SystemClock()
