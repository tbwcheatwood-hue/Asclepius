"""LAN pairing, session tokens, and CSRF for phone access on the local network only."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import secrets
import socket
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from . import db

SESSION_DAYS = 14
PAIRING_MINUTES = 10
TOKEN_HEADER = "x-assistant-lan-token"
CSRF_HEADER = "x-assistant-csrf"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def lan_enabled(conn: sqlite3.Connection | None = None) -> bool:
    own = conn is None
    if own:
        conn = db.connect()
    try:
        return setting(conn, "lan_enabled", "0") == "1"
    finally:
        if own:
            conn.close()


def client_ip_from_headers(host: str | None, forwarded_for: str | None) -> str:
    if host in {"127.0.0.1", "::1", "localhost"} and forwarded_for:
        hop = forwarded_for.split(",")[0].strip()
        if hop:
            return hop
    return host or ""


def is_test_client(host: str | None) -> bool:
    return host in {"testclient", "testserver"}


def is_loopback(ip: str) -> bool:
    if not ip:
        return True
    if ip == "localhost":
        return True
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def is_likely_lan(ip: str) -> bool:
    if is_loopback(ip):
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_private or addr.is_link_local:
        return True
    return False


def is_public_ip(ip: str) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local)


def lan_urls(port_ui: int = 9241) -> list[str]:
    urls: list[str] = []
    try:
        host = socket.gethostname()
        _, _, addresses = socket.gethostbyname_ex(host)
    except OSError:
        addresses = []
    for addr in addresses:
        if is_loopback(addr):
            continue
        if is_likely_lan(addr):
            urls.append(f"http://{addr}:{port_ui}")
    return urls


def cleanup_expired(conn: sqlite3.Connection) -> None:
    now = db.utcnow()
    conn.execute("DELETE FROM lan_pairing_codes WHERE expires_at < ?", (now,))
    conn.execute("DELETE FROM lan_sessions WHERE expires_at < ?", (now,))


def disable_lan(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('lan_enabled', '0') ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    )
    conn.execute("DELETE FROM lan_sessions")
    conn.execute("DELETE FROM lan_pairing_codes")
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('lan_pairing_code', '') ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    )
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('lan_pairing_expires', '') ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    )


def enable_lan(conn: sqlite3.Connection) -> dict:
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = utcnow() + timedelta(minutes=PAIRING_MINUTES)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('lan_enabled', '1') ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    )
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('lan_pairing_code', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (code,),
    )
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('lan_pairing_expires', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (expires.replace(microsecond=0).isoformat(),),
    )
    conn.execute(
        "INSERT INTO lan_pairing_codes (code, expires_at) VALUES (?, ?) ON CONFLICT(code) DO UPDATE SET expires_at = excluded.expires_at",
        (code, expires.replace(microsecond=0).isoformat()),
    )
    return {
        "pairing_code": code,
        "expires_at": expires.replace(microsecond=0).isoformat(),
        "urls": lan_urls(),
        "notice": "LAN access is limited to your network. No internet exposure or port forwarding is configured.",
    }


def lan_status(conn: sqlite3.Connection) -> dict:
    enabled = lan_enabled(conn)
    return {
        "enabled": enabled,
        "urls": lan_urls() if enabled else [],
        "pairing_code": setting(conn, "lan_pairing_code", "") if enabled else "",
        "pairing_expires": setting(conn, "lan_pairing_expires", "") if enabled else "",
        "sessions": conn.execute("SELECT id, device_label, created_at, expires_at FROM lan_sessions ORDER BY id DESC").fetchall(),
        "notice": (
            "Open one of the URLs on your phone, then enter the pairing code. "
            "Sessions expire after 14 days. Disable LAN access when you are done."
        ),
    }


def pair_device(conn: sqlite3.Connection, code: str, device_label: str) -> dict:
    if not lan_enabled(conn):
        raise HTTPException(403, "LAN access is disabled on this computer.")
    clean = re.sub(r"\D", "", code.strip())
    if len(clean) != 6:
        raise HTTPException(400, "Pairing code must be six digits.")
    row = conn.execute(
        "SELECT expires_at FROM lan_pairing_codes WHERE code = ?",
        (clean,),
    ).fetchone()
    if row is None:
        raise HTTPException(400, "Pairing code is not valid.")
    if datetime.fromisoformat(row["expires_at"]) < utcnow():
        raise HTTPException(400, "Pairing code expired. Generate a new code on the desktop.")
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expires = utcnow() + timedelta(days=SESSION_DAYS)
    label = (device_label or "Phone").strip()[:80] or "Phone"
    conn.execute(
        """INSERT INTO lan_sessions (token_hash, csrf_hash, device_label, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)""",
        (
            _hash(token),
            _hash(csrf),
            label,
            db.utcnow(),
            expires.replace(microsecond=0).isoformat(),
        ),
    )
    conn.execute("DELETE FROM lan_pairing_codes WHERE code = ?", (clean,))
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('lan_pairing_code', '') ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    )
    return {
        "token": token,
        "csrf_token": csrf,
        "expires_at": expires.replace(microsecond=0).isoformat(),
        "device_label": label,
    }


def session_from_token(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT * FROM lan_sessions WHERE token_hash = ?",
        (_hash(token),),
    ).fetchone()
    if row is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < utcnow():
        conn.execute("DELETE FROM lan_sessions WHERE id = ?", (row["id"],))
        return None
    return row


def verify_csrf(session: sqlite3.Row, csrf: str) -> bool:
    if not csrf:
        return False
    return secrets.compare_digest(_hash(csrf), session["csrf_hash"])


def revoke_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute("DELETE FROM lan_sessions WHERE id = ?", (session_id,))
