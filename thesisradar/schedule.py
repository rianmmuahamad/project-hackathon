"""The clock: when the next sweep is due, and a thread that waits for it.

Standard library only, like the rest of the agent core — the schedule must work on
a machine with no Hermes installed. `sched` and `zoneinfo` are both in the 3.12
stdlib, so nothing is added to `requirements.txt` for this.

Deliberately quiet: this module never prints. The CLI reports, the server reports,
and a library that writes to stdout from a background thread is a debugging trap.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# How far ahead `due_at` will look for an allowed weekday before giving up.
LOOKAHEAD_DAYS = 8

# How long `stop` waits for the loop to notice the shutdown event.
JOIN_TIMEOUT = 5.0


def parse_when(value: str) -> tuple[int, int]:
    """`HH:MM` -> (hour, minute). Anything else is a configuration error."""
    text = (value or "").strip()
    head, sep, tail = text.partition(":")
    if not sep or not head.isdigit() or not tail.isdigit() or len(tail) != 2:
        raise ValueError(f"not a HH:MM time: {value!r}")
    hour, minute = int(head), int(tail)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"not a HH:MM time: {value!r}")
    return hour, minute


def parse_days(value: str) -> list[int]:
    """`mon,tue,wed` -> [0, 1, 2]. An empty string means every day."""
    names = [part.strip().lower() for part in (value or "").split(",") if part.strip()]
    out: list[int] = []
    for name in names:
        if name not in WEEKDAYS:
            raise ValueError(f"unknown weekday: {name!r}; use mon,tue,...")
        if WEEKDAYS[name] not in out:
            out.append(WEEKDAYS[name])
    return sorted(out)


def due_at(now: datetime, when: str, days: str, *, tz: str = "Asia/Jakarta") -> datetime:
    """The next occurrence of `when` on one of `days`, strictly after `now`.

    Walks forward one day at a time so a candidate is never returned in the past,
    which is what stops a restarted process from firing a sweep it already ran.
    """
    hour, minute = parse_when(when)
    allowed = parse_days(days)
    local = now.astimezone(ZoneInfo(tz))
    for offset in range(LOOKAHEAD_DAYS):
        day = (local + timedelta(days=offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        if allowed and day.weekday() not in allowed:
            continue
        if day > local:
            return day
    # Only reachable when `days` names weekdays that never occur in a full week,
    # which `parse_days` already prevents; a week ahead is the honest answer.
    return (local + timedelta(days=LOOKAHEAD_DAYS)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)


class Scheduler:
    """Runs `run` on a wall-clock schedule in one daemon thread.

    `run` is called with no arguments and its return value is ignored; exceptions
    are handed to `on_error` so a failing sweep is reported instead of silently
    killing the thread. The wait uses an Event, never `time.sleep`, so `stop`
    returns immediately rather than after the next run is due.
    """

    def __init__(self, run: Callable[[], Any], *, when: str = "08:00",
                 days: str = "mon,tue,wed,thu,fri", tz: str = "Asia/Jakarta",
                 on_error: Callable[[Exception], None] | None = None) -> None:
        # Validate up front: a bad `--when` must fail at construction, not at 3am.
        parse_when(when)
        parse_days(days)
        self.run = run
        self.when = when
        self.days = days
        self.tz = tz
        self.on_error = on_error
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        # Planned at construction so a caller can print the next time before
        # starting, and cleared on `stop` so a parked scheduler reports none.
        self._next: datetime | None = due_at(datetime.now(ZoneInfo(tz)).astimezone(),
                                             when, days, tz=tz)

    # -- reading -----------------------------------------------------------
    def next_run(self) -> datetime | None:
        with self._lock:
            return self._next

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _plan_next(self) -> datetime:
        with self._lock:
            self._next = due_at(datetime.now(ZoneInfo(self.tz)).astimezone(),
                                self.when, self.days, tz=self.tz)
            return self._next

    # -- control -----------------------------------------------------------
    def start(self) -> None:
        """Begin waiting. Calling it twice while running does nothing."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            # The first due time is computed before the thread starts so a caller
            # can print `next_run()` immediately after `start()`.
            self._next = due_at(datetime.now(ZoneInfo(self.tz)).astimezone(),
                                self.when, self.days, tz=self.tz)
            self._thread = threading.Thread(target=self._loop, name="thesisradar-schedule",
                                            daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Wake the loop and wait up to JOIN_TIMEOUT for it to leave."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=JOIN_TIMEOUT)
        with self._lock:
            self._thread = None
            self._next = None

    def run_once(self) -> Any:
        """Run the sweep now, whatever the clock says.

        This is the entry point for an external driver (systemd timer, hermes cron,
        a `.zshrc` line) and what `--now` calls.
        """
        try:
            return self.run()
        except Exception as err:  # noqa: BLE001 — the schedule must outlive one bad sweep
            if self.on_error is not None:
                self.on_error(err)
            return None

    # -- the loop ----------------------------------------------------------
    def _loop(self) -> None:
        while True:
            target = self._plan_next()
            wait = max(0.0, (target - datetime.now(ZoneInfo(self.tz))).total_seconds())
            if self._stop.wait(wait):
                return
            self.run_once()