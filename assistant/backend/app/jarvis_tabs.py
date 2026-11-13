"""Route a J.A.R.V.I.S. request to the Assistant tab that already owns the action.

Reads answer from the same tables the API uses. Writes are not performed here:
they come back as a proposal (existing confirm endpoint) or as an action the
client must send to an existing route, with confirmation when that route
already requires it.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

TABS = (
    "today",
    "jarvis",
    "calendar",
    "medications",
    "reminders",
    "notes",
    "memory",
    "records",
    "settings",
)

TAB_HELP = {
    "today": (
        "On Today, J.A.R.V.I.S. can list what is coming up, dismiss all due notices, "
        "dismiss one appointment or reminder by name, or delete sample data. "
        "Dismissals and deleting sample data wait for confirmation."
    ),
    "jarvis": (
        "This tab is the J.A.R.V.I.S. panel for open conversation. "
        "Speech and Quick save can still run the other tabs' commands from here "
        "when you name the action, such as list reminders or list appointments."
    ),
    "calendar": (
        "On Calendar, J.A.R.V.I.S. can list appointments, stage a new one with "
        "appointment: Title at an ISO time, cancel a local appointment by name, "
        "or sync Google Calendar. The month, week, and day controls stay in the calendar. "
        "Google events are read-only. Cancel and sync wait for confirmation."
    ),
    "medications": (
        "On Meds Tracker, the embedded tracker keeps its own sign-in, List, schedule, and doses. "
        "J.A.R.V.I.S. cannot click that separate account. It can list Assistant medication records, "
        "stage one with add medication Name at HH:MM, or log a record as taken or skipped after you confirm. "
        "It will not give dosing advice."
    ),
    "reminders": (
        "On Reminders, J.A.R.V.I.S. can list reminders, stage one with remind me:, "
        "acknowledge or delete one by name, or push one to your phone. "
        "Acknowledge, delete, and push wait for confirmation."
    ),
    "notes": (
        "On Notes, J.A.R.V.I.S. can list notes, stage one with note:, or delete one by title. "
        "Deleting waits for confirmation."
    ),
    "memory": (
        "On Fasten Health, J.A.R.V.I.S. can check whether Fasten on-prem is running. "
        "It cannot read or create clinic records. Assistant memories still answer recall: "
        "and stage with remember:."
    ),
    "records": (
        "On Quick save, J.A.R.V.I.S. stages note:, remember:, remind me:, and project:. "
        "Nothing is stored until you confirm. Medical questions are refused."
    ),
    "settings": (
        "On Settings, J.A.R.V.I.S. can report the selected provider without tokens, "
        "sync Google Calendar, enable or disable LAN, or delete every personal record. "
        "Those changes wait for confirmation, and LAN changes still only succeed from this computer."
    ),
}


def _clean_tab(tab: str) -> str:
    value = (tab or "").strip().lower()
    return value if value in TABS else ""


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params))


def _pick(rows: list[sqlite3.Row], query: str, label: str) -> tuple[sqlite3.Row | None, str | None]:
    needle = query.strip().lower()
    if not needle:
        return None, f"Name the {label} to use."
    exact = [row for row in rows if str(row["title"] if "title" in row.keys() else row["name"]).lower() == needle]
    chosen = exact or [
        row
        for row in rows
        if needle in str(row["title"] if "title" in row.keys() else row["name"]).lower()
    ]
    if not chosen:
        return None, f"No {label} matched “{query.strip()}”."
    if len(chosen) > 1:
        names = ", ".join(str(row["title"] if "title" in row.keys() else row["name"]) for row in chosen[:5])
        return None, f"More than one {label} matched. Be more specific: {names}."
    return chosen[0], None


def _action(summary: str, method: str, path: str, body: dict | None, confirm: bool) -> dict:
    return {"summary": summary, "method": method, "path": path, "body": body, "confirm": confirm}


def _result(reply: str, proposal: dict | None = None, action: dict | None = None) -> dict:
    return {"reply": reply, "proposal": proposal, "action": action}


def _help(tab: str) -> dict:
    current = TAB_HELP.get(tab) or (
        "J.A.R.V.I.S. can use the commands for Today, Calendar, Meds Tracker, Reminders, Notes, "
        "Fasten Health, Quick save, and Settings when you name the action."
    )
    return _result(current + " Ask “what can you do” on a tab for that tab's commands.")


def _list_titles(conn: sqlite3.Connection, sql: str, empty: str, prefix: str) -> dict:
    rows = _rows(conn, sql)
    if not rows:
        return _result(empty)
    parts = []
    for row in rows[:8]:
        title = row["title"] if "title" in row.keys() else row["name"]
        parts.append(str(title))
    extra = f" ({len(rows) - 8} more)" if len(rows) > 8 else ""
    return _result(prefix + ", ".join(parts) + extra + ".")


def route_tab(conn: sqlite3.Connection, tab: str, message: str) -> dict | None:
    """Return a reply, proposal, or client action. None means this is not a tab command."""
    text = message.strip()
    lower = text.lower().rstrip(".")
    current = _clean_tab(tab)

    if lower in {"help", "what can you do", "what can you do here", "what can jarvis do", "what's here", "whats here"}:
        return _help(current)

    if lower in {"list reminders", "show reminders"}:
        return _list_titles(
            conn,
            "SELECT title FROM reminders ORDER BY due_at LIMIT 20",
            "No reminders yet.",
            "Reminders: ",
        )

    if lower in {"list notes", "show notes"}:
        return _list_titles(
            conn,
            "SELECT title FROM notes ORDER BY updated_at DESC LIMIT 20",
            "No notes yet.",
            "Notes: ",
        )

    if lower in {"list appointments", "list calendar", "what's on my calendar", "whats on my calendar"}:
        rows = _rows(conn, "SELECT title, source FROM appointments WHERE status='scheduled' ORDER BY starts_at LIMIT 8")
        if not rows:
            return _result("No upcoming appointments on your calendar.")
        parts = [f"{row['title']} ({'Google' if row['source'] == 'google' else 'local'})" for row in rows]
        return _result("Appointments: " + "; ".join(parts) + ".")

    if lower in {"list medications", "list meds", "list medication records"}:
        rows = _rows(conn, "SELECT name FROM medications ORDER BY name LIMIT 20")
        if not rows:
            return _result(
                "No Assistant medication records yet. The Meds Tracker sign-in is separate, "
                "so its list is not included here."
            )
        return _result("Medication records: " + ", ".join(row["name"] for row in rows) + ".")

    if lower in {"fasten status", "is fasten running", "check fasten"}:
        return _result(
            "Checking whether Fasten Health on-prem is running. This does not read health records.",
            action=_action("Check Fasten Health", "GET", "/api/fasten/status", None, False),
        )

    if lower in {"provider status", "which provider", "what provider"}:
        provider = conn.execute("SELECT value FROM settings WHERE key='provider'").fetchone()
        consent = conn.execute("SELECT value FROM settings WHERE key='consent'").fetchone()
        name = provider["value"] if provider else "off"
        allowed = consent["value"] if consent else "0"
        return _result(
            f"Provider is {name}. Sending messages is {'allowed' if allowed == '1' else 'off'}. Tokens stay in Settings."
        )

    if lower in {"dismiss all due", "clear due reminders"}:
        return _result(
            "Dismissing due appointment and reminder notices needs confirmation.",
            action=_action("Dismiss all due notices", "POST", "/api/dismissals/due", {"confirmed": True}, True),
        )

    if lower in {"delete sample data", "delete demo data"}:
        return _result(
            "Deleting sample appointments, medications, and reminders needs confirmation. Your own records stay.",
            action=_action("Delete sample data", "DELETE", "/api/demo", {"confirmed": True}, True),
        )

    if lower in {"delete all data", "delete everything"}:
        return _result(
            "Deleting every personal record needs confirmation. This cannot be undone from J.A.R.V.I.S.",
            action=_action("Delete all personal records", "DELETE", "/api/data", {"confirmed": True}, True),
        )

    if lower in {"sync google calendar", "sync calendar"}:
        return _result(
            "Syncing Google Calendar replaces the Google events stored here. Confirm to run the existing sync.",
            action=_action("Sync Google Calendar", "POST", "/api/google/sync", None, True),
        )

    if lower == "enable lan":
        return _result(
            "Enabling LAN access needs confirmation, and it only succeeds from this computer.",
            action=_action("Enable LAN access", "POST", "/api/lan/enable", None, True),
        )

    if lower == "disable lan":
        return _result(
            "Disabling LAN access needs confirmation, and it only succeeds from this computer.",
            action=_action("Disable LAN access", "POST", "/api/lan/disable", None, True),
        )

    appointment = re.match(
        r"(?i)^appointment:\s*(.+?)\s+at\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2}))\s*$",
        text,
    )
    if appointment:
        title = appointment.group(1).strip()[:200]
        return _result(
            f"Saving “{title}” on the calendar needs confirmation.",
            action=_action(
                f"Save appointment: {title}",
                "POST",
                "/api/appointments",
                {
                    "title": title,
                    "starts_at": appointment.group(2),
                    "location": "",
                    "notes": "",
                    "reminder_offset_minutes": 2880,
                },
                True,
            ),
        )

    if re.match(r"(?i)^(add|create) appointment\b", text):
        return _result(
            "J.A.R.V.I.S. can save an appointment only with appointment: Title at an ISO time, "
            "for example appointment: Clinic at 2026-11-18T14:00:00-05:00. "
            "The calendar page still has its own add form."
        )

    medication = re.match(r"(?i)^add medication\s+(.+?)\s+at\s+([0-2]\d:[0-5]\d)\s*$", text)
    if medication:
        name = medication.group(1).strip()[:200]
        when = medication.group(2)
        return _result(
            f"Saving the medication record “{name}” needs confirmation. This does not change the Meds Tracker account.",
            action=_action(
                f"Save medication record: {name}",
                "POST",
                "/api/medications",
                {"name": name, "instructions": "", "times": [when]},
                True,
            ),
        )

    if re.match(r"(?i)^(add|create) medication\b", text):
        return _result(
            "Say add medication Name at HH:MM to stage an Assistant medication record. "
            "J.A.R.V.I.S. cannot add a medication inside the separate Meds Tracker sign-in."
        )

    dose = re.match(r"(?i)^log (?:medication|med)\s+(.+?)\s+as\s+(taken|skipped)\s*$", text)
    if dose:
        row, error = _pick(_rows(conn, "SELECT id, name FROM medications ORDER BY name"), dose.group(1), "medication record")
        if error or row is None:
            return _result(error or "No medication record matched.")
        status = dose.group(2).lower()
        scheduled = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        return _result(
            f"Logging {row['name']} as {status} needs confirmation. This is your record, not dosing advice.",
            action=_action(
                f"Log {row['name']} as {status}",
                "POST",
                f"/api/medications/{row['id']}/doses",
                {"scheduled_for": scheduled, "status": status},
                True,
            ),
        )

    named = (
        (
            r"(?i)^(?:delete|remove) reminder\s+(.+)$",
            "reminders",
            "SELECT id, title FROM reminders ORDER BY due_at",
            "reminder",
            "DELETE",
            "/api/reminders/{id}",
            {"confirmed": True},
            "Deleting “{title}” needs confirmation.",
        ),
        (
            r"(?i)^(?:acknowledge|dismiss) reminder\s+(.+)$",
            "reminders",
            "SELECT id, title FROM reminders WHERE acknowledged=0 ORDER BY due_at",
            "open reminder",
            "POST",
            "/api/reminders/{id}/acknowledge",
            {"confirmed": True},
            "Acknowledging “{title}” needs confirmation.",
        ),
        (
            r"(?i)^push reminder\s+(.+)$",
            "reminders",
            "SELECT id, title FROM reminders ORDER BY due_at",
            "reminder",
            "POST",
            "/api/reminders/{id}/push",
            None,
            "Pushing “{title}” notifies your phone or desktop. Confirm to continue.",
        ),
        (
            r"(?i)^(?:delete|remove) note\s+(.+)$",
            "notes",
            "SELECT id, title FROM notes ORDER BY updated_at DESC",
            "note",
            "DELETE",
            "/api/notes/{id}",
            {"confirmed": True},
            "Deleting the note “{title}” needs confirmation.",
        ),
        (
            r"(?i)^(?:cancel|delete) appointment\s+(.+)$",
            "appointments",
            "SELECT id, title, source FROM appointments WHERE status='scheduled' ORDER BY starts_at",
            "appointment",
            "POST",
            "/api/appointments/{id}/cancel",
            {"confirmed": True},
            "Cancelling “{title}” needs confirmation.",
        ),
        (
            r"(?i)^(?:acknowledge|dismiss) appointment\s+(.+)$",
            "appointments",
            "SELECT id, title, source FROM appointments WHERE status='scheduled' AND acknowledged=0 ORDER BY starts_at",
            "appointment",
            "POST",
            "/api/appointments/{id}/acknowledge",
            {"confirmed": True},
            "Dismissing the appointment notice for “{title}” needs confirmation.",
        ),
    )
    for pattern, _kind, sql, label, method, path, body, reply in named:
        match = re.match(pattern, text)
        if not match:
            continue
        row, error = _pick(_rows(conn, sql), match.group(1), label)
        if error or row is None:
            return _result(error or f"No {label} matched.")
        if "source" in row.keys() and (row["source"] or "local") == "google" and path.endswith("/cancel"):
            return _result(f"“{row['title']}” comes from Google Calendar and is read-only here.")
        return _result(
            reply.format(title=row["title"]),
            action=_action(reply.format(title=row["title"]), method, path.format(id=row["id"]), body, True),
        )

    if current == "medications" and lower in {"open list", "show list", "open schedule"}:
        return _result(
            "List and Schedule are buttons in the embedded Meds Tracker. "
            "J.A.R.V.I.S. cannot operate that sign-in. Say list medications for Assistant records."
        )

    if current == "calendar" and lower in {"month", "week", "day", "show month", "show week", "show day"}:
        return _result(
            "Month, week, and day stay on the calendar page. "
            "J.A.R.V.I.S. can list appointments or save one with appointment: Title at an ISO time."
        )

    if current == "memory" and "fasten" in lower and any(word in lower for word in ("import", "connect", "clinic", "record")):
        return _result(
            "Fasten Health on this page does not connect to clinics. "
            "J.A.R.V.I.S. can only check whether the local app is running."
        )

    return None
