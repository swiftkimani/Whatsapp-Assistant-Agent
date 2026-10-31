"""Hours when the assistant writes drafts but does not send them.

A reply at 3am reads as a bot in a way that no amount of tone work fixes, and
it is the one mistake you cannot take back. Messages still arrive, are still
answered, and still land in the Held queue — only the sending waits.

QUIET_HOURS is "HH:MM-HH:MM" in the local timezone, empty to switch off. The
range may wrap past midnight, which is the normal case.
"""
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo(os.getenv("TZ", "Africa/Nairobi"))


def _parse(window: str) -> tuple[time, time] | None:
    try:
        start_text, end_text = window.split("-")
        start_hour, start_minute = (int(p) for p in start_text.strip().split(":"))
        end_hour, end_minute = (int(p) for p in end_text.strip().split(":"))
        return time(start_hour, start_minute), time(end_hour, end_minute)
    except (ValueError, AttributeError):
        return None


def window() -> tuple[time, time] | None:
    raw = os.getenv("QUIET_HOURS", "").strip()
    return _parse(raw) if raw else None


def is_quiet(now: datetime | None = None) -> bool:
    """True when sending should wait. A misspelt setting means "not quiet":
    failing loudly here would hold every reply because of a typo."""
    bounds = window()
    if bounds is None:
        return False
    start, end = bounds
    if start == end:
        return False                     # a zero-length window, not an all-day one
    current = (now or datetime.now(LOCAL_TZ)).time()
    if start < end:
        return start <= current < end
    return current >= start or current < end     # wraps past midnight
