import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

os.environ["ASSISTANT_DB"] = "/tmp/assistant-test.sqlite"
if os.path.exists(os.environ["ASSISTANT_DB"]):
    os.remove(os.environ["ASSISTANT_DB"])

from app.main import app  # noqa: E402
from app.providers import probe_als, probe_lmstudio  # noqa: E402
from app.repair import propose_diff, refuse_source_edit, save_proposal  # noqa: E402
from app.scheduling import (  # noqa: E402
    appointment_reminder_at,
    combine_local,
    low_supply,
    reminder_state,
)


@pytest.fixture(autouse=True)
def _lan_off():
    from app import db, lan_access

    conn = db.connect()
    try:
        lan_access.disable_lan(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def client():
    return TestClient(app)


def test_two_day_reminder_and_missed_state():
    start = datetime(2099, 1, 15, 15, 0, tzinfo=timezone.utc)
    due = appointment_reminder_at(start, 2880)
    assert due == start - timedelta(days=2)
    assert reminder_state(due, due - timedelta(minutes=1), False) == "upcoming"
    assert reminder_state(due, due + timedelta(minutes=1), False) == "missed"
    assert reminder_state(due, due + timedelta(days=3), True) == "done"


def test_dst_gap_moves_forward():
    zone = ZoneInfo("America/New_York")
    when, adjusted = combine_local(datetime(2026, 3, 8, tzinfo=zone), "02:30", zone)
    assert adjusted is True
    assert (when.hour, when.minute) == (3, 30)


def test_low_supply():
    assert low_supply(4, 5) is True
    assert low_supply(6, 5) is False
    assert low_supply(None, 5) is False


def test_persistence_and_medication_flow(client: TestClient):
    created = client.post(
        "/api/appointments",
        json={
            "title": "Clinic",
            "starts_at": "2099-06-01T15:00:00+00:00",
            "reminder_offset_minutes": 2880,
            "location": "Room 2",
            "notes": "",
        },
    )
    assert created.status_code == 200
    listed = client.get("/api/appointments")
    assert any(item["title"] == "Clinic" for item in listed.json()["items"])

    med = client.post(
        "/api/medications",
        json={"name": "Example tablet", "instructions": "as I wrote them", "supply_remaining": 3, "low_supply_threshold": 2, "times": ["08:00", "20:00"]},
    )
    assert med.status_code == 200
    dose = client.post(
        f"/api/medications/{med.json()['id']}/doses",
        json={"scheduled_for": "2099-06-01T12:00:00+00:00", "status": "taken"},
    )
    assert dose.status_code == 200
    again = client.get("/api/medications").json()["items"]
    saved = next(item for item in again if item["name"] == "Example tablet")
    assert saved["supply_remaining"] == 2
    assert saved["logs"][0]["status"] == "taken"

    note = client.post("/api/notes", json={"title": "Parking", "body": "Level 2"})
    assert note.status_code == 200
    edited = client.put(f"/api/notes/{note.json()['id']}", json={"title": "Parking", "body": "Level 3"})
    assert edited.status_code == 200
    exported = client.get("/api/export").json()
    assert any(item["body"] == "Level 3" for item in exported["notes"])
    assert (
        client.request(
            "DELETE",
            f"/api/notes/{note.json()['id']}",
            json={"confirmed": True},
        ).status_code
        == 200
    )
    blocked = client.post("/api/reminders/1/acknowledge", json={"confirmed": False})
    assert blocked.status_code == 400


def test_medical_advice_is_refused_and_writes_need_confirmation(client: TestClient):
    refused = client.post("/api/assistant/message", json={"message": "what dose should I take"})
    assert refused.status_code == 200
    assert refused.json()["proposal"] is None
    assert "can't give medication advice" in refused.json()["reply"]

    proposed = client.post("/api/assistant/message", json={"message": "note: keys are in the blue bowl"})
    proposal = proposed.json()["proposal"]
    assert proposal["status"] == "awaiting_approval"
    before = client.get("/api/notes").json()["items"]
    assert not any(item["body"] == "keys are in the blue bowl" for item in before)
    assert client.post(f"/api/assistant/proposals/{proposal['id']}/confirm").status_code == 200
    after = client.get("/api/notes").json()["items"]
    assert any(item["body"] == "keys are in the blue bowl" for item in after)


def test_provider_errors_do_not_invent_success():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http:
        status = probe_lmstudio("http://127.0.0.1:1234", http)
    assert status["state"] == "unreachable"
    assert status["models"] == []

    def als_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    with httpx.Client(transport=httpx.MockTransport(als_handler)) as http:
        als = probe_als("http://127.0.0.1:8888", client=http)
    assert als["chat"] is False
    assert als["state"] == "reachable"


def test_als_chat_requires_token():
    from app.providers import complete_als_chat

    with pytest.raises(ValueError):
        complete_als_chat("http://127.0.0.1:8888", "", "hello")


def test_jarvis_status_endpoint(client: TestClient):
    body = client.get("/api/jarvis/status").json()
    assert "reachable" in body
    assert "url" in body
    assert "web_app" in body


def test_jarvis_bridge_manifest(client: TestClient):
    body = client.get("/api/jarvis-bridge/manifest").json()
    assert "assistant_dir" in body
    assert body["api_url"].endswith("9242/")


def test_jarvis_bridge_file_roundtrip(client: TestClient):
    rel = "assistant/jarvis-integration/.jarvis-bridge-test.txt"
    payload = {"path": rel, "content": "jarvis bridge ok\n"}
    client.put("/api/jarvis-bridge/file", json=payload)
    body = client.get("/api/jarvis-bridge/file", params={"path": rel}).json()
    assert "jarvis bridge ok" in body["content"]
    from pathlib import Path

    Path(__file__).resolve().parents[2].joinpath("jarvis-integration", ".jarvis-bridge-test.txt").unlink(
        missing_ok=True
    )


def test_jarvis_bridge_rejects_escape(client: TestClient):
    bad = client.get("/api/jarvis-bridge/file", params={"path": "../../etc/passwd"})
    assert bad.status_code == 400


def test_dismissal_requires_confirmation(client: TestClient):
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(microsecond=0).isoformat()
    created = client.post(
        "/api/reminders",
        json={"title": "Dismiss me", "due_at": past, "recurrence": "none", "body": ""},
    )
    rid = created.json()["id"]
    assert client.post(f"/api/reminders/{rid}/acknowledge", json={"confirmed": False}).status_code == 400
    assert client.post(f"/api/reminders/{rid}/acknowledge", json={"confirmed": True}).status_code == 200


def test_fasten_status_reports_reachability(client: TestClient):
    body = client.get("/api/fasten/status").json()
    assert isinstance(body["reachable"], bool)
    assert body["url"].startswith("http")
    assert body["detail"]


def test_lan_loopback_via_vite_proxy_headers():
    from app import lan_access

    ip = lan_access.client_ip_from_headers("127.0.0.1", "127.0.0.1")
    assert ip == "127.0.0.1"
    assert lan_access.is_loopback(ip)


def test_lan_pairing_and_auth(client: TestClient):
    from app import lan_access

    conn = __import__("app.db", fromlist=["db"]).connect()
    try:
        lan_access.disable_lan(conn)
        conn.commit()
        info = lan_access.enable_lan(conn)
        conn.commit()
        code = info["pairing_code"]
    finally:
        conn.close()
    paired = client.post("/api/lan/pair", json={"code": code, "device_label": "Test phone"})
    assert paired.status_code == 200
    token = paired.json()["token"]
    csrf = paired.json()["csrf_token"]
    # Non-loopback requests without a token are rejected when LAN is enabled.
    denied = client.get("/api/reminders", headers={"x-forwarded-for": "192.168.1.50"})
    assert denied.status_code == 401
    ok = client.get(
        "/api/reminders",
        headers={
            "x-forwarded-for": "192.168.1.50",
            "x-assistant-lan-token": token,
        },
    )
    assert ok.status_code == 200
    blocked = client.post(
        "/api/reminders",
        headers={"x-forwarded-for": "192.168.1.50", "x-assistant-lan-token": token},
        json={"title": "x", "due_at": "2099-01-01T12:00:00+00:00", "recurrence": "none", "body": ""},
    )
    assert blocked.status_code == 403
    allowed = client.post(
        "/api/reminders",
        headers={
            "x-forwarded-for": "192.168.1.50",
            "x-assistant-lan-token": token,
            "x-assistant-csrf": csrf,
        },
        json={"title": "LAN ok", "due_at": "2099-01-02T12:00:00+00:00", "recurrence": "none", "body": ""},
    )
    assert allowed.status_code == 200
    conn = __import__("app.db", fromlist=["db"]).connect()
    try:
        lan_access.disable_lan(conn)
        conn.commit()
    finally:
        conn.close()


def test_lan_sync_path_traversal(client: TestClient):
    from app import db, lan_access

    conn = db.connect()
    try:
        lan_access.disable_lan(conn)
        code = lan_access.enable_lan(conn)["pairing_code"]
        conn.commit()
    finally:
        conn.close()
    paired = client.post("/api/lan/pair", json={"code": code, "device_label": "t"})
    assert paired.status_code == 200
    token = paired.json()["token"]
    bad = client.get(
        "/api/lan/sync/list",
        params={"path": "../../etc/passwd"},
        headers={"x-forwarded-for": "192.168.1.2", "x-assistant-lan-token": token},
    )
    assert bad.status_code in {400, 403}
    conn = db.connect()
    try:
        lan_access.disable_lan(conn)
        conn.commit()
    finally:
        conn.close()


def test_alerts_tick_dispatches_once(client: TestClient, monkeypatch):
    from app import notifications

    calls: list[str] = []

    def fake_push(title: str, body: str, use_gs: bool, device: str) -> notifications.PushResult:
        calls.append(title)
        return notifications.PushResult(True, False, "", "ok")

    monkeypatch.setattr("app.alerts.push_alert", fake_push)
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(microsecond=0).isoformat()
    created = client.post(
        "/api/reminders",
        json={"title": "Water plants", "due_at": past, "recurrence": "none", "body": ""},
    )
    assert created.status_code == 200
    first = client.post("/api/alerts/tick")
    assert first.status_code == 200
    first_sent = first.json()["sent"]
    assert any(item["title"] == "Water plants" for item in first_sent)
    assert "Water plants" in calls
    second = client.post("/api/alerts/tick")
    assert not any(item["title"] == "Water plants" for item in second.json()["sent"])


def test_repair_cannot_edit_the_program(tmp_path, monkeypatch):
    import app.repair as repair_mod

    monkeypatch.setattr(repair_mod, "REPAIR_DIR", tmp_path)
    diff = propose_diff("Explain the empty notes list")
    path = save_proposal(4, diff)
    assert path.endswith("proposal-4.diff")
    assert "not applied" in open(path, encoding="utf-8").read()
    with pytest.raises(PermissionError):
        refuse_source_edit()
