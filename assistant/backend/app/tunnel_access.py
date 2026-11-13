"""Internet tunnel exposure (ngrok): env flag and proxy-trust helpers."""

from __future__ import annotations

import os

from fastapi import Request

from . import lan_access

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def tunnel_mode() -> bool:
    return os.environ.get("ASSISTANT_TUNNEL_MODE", "").strip().lower() in _TRUTHY


def tunnel_origin() -> str:
    """Optional HTTPS origin for CORS (set by the mobile tunnel launcher)."""
    return os.environ.get("ASSISTANT_TUNNEL_ORIGIN", "").strip().rstrip("/")


def api_client_is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if lan_access.is_test_client(host):
        return True
    try:
        return lan_access.is_loopback(host)
    except Exception:
        return host in {"127.0.0.1", "::1", "localhost"}


def allow_public_client_ip(client_ip: str, request: Request) -> bool:
    """When the UI tunnel is on, only the local Vite proxy may reach the API with a public X-Forwarded-For."""
    if not lan_access.is_public_ip(client_ip):
        return True
    return tunnel_mode() and api_client_is_loopback(request)


def allow_tunnel_pairing(client_ip: str, request: Request) -> bool:
    if lan_access.is_likely_lan(client_ip) or lan_access.is_loopback(client_ip):
        return True
    if lan_access.is_test_client(request.client.host if request.client else None):
        return True
    return tunnel_mode() and api_client_is_loopback(request)
