"""SQLite storage. Migrations are versioned and run on startup."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "assistant.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  starts_at TEXT NOT NULL,
  ends_at TEXT,
  location TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  reminder_offset_minutes INTEGER NOT NULL DEFAULT 2880,
  status TEXT NOT NULL DEFAULT 'scheduled',
  acknowledged INTEGER NOT NULL DEFAULT 0,
  is_demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS medications (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  instructions TEXT NOT NULL DEFAULT '',
  supply_remaining INTEGER,
  low_supply_threshold INTEGER,
  times_json TEXT NOT NULL,
  timezone TEXT NOT NULL,
  is_demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dose_logs (
  id INTEGER PRIMARY KEY,
  medication_id INTEGER NOT NULL,
  scheduled_for TEXT NOT NULL,
  status TEXT NOT NULL,
  logged_at TEXT NOT NULL,
  FOREIGN KEY (medication_id) REFERENCES medications(id)
);
CREATE TABLE IF NOT EXISTS reminders (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  due_at TEXT NOT NULL,
  recurrence TEXT NOT NULL DEFAULT 'none',
  timezone TEXT NOT NULL,
  acknowledged INTEGER NOT NULL DEFAULT 0,
  is_demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY,
  summary TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repair_proposals (
  id INTEGER PRIMARY KEY,
  explanation TEXT NOT NULL,
  diff TEXT NOT NULL,
  status TEXT NOT NULL,
  path TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_dispatches (
  due_key TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  ref_id INTEGER NOT NULL,
  sent_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    path = Path(os.environ.get("ASSISTANT_DB", DEFAULT_DB))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    version = int(row["version"]) if row else 0
    if version == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        version = 1
    if version < 2:
        cols = _column_names(conn, "appointments")
        if "source" not in cols:
            conn.execute("ALTER TABLE appointments ADD COLUMN source TEXT NOT NULL DEFAULT 'local'")
        if "external_id" not in cols:
            conn.execute("ALTER TABLE appointments ADD COLUMN external_id TEXT")
        conn.execute("UPDATE schema_version SET version = 2")
        version = 2
    if version < 3:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
              id INTEGER PRIMARY KEY,
              title TEXT NOT NULL,
              body TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('voice_speak_replies', '1') ON CONFLICT(key) DO NOTHING"
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('butler_mode', '0') ON CONFLICT(key) DO NOTHING"
        )
        home = Path.home()
        default_roots = f"{home / 'Documents'}\n{home}"
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('file_search_roots', ?) ON CONFLICT(key) DO NOTHING",
            (default_roots,),
        )
        conn.execute("UPDATE schema_version SET version = 3")
        version = 3
    if version < 4:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS lan_sessions (
              id INTEGER PRIMARY KEY,
              token_hash TEXT NOT NULL UNIQUE,
              csrf_hash TEXT NOT NULL,
              device_label TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS lan_pairing_codes (
              code TEXT PRIMARY KEY,
              expires_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('lan_enabled', '0') ON CONFLICT(key) DO NOTHING"
        )
        conn.execute("UPDATE schema_version SET version = 4")
    conn.commit()


def seed_demo(conn: sqlite3.Connection, timezone_name: str) -> None:
    if conn.execute("SELECT COUNT(*) AS n FROM appointments").fetchone()["n"]:
        return
    now = utcnow()
    conn.execute(
        """INSERT INTO appointments
        (title, starts_at, ends_at, location, notes, reminder_offset_minutes, status, is_demo, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 2880, 'scheduled', 1, ?, ?)""",
        (
            "Sample: pharmacy pickup",
            "2099-01-15T15:00:00+00:00",
            "2099-01-15T15:30:00+00:00",
            "Front counter",
            "Demo record. Delete sample data when you no longer want it.",
            now,
            now,
        ),
    )
    conn.execute(
        """INSERT INTO medications
        (name, instructions, supply_remaining, low_supply_threshold, times_json, timezone, is_demo, created_at)
        VALUES (?, ?, 6, 5, ?, ?, 1, ?)""",
        (
            "Sample vitamin",
            "User-entered example only. This is not a dose recommendation.",
            json.dumps(["08:00"]),
            timezone_name,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('timezone', ?) ON CONFLICT(key) DO NOTHING",
        (timezone_name,),
    )
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('provider', 'off') ON CONFLICT(key) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('gsconnect_push', '1') ON CONFLICT(key) DO NOTHING"
    )
    conn.commit()
