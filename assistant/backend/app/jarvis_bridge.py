"""Reachability checks for Personal Jarvis (headless web UI)."""

from __future__ import annotations

import os

import httpx

DEFAULT_JARVIS_PORT = 47821
DEFAULT_JARVIS_URL = f"http://127.0.0.1:{DEFAULT_JARVIS_PORT}"

ASSISTANT_ORIGINS = (
    "http://localhost:9241",
    "http://127.0.0.1:9241",
    "http://localhost:47821",
    "http://127.0.0.1:47821",
)


def jarvis_base_url() -> str:
    return os.environ.get("JARVIS_URL", DEFAULT_JARVIS_URL).rstrip("/")


def probe_jarvis(timeout: float = 12.0) -> dict:
    base = jarvis_base_url()
    try:
        response = httpx.get(f"{base}/api/health", timeout=timeout)
        response.raise_for_status()
        info = response.json()
        version = info.get("version")
        return {
            "reachable": True,
            "url": base,
            "web_app": f"{base}/",
            "version": str(version) if version is not None else None,
            "detail": "J.A.R.V.I.S. is running. Voice, agents, and tools use Personal Jarvis.",
        }
    except httpx.HTTPError as exc:
        return {
            "reachable": False,
            "url": base,
            "web_app": f"{base}/",
            "version": None,
            "detail": (
                f"J.A.R.V.I.S. is not reachable ({exc}). "
                "Run assistant/scripts/jarvis.sh install once, then jarvis.sh start."
            ),
        }
