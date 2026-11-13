"""Local Jarvis-style skills: no cloud, no autonomous shell access."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import file_search
from .scheduling import appointment_reminder_at, reminder_state


def _setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _memory_hits(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict]:
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
    if not words:
        return []
    rows = conn.execute("SELECT id, title, body, updated_at FROM memories").fetchall()
    scored: list[tuple[int, dict]] = []
    for row in rows:
        blob = f"{row['title']} {row['body']}".lower()
        score = sum(2 if w in row["title"].lower() else 1 for w in words if w in blob)
        if score:
            scored.append((score, dict(row)))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:limit]]


def _next_items(conn: sqlite3.Connection) -> list[dict]:
    now = datetime.now(timezone.utc)
    items: list[dict] = []
    for row in conn.execute("SELECT * FROM reminders WHERE acknowledged = 0"):
        due = datetime.fromisoformat(row["due_at"])
        items.append(
            {
                "kind": "reminder",
                "title": row["title"],
                "due_at": due,
                "state": reminder_state(due, now, False),
            }
        )
    for row in conn.execute("SELECT * FROM appointments WHERE status = 'scheduled' AND acknowledged = 0"):
        start = datetime.fromisoformat(row["starts_at"])
        due = appointment_reminder_at(start, row["reminder_offset_minutes"])
        items.append(
            {
                "kind": "appointment",
                "title": row["title"],
                "due_at": due,
                "state": reminder_state(due, now, False),
                "starts_at": start,
            }
        )
    items.sort(key=lambda item: item["due_at"])
    return items


def build_hud(conn: sqlite3.Connection) -> dict:
    now = datetime.now(timezone.utc)
    items = _next_items(conn)
    next_due = None
    if items:
        due = items[0]
        delta = (due["due_at"] - now).total_seconds()
        next_due = {
            "kind": due["kind"],
            "title": due["title"],
            "due_at": due["due_at"].isoformat(),
            "state": due["state"],
            "seconds_until": int(delta),
        }
    active = conn.execute(
        "SELECT id, title, status FROM projects WHERE status='active' ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    return {
        "next_due": next_due,
        "active_project": dict(active) if active else None,
        "voice_skill_count": 6,
    }


def try_local_answer(conn: sqlite3.Connection, message: str) -> str | None:
    text = message.strip()
    lower = text.lower()

    if re.match(r"(?i)^(what'?s next|what is next|what'?s coming up|what is coming up)\??$", text):
        items = _next_items(conn)
        if not items:
            return "Nothing is scheduled. You can add a reminder or appointment."
        lines = []
        for item in items[:4]:
            when = item["due_at"].astimezone().strftime("%a %b %d, %I:%M %p")
            label = "Reminder" if item["kind"] == "reminder" else "Appointment heads-up"
            lines.append(f"{label}: {item['title']} — {when} ({item['state']})")
        return " ".join(lines)

    if re.match(r"(?i)^(next appointment|what'?s on my calendar)\??$", text):
        rows = conn.execute(
            "SELECT title, starts_at, source FROM appointments WHERE status='scheduled' ORDER BY starts_at LIMIT 5"
        ).fetchall()
        if not rows:
            return "No upcoming appointments on your calendar."
        parts = []
        for row in rows:
            when = datetime.fromisoformat(row["starts_at"]).astimezone().strftime("%a %b %d, %I:%M %p")
            tag = "Google" if row["source"] == "google" else "local"
            parts.append(f"{row['title']} ({tag}) at {when}")
        return "Up next: " + "; ".join(parts) + "."

    if re.match(r"(?i)^(next reminder)\??$", text):
        row = conn.execute(
            "SELECT title, due_at FROM reminders WHERE acknowledged=0 ORDER BY due_at LIMIT 1"
        ).fetchone()
        if row is None:
            return "No open reminders."
        when = datetime.fromisoformat(row["due_at"]).astimezone().strftime("%a %b %d, %I:%M %p")
        return f"Next reminder: {row['title']} at {when}."

    recall = re.match(r"(?i)^(?:recall|remember about|what do i (?:know|remember) about)[:\s]+(.+)$", text)
    if recall:
        hits = _memory_hits(conn, recall.group(1))
        if not hits:
            return "I did not find a saved memory matching that."
        chunks = [f"{h['title']}: {h['body'][:200]}" for h in hits[:3]]
        return "From your memory: " + " | ".join(chunks)

    find = re.match(r"(?i)^(?:find|search) (?:file|files)(?:\s+for)?[:\s]+(.+)$", text)
    if find:
        roots = _setting(conn, "file_search_roots", "")
        matches = file_search.search(roots, find.group(1))
        if not matches:
            return "No files matched in your approved folders. Add paths in Settings → File search."
        return "Files found: " + "; ".join(m["path"] for m in matches[:8])

    if re.match(r"(?i)^list projects\.?$", text):
        rows = conn.execute("SELECT title, status FROM projects ORDER BY updated_at DESC LIMIT 8").fetchall()
        if not rows:
            return "No projects yet. Say project: followed by a name to start one."
        return "Projects: " + ", ".join(f"{r['title']} ({r['status']})" for r in rows)

    if "help" in lower and ("skills" in lower or "commands" in lower):
        return (
            "Local skills: what's next, next appointment, next reminder, "
            "recall: topic, find files: name, list projects, "
            "note:/remember:/remind me:/project: (needs confirm). "
            "Open conversation stays on the J.A.R.V.I.S. tab. "
            "Voice Butler mode speaks replies when enabled in Settings."
        )

    return None
