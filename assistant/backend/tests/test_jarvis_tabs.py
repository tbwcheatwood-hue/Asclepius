import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ASSISTANT_DB", "/tmp/assistant-test.sqlite")

from app.jarvis_tabs import TABS, route_tab  # noqa: E402
from app.main import app  # noqa: E402
from app import db  # noqa: E402


@pytest.fixture(autouse=True)
def _lan_off():
    from app import lan_access

    conn = db.connect()
    try:
        db.migrate(conn)
        lan_access.disable_lan(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def client():
    return TestClient(app)


def test_visible_status_uses_dotted_name():
    from app.jarvis_bridge import probe_jarvis

    detail = probe_jarvis(timeout=0.2)["detail"]
    assert "J.A.R.V.I.S." in detail
    assert "JARVIS is" not in detail


def test_help_covers_every_tab(client: TestClient):
    for tab in TABS:
        body = client.post("/api/assistant/message", json={"message": "what can you do", "tab": tab}).json()
        assert body["action"] is None
        assert body["proposal"] is None
        assert "J.A.R.V.I.S." in body["reply"]
        assert body["reply"]


def test_list_reminders_from_another_tab_uses_stored_rows(client: TestClient):
    created = client.post(
        "/api/reminders",
        json={"title": "Call the pharmacy", "due_at": "2001-01-01T15:00:00+00:00", "recurrence": "none", "body": ""},
    )
    assert created.status_code == 200
    listed = client.post(
        "/api/assistant/message",
        json={"message": "list reminders", "tab": "calendar"},
    ).json()
    assert "Call the pharmacy" in listed["reply"]
    assert listed["action"] is None


def test_delete_waits_for_the_existing_confirm_route(client: TestClient):
    created = client.post(
        "/api/notes",
        json={"title": "Garage code", "body": "posted on the bench"},
    )
    note_id = created.json()["id"]
    routed = client.post(
        "/api/assistant/message",
        json={"message": "delete note Garage code", "tab": "notes"},
    ).json()
    assert routed["action"]["confirm"] is True
    assert routed["action"]["path"] == f"/api/notes/{note_id}"
    assert routed["action"]["method"] == "DELETE"
    still = client.get("/api/notes").json()["items"]
    assert any(item["id"] == note_id for item in still)
    blocked = client.request("DELETE", f"/api/notes/{note_id}", json={"confirmed": False})
    assert blocked.status_code == 400
    deleted = client.request("DELETE", routed["action"]["path"], json=routed["action"]["body"])
    assert deleted.status_code == 200
    assert all(item["id"] != note_id for item in client.get("/api/notes").json()["items"])


def test_google_appointment_is_not_cancelled(client: TestClient):
    created = client.post(
        "/api/appointments",
        json={"title": "Cardiologist", "starts_at": "2099-06-01T15:00:00+00:00", "location": "", "notes": ""},
    )
    assert created.status_code == 200
    conn = db.connect()
    try:
        conn.execute("UPDATE appointments SET source='google' WHERE title='Cardiologist'")
        conn.commit()
        routed = route_tab(conn, "today", "cancel appointment Cardiologist")
    finally:
        conn.close()
    assert routed is not None
    assert routed["action"] is None
    assert "read-only" in routed["reply"]
    still = client.get("/api/appointments").json()["items"]
    assert any(item["title"] == "Cardiologist" and item["status"] == "scheduled" for item in still)


def test_medication_advice_stays_refused_and_record_log_is_not_written(client: TestClient):
    refused = client.post("/api/assistant/message", json={"message": "what dose should I take", "tab": "medications"})
    assert "can't give medication advice" in refused.json()["reply"]
    created = client.post(
        "/api/medications",
        json={"name": "Jarvis record tablet", "instructions": "as written", "times": ["08:00"]},
    )
    med_id = created.json()["id"]
    routed = client.post(
        "/api/assistant/message",
        json={"message": "log medication Jarvis record tablet as taken", "tab": "settings"},
    ).json()
    assert routed["action"]["confirm"] is True
    assert routed["action"]["path"] == f"/api/medications/{med_id}/doses"
    logs = client.get("/api/medications").json()["items"]
    match = next(item for item in logs if item["id"] == med_id)
    assert match["logs"] == []


def test_fasten_check_does_not_invent_records(client: TestClient):
    body = client.post("/api/assistant/message", json={"message": "check fasten", "tab": "memory"}).json()
    assert body["action"]["path"] == "/api/fasten/status"
    assert body["action"]["confirm"] is False
    assert "does not read health records" in body["reply"]


def test_unrecognized_request_does_not_claim_success(client: TestClient):
    body = client.post(
        "/api/assistant/message",
        json={"message": "please book a flight", "tab": "today"},
    ).json()
    assert body["action"] is None
    assert body["proposal"] is None
    assert "J.A.R.V.I.S." in body["reply"]
