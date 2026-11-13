"""Due-item dispatch for in-app and GSConnect phone alerts."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import db
from .notifications import push_alert
from .scheduling import appointment_reminder_at


def _dispatched(conn: sqlite3.Connection, key: str) -> bool:
    row = conn.execute("SELECT due_key FROM alert_dispatches WHERE due_key = ?", (key,)).fetchone()
    return row is not None


def _mark(conn: sqlite3.Connection, kind: str, ref_id: int, due_key: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO alert_dispatches (due_key, kind, ref_id, sent_at) VALUES (?, ?, ?, ?)",
        (due_key, kind, ref_id, db.utcnow()),
    )


def tick(conn: sqlite3.Connection, use_gsconnect: bool, device_path: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    sent: list[dict] = []
    for row in conn.execute("SELECT * FROM reminders WHERE acknowledged = 0"):
        due = datetime.fromisoformat(row["due_at"])
        if due > now:
            continue
        key = f"reminder:{row['id']}:{due.isoformat()}"
        if _dispatched(conn, key):
            continue
        body = row["body"] or "Reminder"
        result = push_alert(row["title"], body, use_gsconnect, device_path)
        _mark(conn, "reminder", row["id"], key)
        sent.append({"kind": "reminder", "id": row["id"], "title": row["title"], **result.__dict__})

    for row in conn.execute("SELECT * FROM appointments WHERE status = 'scheduled' AND acknowledged = 0"):
        start = datetime.fromisoformat(row["starts_at"])
        due = appointment_reminder_at(start, row["reminder_offset_minutes"])
        if due > now:
            continue
        key = f"appointment:{row['id']}:{due.isoformat()}"
        if _dispatched(conn, key):
            continue
        body = row["location"] or row["notes"] or f"Starts {start.isoformat()}"
        result = push_alert(row["title"], body, use_gsconnect, device_path)
        _mark(conn, "appointment", row["id"], key)
        sent.append({"kind": "appointment", "id": row["id"], "title": row["title"], **result.__dict__})
    return sent
