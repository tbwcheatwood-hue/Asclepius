"""Optional Google Calendar read sync. Credentials stay in local SQLite settings."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
REDIRECT_DEFAULT = "http://127.0.0.1:9242/api/google/callback"


def redirect_uri() -> str:
    return os.environ.get("GOOGLE_REDIRECT_URI", REDIRECT_DEFAULT)


def auth_url(client_id: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": CALENDAR_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH}?{urlencode(params)}"


def exchange_code(client_id: str, client_secret: str, code: str) -> dict[str, Any]:
    response = httpx.post(
        GOOGLE_TOKEN,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri(),
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return response.json()


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    response = httpx.post(
        GOOGLE_TOKEN,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def list_events(access_token: str, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
    params = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": time_min.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "timeMax": time_max.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "maxResults": 250,
    }
    response = httpx.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        headers={"Authorization": f"Bearer {access_token}"},
        params=params,
        timeout=30.0,
    )
    response.raise_for_status()
    items = response.json().get("items") or []
    parsed: list[dict[str, Any]] = []
    for item in items:
        start = item.get("start", {})
        end = item.get("end", {})
        start_raw = start.get("dateTime") or start.get("date")
        end_raw = end.get("dateTime") or end.get("date")
        if not start_raw:
            continue
        if "T" not in start_raw:
            start_raw = f"{start_raw}T00:00:00+00:00"
        if end_raw and "T" not in end_raw:
            end_raw = f"{end_raw}T23:59:59+00:00"
        parsed.append(
            {
                "external_id": item.get("id", ""),
                "title": item.get("summary") or "(No title)",
                "starts_at": datetime.fromisoformat(start_raw.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(),
                "ends_at": datetime.fromisoformat(end_raw.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
                if end_raw
                else None,
                "location": item.get("location") or "",
                "notes": item.get("description") or "",
                "source": "google",
                "status": "cancelled" if item.get("status") == "cancelled" else "scheduled",
            }
        )
    return parsed


def sync_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    return now - timedelta(days=7), now + timedelta(days=120)
