"""Deterministic schedules. The model never decides when something is due."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def parse_hhmm(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("Time must be HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("Time must be HH:MM")
    return hour, minute


def combine_local(day: datetime, hhmm: str, tz: ZoneInfo) -> tuple[datetime, bool]:
    """Build a timezone-aware instant. If the clock time is skipped by DST, move forward one hour."""
    hour, minute = parse_hhmm(hhmm)
    naive = datetime(day.year, day.month, day.day, hour, minute)
    aware = naive.replace(tzinfo=tz)
    back = aware.astimezone(timezone.utc).astimezone(tz)
    if (back.hour, back.minute) != (hour, minute) or back.date() != naive.date():
        shifted = aware + timedelta(hours=1)
        return shifted, True
    return aware, False


def appointment_reminder_at(starts_at: datetime, offset_minutes: int) -> datetime:
    if offset_minutes < 0:
        raise ValueError("Reminder offset cannot be negative")
    return starts_at - timedelta(minutes=offset_minutes)


def reminder_state(due_at: datetime, now: datetime, acknowledged: bool) -> str:
    if acknowledged:
        return "done"
    if now >= due_at:
        return "missed"
    return "upcoming"


def next_daily_occurrence(now: datetime, hhmm: str, tz: ZoneInfo) -> tuple[datetime, bool]:
    local_now = now.astimezone(tz)
    today, adjusted = combine_local(local_now, hhmm, tz)
    if today > local_now:
        return today, adjusted
    tomorrow = local_now + timedelta(days=1)
    return combine_local(tomorrow, hhmm, tz)


def low_supply(remaining: int | None, threshold: int | None) -> bool:
    if remaining is None or threshold is None:
        return False
    return remaining <= threshold
