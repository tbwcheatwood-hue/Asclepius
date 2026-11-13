import os

import pytest
from starlette.requests import Request

os.environ["ASSISTANT_DB"] = "/tmp/assistant-tunnel-test.sqlite"

from app import db, lan_access, tunnel_access  # noqa: E402
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean_db():
    path = os.environ["ASSISTANT_DB"]
    if os.path.exists(path):
        os.remove(path)
    conn = db.connect()
    db.migrate(conn)
    lan_access.disable_lan(conn)
    conn.commit()
    conn.close()
    yield


def test_public_ip_blocked_without_tunnel(monkeypatch):
    monkeypatch.delenv("ASSISTANT_TUNNEL_MODE", raising=False)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/health",
        "headers": [],
        "client": ("203.0.113.10", 12345),
    }
    request = Request(scope)
    assert not tunnel_access.allow_public_client_ip("8.8.8.8", request)


def test_tunnel_mode_allows_public_when_api_is_loopback(monkeypatch):
    monkeypatch.setenv("ASSISTANT_TUNNEL_MODE", "1")
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/health",
        "headers": [],
        "client": ("127.0.0.1", 9242),
    }
    request = Request(scope)
    assert tunnel_access.allow_public_client_ip("203.0.113.10", request)


@pytest.fixture()
def client(_clean_db):
    from app.main import app

    return TestClient(app)


def test_pair_via_proxy_client_in_tunnel_mode(monkeypatch, client: TestClient):
    monkeypatch.setenv("ASSISTANT_TUNNEL_MODE", "1")
    conn = db.connect()
    try:
        out = lan_access.enable_lan(conn)
        conn.commit()
        code = out["pairing_code"]
    finally:
        conn.close()
    response = client.post(
        "/api/lan/pair",
        json={"code": code, "device_label": "Phone"},
        headers={"x-forwarded-for": "203.0.113.55"},
    )
    assert response.status_code == 200
    assert "token" in response.json()
