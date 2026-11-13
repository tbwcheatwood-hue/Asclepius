"""Local assistant API. Records stay in SQLite on this machine."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
import secrets

import httpx

from . import alerts, db, repair
from . import file_search
from . import google_calendar
from . import lan_access
from . import lan_sync
from . import jarvis_bridge
from . import jarvis_project
from .jarvis_tabs import route_tab
from . import tunnel_access
from . import notifications as push
from .confirm import ConfirmBody, require_confirmed
from .providers import (
    ALS_DEFAULT,
    LMSTUDIO_DEFAULT,
    complete_als_chat,
    complete_lmstudio,
    probe_als,
    probe_lmstudio,
)
from .scheduling import appointment_reminder_at, low_supply, next_daily_occurrence, parse_hhmm, reminder_state

app = FastAPI(title="Assistant", docs_url=None, redoc_url=None)


def _cors_origins() -> list[str]:
    origins = list(jarvis_bridge.ASSISTANT_ORIGINS)
    extra = tunnel_access.tunnel_origin()
    if extra and extra not in origins:
        origins.append(extra)
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

MEDICAL_REFUSAL = (
    "I can't give medication advice, suggest a dose, or tell you to skip or change a dose. "
    "What you enter here is your own record, not a clinician's instruction."
)


def local_tz_name() -> str:
    try:
        return datetime.now().astimezone().tzinfo.key  # type: ignore[union-attr]
    except Exception:
        return "America/New_York"


def boot() -> None:
    conn = db.connect()
    db.migrate(conn)
    db.seed_demo(conn, local_tz_name())
    conn.close()


boot()

LAN_OPEN_PATHS = {
    ("GET", "/api/lan/status"),
    ("POST", "/api/lan/pair"),
}


@app.middleware("http")
async def lan_access_guard(request: Request, call_next):
    path = request.url.path
    method = request.method.upper()
    client_host = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for")
    client_ip = lan_access.client_ip_from_headers(client_host, forwarded)
    if not tunnel_access.allow_public_client_ip(client_ip, request):
        return JSONResponse(status_code=403, content={"detail": "Access from the public internet is not allowed."})
    conn = db.connect()
    try:
        enabled = lan_access.lan_enabled(conn)
        lan_access.cleanup_expired(conn)
        conn.commit()
    finally:
        conn.close()
    if not enabled:
        return await call_next(request)
    if lan_access.is_loopback(client_ip):
        return await call_next(request)
    if not forwarded and lan_access.is_test_client(client_host):
        return await call_next(request)
    if (method, path) in LAN_OPEN_PATHS:
        return await call_next(request)
    token = request.headers.get(lan_access.TOKEN_HEADER, "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    conn = db.connect()
    try:
        session = lan_access.session_from_token(conn, token)
        if session is None:
            return JSONResponse(status_code=401, content={"detail": "LAN session required. Pair this device first."})
        if method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = request.headers.get(lan_access.CSRF_HEADER, "")
            if not lan_access.verify_csrf(session, csrf):
                return JSONResponse(status_code=403, content={"detail": "Missing or invalid CSRF token."})
        conn.commit()
    finally:
        conn.close()
    return await call_next(request)


def setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def put_setting(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def log_action(conn, summary: str, status: str) -> None:
    conn.execute(
        "INSERT INTO actions (summary, status, created_at) VALUES (?, ?, ?)",
        (summary, status, db.utcnow()),
    )


class AppointmentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    starts_at: str
    ends_at: str | None = None
    location: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=4000)
    reminder_offset_minutes: int = 2880


class MedicationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    instructions: str = Field(default="", max_length=2000)
    supply_remaining: int | None = Field(default=None, ge=0, le=100000)
    low_supply_threshold: int | None = Field(default=None, ge=0, le=100000)
    times: list[str] = Field(min_length=1, max_length=12)


class DoseIn(BaseModel):
    scheduled_for: str
    status: str


class ReminderIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=4000)
    due_at: str
    recurrence: str = "none"


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=20000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    tab: str = ""


class SettingsIn(BaseModel):
    provider: str
    lmstudio_url: str = LMSTUDIO_DEFAULT
    als_url: str = ALS_DEFAULT
    als_api_token: str = ""
    lmstudio_model: str = ""
    consent: bool = False
    timezone: str
    text_scale: str = "100"
    contrast: str = "default"
    reduced_motion: bool = False
    gsconnect_push: bool = True
    gsconnect_device: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    voice_speak_replies: bool = True
    butler_mode: bool = False
    file_search_roots: str = ""


class RepairIn(BaseModel):
    explanation: str = Field(min_length=1, max_length=2000)


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=20000)
    status: str = "active"


def parse_when(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, "Use an ISO date and time") from exc
    if parsed.tzinfo is None:
        raise HTTPException(400, "Include a time zone offset")
    return parsed.astimezone(timezone.utc)


def require_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception as exc:
        raise HTTPException(400, "Unknown time zone") from exc


@app.get("/api/health")
def health():
    conn = db.connect()
    try:
        db.migrate(conn)
        conn.execute("SELECT 1").fetchone()
        ok = True
    except sqlite3.Error:
        ok = False
    finally:
        conn.close()
    return repair.health(ok)


@app.get("/api/dashboard")
def dashboard():
    conn = db.connect()
    try:
        db.migrate(conn)
        provider = setting(conn, "provider", "off")
        consent = setting(conn, "consent", "0") == "1"
        actions = [dict(row) for row in conn.execute("SELECT id, summary, status, created_at FROM actions ORDER BY id DESC LIMIT 8")]
        repairs = [
            dict(row)
            for row in conn.execute(
                "SELECT id, explanation, status, created_at FROM repair_proposals ORDER BY id DESC LIMIT 5"
            )
        ]
        upcoming = _upcoming(conn)
        return {
            "assistant": "on" if provider != "off" and consent else "off",
            "provider": provider,
            "consent": consent,
            "capabilities": [
                "calendar",
                "medications",
                "reminders",
                "notes",
                "memory",
                "jarvis",
                "speech-input",
                "gsconnect",
                "google-calendar",
            ],
            "jarvis": jarvis_bridge.probe_jarvis(),
            "background_jobs": [],
            "upcoming": upcoming[:8],
            "actions": actions,
            "repairs": repairs,
            "notice": (
                "Due reminders push to your desktop and, when enabled, to your phone through GSConnect "
                "while this page stays open."
            ),
        }
    finally:
        conn.close()


def _upcoming(conn) -> list[dict]:
    now = datetime.now(timezone.utc)
    tz_name = setting(conn, "timezone", local_tz_name())
    zone = ZoneInfo(tz_name) if tz_name else ZoneInfo("UTC")
    items: list[dict] = []
    for row in conn.execute("SELECT * FROM appointments WHERE status = 'scheduled'"):
        start = datetime.fromisoformat(row["starts_at"])
        due = appointment_reminder_at(start, row["reminder_offset_minutes"])
        state = reminder_state(due, now, bool(row["acknowledged"]))
        if state == "upcoming" and due - now > timedelta(days=14):
            continue
        items.append(
            {
                "kind": "appointment",
                "id": row["id"],
                "title": row["title"],
                "due_at": due.isoformat(),
                "state": state,
                "demo": bool(row["is_demo"]),
            }
        )
    for row in conn.execute("SELECT * FROM reminders"):
        due = datetime.fromisoformat(row["due_at"])
        state = reminder_state(due, now, bool(row["acknowledged"]))
        items.append(
            {
                "kind": "reminder",
                "id": row["id"],
                "title": row["title"],
                "due_at": due.isoformat(),
                "state": state,
                "demo": bool(row["is_demo"]),
            }
        )
    for row in conn.execute("SELECT * FROM medications"):
        times = json.loads(row["times_json"])
        med_zone = ZoneInfo(row["timezone"])
        for hhmm in times:
            due, _adjusted = next_daily_occurrence(now, hhmm, med_zone)
            items.append(
                {
                    "kind": "medication",
                    "id": row["id"],
                    "title": row["name"],
                    "due_at": due.isoformat(),
                    "state": "upcoming",
                    "demo": bool(row["is_demo"]),
                }
            )
        if low_supply(row["supply_remaining"], row["low_supply_threshold"]):
            items.append(
                {
                    "kind": "supply",
                    "id": row["id"],
                    "title": f"Low supply: {row['name']}",
                    "due_at": now.isoformat(),
                    "state": "missed",
                    "demo": bool(row["is_demo"]),
                }
            )
    items.sort(key=lambda item: item["due_at"])
    _ = zone
    return items


@app.get("/api/upcoming")
def upcoming():
    conn = db.connect()
    try:
        return {"items": _upcoming(conn), "timezone": setting(conn, "timezone", local_tz_name())}
    finally:
        conn.close()


@app.get("/api/appointments")
def list_appointments():
    conn = db.connect()
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM appointments ORDER BY starts_at")]
        return {"items": rows}
    finally:
        conn.close()


@app.post("/api/appointments")
def create_appointment(body: AppointmentIn):
    start = parse_when(body.starts_at)
    end = parse_when(body.ends_at) if body.ends_at else None
    if body.reminder_offset_minutes < 0 or body.reminder_offset_minutes > 60 * 24 * 30:
        raise HTTPException(400, "Reminder offset is out of range")
    now = db.utcnow()
    conn = db.connect()
    try:
        cur = conn.execute(
            """INSERT INTO appointments
            (title, starts_at, ends_at, location, notes, reminder_offset_minutes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.title.strip(), start.isoformat(), end.isoformat() if end else None, body.location, body.notes, body.reminder_offset_minutes, now, now),
        )
        log_action(conn, "Appointment saved", "complete")
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/appointments/{item_id}")
def update_appointment(item_id: int, body: AppointmentIn):
    start = parse_when(body.starts_at)
    end = parse_when(body.ends_at) if body.ends_at else None
    conn = db.connect()
    try:
        cur = conn.execute(
            """UPDATE appointments
            SET title=?, starts_at=?, ends_at=?, location=?, notes=?, reminder_offset_minutes=?, updated_at=?
            WHERE id=? AND status='scheduled'""",
            (body.title.strip(), start.isoformat(), end.isoformat() if end else None, body.location, body.notes, body.reminder_offset_minutes, db.utcnow(), item_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Appointment not found")
        log_action(conn, "Appointment updated", "complete")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/appointments/{item_id}/cancel")
def cancel_appointment(item_id: int, body: ConfirmBody):
    require_confirmed(body)
    conn = db.connect()
    try:
        row = conn.execute("SELECT source FROM appointments WHERE id=?", (item_id,)).fetchone()
        if row and (row["source"] or "local") == "google":
            raise HTTPException(400, "Google Calendar events are read-only here.")
        cur = conn.execute(
            "UPDATE appointments SET status='cancelled', updated_at=? WHERE id=? AND status='scheduled'",
            (db.utcnow(), item_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Appointment not found")
        log_action(conn, "Appointment cancelled", "complete")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/appointments/{item_id}/acknowledge")
def ack_appointment(item_id: int, body: ConfirmBody):
    require_confirmed(body)
    conn = db.connect()
    try:
        conn.execute("UPDATE appointments SET acknowledged=1, updated_at=? WHERE id=?", (db.utcnow(), item_id))
        log_action(conn, "Appointment reminder acknowledged", "complete")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/medications")
def list_medications():
    conn = db.connect()
    try:
        items = []
        for row in conn.execute("SELECT * FROM medications ORDER BY name"):
            item = dict(row)
            item["times"] = json.loads(item.pop("times_json"))
            item["logs"] = [
                dict(log)
                for log in conn.execute(
                    "SELECT id, scheduled_for, status, logged_at FROM dose_logs WHERE medication_id=? ORDER BY logged_at DESC LIMIT 20",
                    (row["id"],),
                )
            ]
            items.append(item)
        return {"items": items, "disclaimer": "This is your own record. It is not medical advice or a medical alert system."}
    finally:
        conn.close()


@app.post("/api/medications")
def create_medication(body: MedicationIn):
    try:
        for value in body.times:
            parse_hhmm(value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    conn = db.connect()
    try:
        tz_name = setting(conn, "timezone", local_tz_name())
        cur = conn.execute(
            """INSERT INTO medications
            (name, instructions, supply_remaining, low_supply_threshold, times_json, timezone, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                body.name.strip(),
                body.instructions,
                body.supply_remaining,
                body.low_supply_threshold,
                json.dumps(body.times),
                tz_name,
                db.utcnow(),
            ),
        )
        log_action(conn, "Medication record saved", "complete")
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.post("/api/medications/{item_id}/doses")
def log_dose(item_id: int, body: DoseIn):
    if body.status not in {"taken", "skipped", "pending"}:
        raise HTTPException(400, "Status must be taken, skipped, or pending")
    parse_when(body.scheduled_for)
    conn = db.connect()
    try:
        row = conn.execute("SELECT id, supply_remaining FROM medications WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Medication not found")
        conn.execute(
            "INSERT INTO dose_logs (medication_id, scheduled_for, status, logged_at) VALUES (?, ?, ?, ?)",
            (item_id, body.scheduled_for, body.status, db.utcnow()),
        )
        if body.status == "taken" and row["supply_remaining"] is not None and row["supply_remaining"] > 0:
            conn.execute(
                "UPDATE medications SET supply_remaining = supply_remaining - 1 WHERE id=?",
                (item_id,),
            )
        log_action(conn, "Dose status recorded", "complete")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/reminders")
def list_reminders():
    conn = db.connect()
    try:
        return {"items": [dict(row) for row in conn.execute("SELECT * FROM reminders ORDER BY due_at")], "timezone": setting(conn, "timezone", local_tz_name())}
    finally:
        conn.close()


@app.post("/api/reminders")
def create_reminder(body: ReminderIn):
    if body.recurrence not in {"none", "daily", "weekly"}:
        raise HTTPException(400, "Recurrence must be none, daily, or weekly")
    due = parse_when(body.due_at)
    conn = db.connect()
    try:
        cur = conn.execute(
            """INSERT INTO reminders (title, body, due_at, recurrence, timezone, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (body.title.strip(), body.body, due.isoformat(), body.recurrence, setting(conn, "timezone", local_tz_name()), db.utcnow()),
        )
        log_action(conn, "Reminder saved", "complete")
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.post("/api/reminders/{item_id}/acknowledge")
def ack_reminder(item_id: int, body: ConfirmBody):
    require_confirmed(body)
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM reminders WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Reminder not found")
        if row["recurrence"] == "none":
            conn.execute("UPDATE reminders SET acknowledged=1 WHERE id=?", (item_id,))
        else:
            due = datetime.fromisoformat(row["due_at"])
            step = timedelta(days=1 if row["recurrence"] == "daily" else 7)
            nxt = due + step
            while nxt <= datetime.now(timezone.utc):
                nxt += step
            conn.execute("UPDATE reminders SET due_at=?, acknowledged=0 WHERE id=?", (nxt.isoformat(), item_id))
        log_action(conn, "Reminder acknowledged", "complete")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/dismissals/due")
def dismiss_due_notifications(body: ConfirmBody):
    """Acknowledge all appointment and one-time reminder notifications that are currently due."""
    require_confirmed(body)
    conn = db.connect()
    now = datetime.now(timezone.utc)
    touched = {"appointments": 0, "reminders": 0}
    try:
        for row in conn.execute("SELECT * FROM appointments WHERE status = 'scheduled' AND acknowledged = 0"):
            start = datetime.fromisoformat(row["starts_at"])
            due = appointment_reminder_at(start, row["reminder_offset_minutes"])
            if due <= now:
                conn.execute(
                    "UPDATE appointments SET acknowledged=1, updated_at=? WHERE id=?",
                    (db.utcnow(), row["id"]),
                )
                touched["appointments"] += 1
        for row in conn.execute(
            "SELECT * FROM reminders WHERE acknowledged = 0 AND recurrence = 'none'"
        ):
            due = datetime.fromisoformat(row["due_at"])
            if due <= now:
                conn.execute("UPDATE reminders SET acknowledged=1 WHERE id=?", (row["id"],))
                touched["reminders"] += 1
        log_action(conn, "Due notifications dismissed in bulk", "complete")
        conn.commit()
        return {"ok": True, **touched}
    finally:
        conn.close()


@app.delete("/api/reminders/{item_id}")
def delete_reminder(item_id: int, body: ConfirmBody):
    require_confirmed(body)
    conn = db.connect()
    try:
        conn.execute("DELETE FROM reminders WHERE id=?", (item_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def _crud_text(table: str):
    pass


@app.get("/api/notes")
def list_notes():
    conn = db.connect()
    try:
        return {"items": [dict(row) for row in conn.execute("SELECT * FROM notes ORDER BY updated_at DESC")]}
    finally:
        conn.close()


@app.post("/api/notes")
def create_note(body: NoteIn):
    conn = db.connect()
    try:
        now = db.utcnow()
        cur = conn.execute("INSERT INTO notes (title, body, updated_at) VALUES (?, ?, ?)", (body.title.strip(), body.body, now))
        log_action(conn, "Note saved", "complete")
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/notes/{item_id}")
def update_note(item_id: int, body: NoteIn):
    conn = db.connect()
    try:
        cur = conn.execute("UPDATE notes SET title=?, body=?, updated_at=? WHERE id=?", (body.title.strip(), body.body, db.utcnow(), item_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "Note not found")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/notes/{item_id}")
def delete_note(item_id: int, body: ConfirmBody):
    require_confirmed(body)
    conn = db.connect()
    try:
        conn.execute("DELETE FROM notes WHERE id=?", (item_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/memories")
def list_memories():
    conn = db.connect()
    try:
        return {"items": [dict(row) for row in conn.execute("SELECT * FROM memories ORDER BY updated_at DESC")]}
    finally:
        conn.close()


@app.post("/api/memories")
def create_memory(body: NoteIn):
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO memories (title, body, updated_at) VALUES (?, ?, ?)",
            (body.title.strip(), body.body, db.utcnow()),
        )
        log_action(conn, "Memory saved", "complete")
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/memories/{item_id}")
def update_memory(item_id: int, body: NoteIn):
    conn = db.connect()
    try:
        cur = conn.execute(
            "UPDATE memories SET title=?, body=?, updated_at=? WHERE id=?",
            (body.title.strip(), body.body, db.utcnow(), item_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Memory not found")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/projects")
def list_projects():
    conn = db.connect()
    try:
        db.migrate(conn)
        rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC")
        return {"items": [dict(row) for row in rows]}
    finally:
        conn.close()


@app.post("/api/projects")
def create_project(body: ProjectIn):
    if body.status not in {"active", "archived"}:
        raise HTTPException(400, "Status must be active or archived")
    conn = db.connect()
    try:
        now = db.utcnow()
        cur = conn.execute(
            "INSERT INTO projects (title, body, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (body.title.strip(), body.body, body.status, now, now),
        )
        log_action(conn, "Project saved", "complete")
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/projects/{item_id}")
def update_project(item_id: int, body: ProjectIn):
    if body.status not in {"active", "archived"}:
        raise HTTPException(400, "Status must be active or archived")
    conn = db.connect()
    try:
        now = db.utcnow()
        cur = conn.execute(
            "UPDATE projects SET title=?, body=?, status=?, updated_at=? WHERE id=?",
            (body.title.strip(), body.body, body.status, now, item_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Project not found")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/projects/{item_id}")
def delete_project(item_id: int, body: ConfirmBody):
    require_confirmed(body)
    conn = db.connect()
    try:
        conn.execute("DELETE FROM projects WHERE id=?", (item_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/files/search")
def files_search(q: str = ""):
    conn = db.connect()
    try:
        roots = setting(conn, "file_search_roots", "")
        items = file_search.search(roots, q)
        return {"items": items, "query": q.strip()}
    finally:
        conn.close()


@app.delete("/api/memories/{item_id}")
def delete_memory(item_id: int, body: ConfirmBody):
    require_confirmed(body)
    conn = db.connect()
    try:
        conn.execute("DELETE FROM memories WHERE id=?", (item_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/export")
def export_data():
    conn = db.connect()
    try:
        def rows(sql: str):
            return [dict(row) for row in conn.execute(sql)]

        return JSONResponse(
            {
                "exported_at": db.utcnow(),
                "appointments": rows("SELECT * FROM appointments"),
                "medications": rows("SELECT id, name, instructions, supply_remaining, low_supply_threshold, times_json, timezone, is_demo, created_at FROM medications"),
                "dose_logs": rows("SELECT * FROM dose_logs"),
                "reminders": rows("SELECT * FROM reminders"),
                "notes": rows("SELECT * FROM notes"),
                "memories": rows("SELECT * FROM memories"),
                "projects": rows("SELECT * FROM projects"),
            }
        )
    finally:
        conn.close()


@app.delete("/api/data")
def delete_all(body: ConfirmBody):
    require_confirmed(body)
    conn = db.connect()
    try:
        for table in (
            "dose_logs",
            "medications",
            "appointments",
            "reminders",
            "notes",
            "memories",
            "projects",
            "actions",
            "proposals",
        ):
            conn.execute(f"DELETE FROM {table}")
        log_action(conn, "All personal records deleted", "complete")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/demo")
def delete_demo(body: ConfirmBody):
    require_confirmed(body)
    conn = db.connect()
    try:
        conn.execute("DELETE FROM dose_logs WHERE medication_id IN (SELECT id FROM medications WHERE is_demo=1)")
        conn.execute("DELETE FROM medications WHERE is_demo=1")
        conn.execute("DELETE FROM appointments WHERE is_demo=1")
        conn.execute("DELETE FROM reminders WHERE is_demo=1")
        log_action(conn, "Sample data deleted", "complete")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/settings")
def get_settings():
    conn = db.connect()
    try:
        keys = (
            "provider",
            "lmstudio_url",
            "als_url",
            "als_api_token",
            "lmstudio_model",
            "consent",
            "timezone",
            "text_scale",
            "contrast",
            "reduced_motion",
            "gsconnect_push",
            "gsconnect_device",
            "google_client_id",
            "google_client_secret",
            "voice_speak_replies",
            "butler_mode",
            "file_search_roots",
        )
        values = {key: setting(conn, key, "") for key in keys}
        if not values["provider"]:
            values["provider"] = "off"
        if not values["lmstudio_url"]:
            values["lmstudio_url"] = LMSTUDIO_DEFAULT
        if not values["als_url"]:
            values["als_url"] = ALS_DEFAULT
        if not values["timezone"]:
            values["timezone"] = local_tz_name()
        values["consent"] = values["consent"] == "1"
        values["reduced_motion"] = values["reduced_motion"] == "1"
        if not values["gsconnect_push"]:
            values["gsconnect_push"] = "1"
        values["gsconnect_push"] = values["gsconnect_push"] == "1"
        if not values.get("voice_speak_replies"):
            values["voice_speak_replies"] = "1"
        values["voice_speak_replies"] = values["voice_speak_replies"] == "1"
        values["butler_mode"] = values.get("butler_mode", "0") == "1"
        if not values.get("file_search_roots"):
            root = jarvis_project.REPO_ROOT
            assistant = jarvis_project.ASSISTANT_DIR
            values["file_search_roots"] = f"{assistant}\n{root}"
        if not values["text_scale"]:
            values["text_scale"] = "100"
        if not values["contrast"]:
            values["contrast"] = "default"
        return values
    finally:
        conn.close()


@app.put("/api/settings")
def update_settings(body: SettingsIn):
    if body.provider not in {"off", "lmstudio", "als"}:
        raise HTTPException(400, "Provider must be off, lmstudio, or als")
    require_zone(body.timezone)
    if body.text_scale not in {"100", "125", "150"}:
        raise HTTPException(400, "Text scale must be 100, 125, or 150")
    if body.contrast not in {"default", "high"}:
        raise HTTPException(400, "Contrast must be default or high")
    conn = db.connect()
    try:
        put_setting(conn, "provider", body.provider)
        put_setting(conn, "lmstudio_url", body.lmstudio_url.strip() or LMSTUDIO_DEFAULT)
        put_setting(conn, "als_url", body.als_url.strip() or ALS_DEFAULT)
        put_setting(conn, "als_api_token", body.als_api_token.strip())
        put_setting(conn, "lmstudio_model", body.lmstudio_model.strip())
        put_setting(conn, "consent", "1" if body.consent else "0")
        put_setting(conn, "timezone", body.timezone)
        put_setting(conn, "text_scale", body.text_scale)
        put_setting(conn, "contrast", body.contrast)
        put_setting(conn, "reduced_motion", "1" if body.reduced_motion else "0")
        put_setting(conn, "gsconnect_push", "1" if body.gsconnect_push else "0")
        put_setting(conn, "gsconnect_device", body.gsconnect_device.strip())
        if body.google_client_id.strip():
            put_setting(conn, "google_client_id", body.google_client_id.strip())
        if body.google_client_secret.strip():
            put_setting(conn, "google_client_secret", body.google_client_secret.strip())
        put_setting(conn, "voice_speak_replies", "1" if body.voice_speak_replies else "0")
        put_setting(conn, "butler_mode", "1" if body.butler_mode else "0")
        put_setting(conn, "file_search_roots", body.file_search_roots.strip())
        log_action(conn, "Settings saved", "complete")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/providers/status")
def provider_status():
    conn = db.connect()
    try:
        lm = probe_lmstudio(setting(conn, "lmstudio_url", LMSTUDIO_DEFAULT))
        als = probe_als(
            setting(conn, "als_url", ALS_DEFAULT),
            setting(conn, "als_api_token", ""),
        )
        return {
            "selected": setting(conn, "provider", "off"),
            "consent": setting(conn, "consent", "0") == "1",
            "sent_when_enabled": "Only the message you just typed. Records are not attached.",
            "providers": [lm, als, {"id": "off", "state": "selected" if setting(conn, "provider", "off") == "off" else "available", "chat": False, "models": [], "detail": "The app works with no AI."}],
        }
    finally:
        conn.close()


MEDICAL_RE = re.compile(r"\b(dose|dosage|diagnos|should i skip|change my (med|medicine|medication)|what should i take)\b", re.I)


def local_proposal(message: str) -> dict | None:
    text = message.strip()
    note = re.match(r"(?i)^note:\s*(.+)$", text)
    if note:
        return {"kind": "note", "summary": f"Save a note: {note.group(1)[:80]}", "payload": {"title": "Note", "body": note.group(1)}}
    memory = re.match(r"(?i)^remember:\s*(.+)$", text)
    if memory:
        return {"kind": "memory", "summary": f"Save a memory: {memory.group(1)[:80]}", "payload": {"title": "Memory", "body": memory.group(1)}}
    reminder = re.match(r"(?i)^remind me:\s*(.+)$", text)
    if reminder:
        due = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0)
        return {
            "kind": "reminder",
            "summary": f"Create a reminder: {reminder.group(1)[:80]}",
            "payload": {"title": reminder.group(1)[:200], "body": "", "due_at": due.isoformat(), "recurrence": "none"},
        }
    project = re.match(r"(?i)^project:\s*(.+)$", text)
    if project:
        return {
            "kind": "project",
            "summary": f"Start a project: {project.group(1)[:80]}",
            "payload": {"title": project.group(1)[:200], "body": "", "status": "active"},
        }
    return None


def _store_proposal(conn, proposal: dict) -> dict:
    cur = conn.execute(
        "INSERT INTO proposals (kind, summary, payload_json, status, created_at) VALUES (?, ?, ?, 'awaiting_approval', ?)",
        (proposal["kind"], proposal["summary"], json.dumps(proposal["payload"]), db.utcnow()),
    )
    log_action(conn, "Change waiting for approval", "awaiting_approval")
    conn.commit()
    proposal["id"] = cur.lastrowid
    proposal["status"] = "awaiting_approval"
    return proposal


@app.post("/api/assistant/message")
def assistant_message(body: ChatIn):
    if MEDICAL_RE.search(body.message):
        return {"reply": MEDICAL_REFUSAL, "proposal": None, "action": None, "sent": False, "source": "refusal"}
    conn = db.connect()
    try:
        routed = route_tab(conn, body.tab, body.message)
        if routed is not None:
            proposal = routed.get("proposal")
            if proposal:
                proposal = _store_proposal(conn, proposal)
            return {
                "reply": routed["reply"],
                "proposal": proposal,
                "action": routed.get("action"),
                "sent": False,
                "source": "jarvis",
            }
        proposal = local_proposal(body.message)
        jarvis = jarvis_bridge.probe_jarvis()
        reply = (
            "I can save that after you confirm it."
            if proposal
            else (
                "Use the J.A.R.V.I.S. tab for open conversation. "
                "From any tab you can ask J.A.R.V.I.S. to use that tab's existing actions, "
                "or say note:, remember:, remind me:, or project: to stage a record."
                if jarvis["reachable"]
                else "Start J.A.R.V.I.S. with assistant/scripts/jarvis.sh start, then use the J.A.R.V.I.S. tab. "
                "Or type note:, remember:, remind me:, or project: to stage a record."
            )
        )
        sent = False
        provider = setting(conn, "provider", "off")
        consent = setting(conn, "consent", "0") == "1"
        model = setting(conn, "lmstudio_model", "")
        if provider == "lmstudio" and consent and model and not proposal:
            try:
                reply = complete_lmstudio(setting(conn, "lmstudio_url", LMSTUDIO_DEFAULT), model, body.message)
                sent = True
                reply = "Generated text, not a verified fact. " + reply
            except Exception:
                reply = "LM Studio did not answer. Nothing was saved."
        elif provider == "als" and consent and not proposal:
            token = setting(conn, "als_api_token", "")
            try:
                reply = complete_als_chat(
                    setting(conn, "als_url", ALS_DEFAULT),
                    token,
                    body.message,
                )
                sent = True
                reply = "Generated text via ALS, not a verified fact. " + reply
            except Exception as exc:
                reply = f"ALS did not answer ({exc}). Nothing was saved."
        if proposal:
            proposal = _store_proposal(conn, proposal)
        return {"reply": reply, "proposal": proposal, "action": None, "sent": sent}
    finally:
        conn.close()


@app.post("/api/assistant/proposals/{item_id}/confirm")
def confirm_proposal(item_id: int):
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM proposals WHERE id=? AND status='awaiting_approval'", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Nothing is waiting for approval")
        payload = json.loads(row["payload_json"])
        now = db.utcnow()
        if row["kind"] == "note":
            conn.execute("INSERT INTO notes (title, body, updated_at) VALUES (?, ?, ?)", (payload["title"], payload["body"], now))
        elif row["kind"] == "memory":
            conn.execute("INSERT INTO memories (title, body, updated_at) VALUES (?, ?, ?)", (payload["title"], payload["body"], now))
        elif row["kind"] == "reminder":
            conn.execute(
                "INSERT INTO reminders (title, body, due_at, recurrence, timezone, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (payload["title"], payload.get("body", ""), payload["due_at"], payload.get("recurrence", "none"), setting(conn, "timezone", local_tz_name()), now),
            )
        elif row["kind"] == "project":
            conn.execute(
                "INSERT INTO projects (title, body, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (payload["title"], payload.get("body", ""), payload.get("status", "active"), now, now),
            )
        else:
            raise HTTPException(400, "Unsupported proposal")
        conn.execute("UPDATE proposals SET status='complete' WHERE id=?", (item_id,))
        log_action(conn, "Approved change saved", "complete")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/assistant/proposals/{item_id}/reject")
def reject_proposal(item_id: int):
    conn = db.connect()
    try:
        conn.execute("UPDATE proposals SET status='failed' WHERE id=? AND status='awaiting_approval'", (item_id,))
        log_action(conn, "Change declined", "failed")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/repair")
def repair_status():
    return health()


@app.post("/api/repair/proposals")
def create_repair(body: RepairIn):
    diff = repair.propose_diff(body.explanation)
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO repair_proposals (explanation, diff, status, created_at) VALUES (?, ?, 'awaiting_approval', ?)",
            (body.explanation.strip(), diff, db.utcnow()),
        )
        log_action(conn, "Repair proposal waiting for approval", "awaiting_approval")
        conn.commit()
        return {"id": cur.lastrowid, "diff": diff, "status": "awaiting_approval"}
    finally:
        conn.close()


@app.post("/api/repair/proposals/{item_id}/approve")
def approve_repair(item_id: int):
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM repair_proposals WHERE id=? AND status='awaiting_approval'", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "No repair is waiting")
        path = repair.save_proposal(item_id, row["diff"])
        conn.execute("UPDATE repair_proposals SET status='complete', path=? WHERE id=?", (path, item_id))
        log_action(conn, "Repair diff saved. The program was not changed.", "complete")
        conn.commit()
        return {"ok": True, "path": path, "applied": False}
    finally:
        conn.close()


@app.post("/api/alerts/tick")
def alerts_tick():
    conn = db.connect()
    try:
        db.migrate(conn)
        use_gs = setting(conn, "gsconnect_push", "1") == "1"
        device = setting(conn, "gsconnect_device", "")
        sent = alerts.tick(conn, use_gs, device)
        if sent:
            log_action(conn, f"Dispatched {len(sent)} alert(s)", "complete")
        conn.commit()
        return {"sent": sent}
    finally:
        conn.close()


@app.post("/api/reminders/{item_id}/push")
def push_reminder_now(item_id: int):
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM reminders WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Reminder not found")
        result = push.push_alert(
            row["title"],
            row["body"] or "Reminder",
            setting(conn, "gsconnect_push", "1") == "1",
            setting(conn, "gsconnect_device", ""),
        )
        log_action(conn, "Reminder pushed to phone/desktop", "complete")
        conn.commit()
        return result.__dict__
    finally:
        conn.close()


@app.get("/api/gsconnect/devices")
def gsconnect_devices():
    devices = [
        {"path": path, "name": name, "connected": connected}
        for path, name, connected in push._list_gsconnect_devices()
    ]
    return {"items": devices}


@app.get("/api/jarvis/status")
def jarvis_status():
    return jarvis_bridge.probe_jarvis()


@app.get("/api/fasten/status")
def fasten_status():
    """Reachability for a local Fasten Health on-prem instance. Does not invent records."""
    import os

    url = os.environ.get("FASTEN_URL", "http://127.0.0.1:9091").rstrip("/")
    try:
        response = httpx.get(url, timeout=2.0, verify=False, follow_redirects=True)
    except httpx.HTTPError as exc:
        return {
            "reachable": False,
            "url": url,
            "detail": (
                "Fasten Health on-prem is not running on this computer. "
                "Start it with assistant/scripts/fasten.sh start. The section embeds http://127.0.0.1:9091."
            ),
        }
    if response.status_code >= 500:
        return {
            "reachable": False,
            "url": url,
            "detail": f"Fasten answered HTTP {response.status_code}.",
        }
    return {
        "reachable": True,
        "url": url,
        "detail": "Fasten Health on-prem is running.",
    }


def _jarvis_bridge_loopback_only(request: Request) -> None:
    client_ip = lan_access.client_ip_from_headers(
        request.client.host if request.client else "",
        request.headers.get("x-forwarded-for"),
    )
    if not (
        lan_access.is_loopback(client_ip)
        or lan_access.is_test_client(request.client.host if request.client else None)
    ):
        raise HTTPException(403, "Jarvis bridge is only available on this computer.")


@app.get("/api/jarvis-bridge/manifest")
def jarvis_bridge_manifest(request: Request):
    _jarvis_bridge_loopback_only(request)
    return jarvis_project.manifest()


@app.get("/api/jarvis-bridge/tree")
def jarvis_bridge_tree(request: Request, path: str = "."):
    _jarvis_bridge_loopback_only(request)
    try:
        return jarvis_project.list_tree(path)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/jarvis-bridge/file")
def jarvis_bridge_read_file(request: Request, path: str):
    _jarvis_bridge_loopback_only(request)
    try:
        return jarvis_project.read_text(path)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class JarvisBridgeWriteIn(BaseModel):
    path: str = Field(min_length=1, max_length=4000)
    content: str = Field(default="", max_length=2_000_000)


@app.put("/api/jarvis-bridge/file")
def jarvis_bridge_write_file(request: Request, body: JarvisBridgeWriteIn):
    _jarvis_bridge_loopback_only(request)
    try:
        return jarvis_project.write_text(body.path, body.content)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class LanPairIn(BaseModel):
    code: str
    device_label: str = "Phone"


@app.get("/api/lan/status")
def lan_status_endpoint():
    conn = db.connect()
    try:
        lan_access.cleanup_expired(conn)
        body = lan_access.lan_status(conn)
        body["sessions"] = [dict(row) for row in body["sessions"]]
        conn.commit()
        return body
    finally:
        conn.close()


@app.post("/api/lan/enable")
def lan_enable(request: Request):
    client_ip = lan_access.client_ip_from_headers(
        request.client.host if request.client else "",
        request.headers.get("x-forwarded-for"),
    )
    if not lan_access.is_loopback(client_ip):
        raise HTTPException(403, "Enable LAN access from this computer only.")
    conn = db.connect()
    try:
        result = lan_access.enable_lan(conn)
        conn.commit()
        return result
    finally:
        conn.close()


@app.post("/api/lan/disable")
def lan_disable(request: Request):
    client_ip = lan_access.client_ip_from_headers(
        request.client.host if request.client else "",
        request.headers.get("x-forwarded-for"),
    )
    if not lan_access.is_loopback(client_ip):
        raise HTTPException(403, "Disable LAN access from this computer only.")
    conn = db.connect()
    try:
        lan_access.disable_lan(conn)
        conn.commit()
        return {"ok": True, "enabled": False}
    finally:
        conn.close()


@app.post("/api/lan/pair")
def lan_pair(body: LanPairIn, request: Request):
    client_ip = lan_access.client_ip_from_headers(
        request.client.host if request.client else "",
        request.headers.get("x-forwarded-for"),
    )
    if not tunnel_access.allow_tunnel_pairing(client_ip, request):
        raise HTTPException(403, "Pairing is only allowed from the local network or an active mobile tunnel.")
    conn = db.connect()
    try:
        result = lan_access.pair_device(conn, body.code, body.device_label)
        conn.commit()
        return result
    finally:
        conn.close()


@app.delete("/api/lan/sessions/{session_id}")
def lan_revoke_session(session_id: int, request: Request, body: ConfirmBody):
    require_confirmed(body)
    client_ip = lan_access.client_ip_from_headers(
        request.client.host if request.client else "",
        request.headers.get("x-forwarded-for"),
    )
    if not lan_access.is_loopback(client_ip):
        raise HTTPException(403, "Revoke sessions from this computer only.")
    conn = db.connect()
    try:
        lan_access.revoke_session(conn, session_id)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/lan/sync/roots")
def lan_sync_roots():
    conn = db.connect()
    try:
        roots = lan_sync.sync_roots(conn)
        return {"roots": [str(root) for root in roots]}
    finally:
        conn.close()


@app.get("/api/lan/sync/list")
def lan_sync_list(path: str = ""):
    conn = db.connect()
    try:
        return lan_sync.list_sync_dir(conn, path)
    finally:
        conn.close()


@app.get("/api/lan/sync/file")
def lan_sync_download(path: str):
    conn = db.connect()
    try:
        target = lan_sync.resolve_sync_path(conn, path)
        if not target.is_file():
            raise HTTPException(404, "File not found.")
        meta = lan_sync.file_metadata(target)
        from fastapi.responses import FileResponse

        return FileResponse(target, filename=target.name, headers={"X-File-Sha256": meta["sha256"]})
    finally:
        conn.close()


class LanUploadIn(BaseModel):
    path: str
    sha256: str = ""
    size: int = 0
    overwrite: bool = False


@app.post("/api/lan/sync/upload-check")
def lan_upload_check(body: LanUploadIn):
    conn = db.connect()
    try:
        return lan_sync.prepare_upload(conn, body.path, body.sha256, body.size)
    finally:
        conn.close()


@app.get("/api/google/status")
def google_status():
    conn = db.connect()
    try:
        client_id = setting(conn, "google_client_id", "")
        refresh = setting(conn, "google_refresh_token", "")
        linked = bool(client_id and refresh)
        google_count = conn.execute(
            "SELECT COUNT(*) AS n FROM appointments WHERE source='google'"
        ).fetchone()["n"]
        return {
            "linked": linked,
            "client_id_set": bool(client_id),
            "events_cached": google_count,
            "redirect_uri": google_calendar.redirect_uri(),
            "scope": google_calendar.CALENDAR_SCOPE,
        }
    finally:
        conn.close()


@app.get("/api/google/auth/url")
def google_auth_url():
    conn = db.connect()
    try:
        client_id = setting(conn, "google_client_id", "")
        if not client_id:
            raise HTTPException(400, "Set a Google OAuth client ID in Settings first.")
        state = secrets.token_urlsafe(16)
        put_setting(conn, "google_oauth_state", state)
        conn.commit()
        return {"url": google_calendar.auth_url(client_id, state)}
    finally:
        conn.close()


@app.get("/api/google/callback")
def google_callback(code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse("http://localhost:9241/?view=settings&google=denied")
    conn = db.connect()
    try:
        expected = setting(conn, "google_oauth_state", "")
        client_id = setting(conn, "google_client_id", "")
        client_secret = setting(conn, "google_client_secret", "")
        if not code or state != expected or not client_id or not client_secret:
            raise HTTPException(400, "OAuth state did not match. Try linking again.")
        tokens = google_calendar.exchange_code(client_id, client_secret, code)
        refresh = tokens.get("refresh_token")
        if not refresh:
            raise HTTPException(400, "Google did not return a refresh token. Revoke access and try again.")
        put_setting(conn, "google_refresh_token", refresh)
        put_setting(conn, "google_oauth_state", "")
        log_action(conn, "Google Calendar linked", "complete")
        conn.commit()
        return RedirectResponse("http://localhost:9241/?view=settings&google=linked")
    finally:
        conn.close()


@app.post("/api/google/sync")
def google_sync():
    conn = db.connect()
    try:
        client_id = setting(conn, "google_client_id", "")
        client_secret = setting(conn, "google_client_secret", "")
        refresh = setting(conn, "google_refresh_token", "")
        if not (client_id and client_secret and refresh):
            raise HTTPException(400, "Link Google Calendar in Settings before syncing.")
        access = google_calendar.refresh_access_token(client_id, client_secret, refresh)
        start, end = google_calendar.sync_window()
        events = google_calendar.list_events(access, start, end)
        conn.execute("DELETE FROM appointments WHERE source='google'")
        now = db.utcnow()
        for event in events:
            if event["status"] == "cancelled":
                continue
            conn.execute(
                """INSERT INTO appointments
                (title, starts_at, ends_at, location, notes, reminder_offset_minutes, status, source, external_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 2880, 'scheduled', 'google', ?, ?, ?)""",
                (
                    event["title"],
                    event["starts_at"],
                    event["ends_at"],
                    event["location"],
                    event["notes"],
                    event["external_id"],
                    now,
                    now,
                ),
            )
        log_action(conn, f"Synced {len(events)} Google Calendar events", "complete")
        conn.commit()
        return {"imported": len(events)}
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Google Calendar error: {exc.response.status_code}") from exc
    finally:
        conn.close()


@app.get("/api/memories/search")
def search_memories(q: str = ""):
    conn = db.connect()
    try:
        like = f"%{q.strip()}%"
        rows = conn.execute(
            "SELECT id, title, body, updated_at FROM memories WHERE title LIKE ? OR body LIKE ? ORDER BY updated_at DESC",
            (like, like),
        )
        return {"items": [dict(row) for row in rows]}
    finally:
        conn.close()
