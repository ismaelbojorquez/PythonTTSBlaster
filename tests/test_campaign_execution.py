import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from blaster.config import Settings
from blaster.models import CampaignInput, Contact
from blaster.store import Store
from blaster.web import create_app

CAMPAIGN = {
    "name": "Campaña de prueba",
    "template": "Hola {Nombre completo}",
    "country": "MX",
    "agent_numbers_text": "5550000199",
    "csv_text": "Credito,telefono,Nombre completo\nEXEC-1,5550000101,Ana\nEXEC-2,5550000102,Luis",
}


def make_app(tmp_path, enabled=True):
    return create_app(
        Settings(
            data_dir=tmp_path,
            auth={"enabled": False},
            automation={"enabled": enabled, "poll_seconds": 60},
            recordings={"enabled": False},
            choice_timeout=20,
        )
    )


def future():
    return (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0).isoformat()


def test_legacy_and_explicit_drafts_do_not_start_or_schedule(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        for payload in [CAMPAIGN, {**CAMPAIGN, "execution": "draft"}]:
            result = client.post("/api/campaigns", json=payload)
            assert result.status_code == 201, result.text
            assert result.json()["execution"] == "draft"
        assert len(client.get("/api/campaigns").json()) == 2
        assert all(c["display_status"] == "draft" for c in client.get("/api/campaigns").json())
        assert client.get("/api/manage/schedules").json() == []
        assert client.get("/api/status").json()["active_campaign"] is None


def test_create_and_start_runs_once_without_another_start_request(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/campaigns", json={**CAMPAIGN, "execution": "now"})
        assert created.status_code == 201, created.text
        cid = created.json()["id"]
        assert created.json()["execution"] == "now"
        assert client.get("/api/status").json()["active_campaign"] == cid
        assert client.get("/api/campaigns").json()[0]["status"] == "running"
        assert client.get("/api/manage/schedules").json() == []
        blocked = client.post("/api/campaigns", json={**CAMPAIGN, "execution": "now"})
        assert blocked.status_code == 422 and "campaña actual" in blocked.json()["detail"]
        assert len(client.get("/api/campaigns").json()) == 1
        assert client.post(f"/api/campaigns/{cid}/stop", json={}).status_code == 200


def test_no_route_does_not_create_an_unwanted_draft(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        app.state.engine.telephony.available = False
        result = client.post("/api/campaigns", json={**CAMPAIGN, "execution": "now"})
        assert result.status_code == 422 and "troncal" in result.json()["detail"]
        assert client.get("/api/campaigns").json() == []


def test_last_minute_start_failure_returns_the_saved_campaign_id(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    with TestClient(app) as client:

        def fail(cid):
            raise ValueError("La troncal se desconectó")

        monkeypatch.setattr(app.state.engine, "start_campaign", fail)
        result = client.post("/api/campaigns", json={**CAMPAIGN, "execution": "now"})
        assert result.status_code == 201
        assert result.json()["execution"] == "draft"
        assert result.json()["start_error"] == "La troncal se desconectó"
        assert client.get("/api/campaigns").json()[0]["id"] == result.json()["id"]


def test_schedule_is_saved_with_campaign_and_dispatches_only_when_due(tmp_path):
    app = make_app(tmp_path)
    due = future()
    with TestClient(app) as client:
        created = client.post(
            "/api/campaigns",
            json={
                **CAMPAIGN,
                "execution": "scheduled",
                "local_at": due,
                "schedule_timezone": "America/Mexico_City",
            },
        )
        assert created.status_code == 201, created.text
        cid = created.json()["id"]
        assert created.json()["schedule"]["due_at"] == due
        row = client.get("/api/campaigns").json()[0]
        assert row["display_status"] == "scheduled" and row["status"] == "draft"
        assert row["schedule"]["timezone"] == "America/Mexico_City"
        assert client.get("/api/status").json()["active_campaign"] is None
        client.portal.call(
            app.state.automation.tick, datetime.fromisoformat(due) - timedelta(seconds=1)
        )
        assert client.get("/api/status").json()["active_campaign"] is None
        client.portal.call(app.state.automation.tick, datetime.fromisoformat(due))
        assert client.get("/api/status").json()["active_campaign"] == cid
        assert client.get("/api/manage/schedules").json()[0]["state"] == "started"
        client.portal.call(app.state.automation.tick, datetime.fromisoformat(due))
        assert len(client.get("/api/manage/schedules").json()) == 1
        assert client.post(f"/api/campaigns/{cid}/stop", json={}).status_code == 200


def test_saved_draft_can_be_scheduled_from_its_detail_with_audit(tmp_path):
    app = make_app(tmp_path)
    due = future()
    with TestClient(app) as client:
        cid = client.post("/api/campaigns", json=CAMPAIGN).json()["id"]
        scheduled = client.post(
            "/api/manage/schedules",
            json={"campaign_id": cid, "local_at": due, "timezone": "UTC"},
        )
        assert scheduled.status_code == 200, scheduled.text
        assert scheduled.json()["timezone"] == "UTC"
        campaign = client.get("/api/campaigns").json()[0]
        assert campaign["status"] == "draft"
        assert campaign["display_status"] == "scheduled"
        assert campaign["schedule"]["due_at"] == due
        audit = client.portal.call(
            lambda: app.state.store.db.execute(
                "SELECT detail FROM audit WHERE action='campaign.scheduled_from_draft' "
                "AND target=?",
                (cid,),
            ).fetchone()
        )
        assert audit is not None and due in audit["detail"]


def test_only_unstarted_drafts_can_be_scheduled_and_automation_must_be_on(tmp_path):
    disabled = make_app(tmp_path, enabled=False)
    with TestClient(disabled) as client:
        cid = client.post("/api/campaigns", json=CAMPAIGN).json()["id"]
        result = client.post(
            "/api/manage/schedules",
            json={"campaign_id": cid, "local_at": future(), "timezone": "UTC"},
        )
        assert result.status_code == 422 and "Activa" in result.json()["detail"]
        assert client.get("/api/campaigns").json()[0]["schedule"] is None

    enabled = make_app(tmp_path / "started")
    with TestClient(enabled) as client:
        cid = client.post("/api/campaigns", json={**CAMPAIGN, "execution": "now"}).json()["id"]
        result = client.post(
            "/api/manage/schedules",
            json={"campaign_id": cid, "local_at": future(), "timezone": "UTC"},
        )
        assert result.status_code == 422 and "borrador" in result.json()["detail"]
        client.post(f"/api/campaigns/{cid}/stop", json={})


@pytest.mark.parametrize(
    "fields",
    [
        {"local_at": "2020-01-01T12:00", "schedule_timezone": "UTC"},
        {"local_at": "", "schedule_timezone": "UTC"},
        {"local_at": "2030-01-01T12:00", "schedule_timezone": ""},
        {"local_at": "2030-01-01T12:00", "schedule_timezone": "No/existe"},
        {"local_at": "2030-03-10T02:30", "schedule_timezone": "America/New_York"},
        {"local_at": "2030-11-03T01:30", "schedule_timezone": "America/New_York"},
    ],
)
def test_bad_schedule_never_leaves_partial_campaigns(tmp_path, fields):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        result = client.post(
            "/api/campaigns",
            json={
                **CAMPAIGN,
                "execution": "scheduled",
                **fields,
            },
        )
        assert result.status_code == 422, result.text
        assert client.get("/api/campaigns").json() == []
        assert client.get("/api/manage/schedules").json() == []


def test_disabled_automation_and_preview_do_not_schedule(tmp_path):
    app = make_app(tmp_path, enabled=False)
    with TestClient(app) as client:
        payload = {**CAMPAIGN, "execution": "scheduled"}
        assert client.post("/api/preview", json=payload).status_code == 200
        assert client.post("/api/campaigns", json=payload).status_code == 422
        assert client.get("/api/campaigns").json() == []
        assert client.get("/api/status").json()["automation_enabled"] is False


def test_schedule_persists_after_reopening_and_manual_start_cancels_it(tmp_path):
    payload = {
        **CAMPAIGN,
        "execution": "scheduled",
        "local_at": future(),
        "schedule_timezone": "UTC",
    }
    with TestClient(make_app(tmp_path)) as client:
        cid = client.post("/api/campaigns", json=payload).json()["id"]
    with TestClient(make_app(tmp_path)) as client:
        assert client.get("/api/campaigns").json()[0]["schedule"]["timezone"] == "UTC"
        assert client.post(f"/api/campaigns/{cid}/start", json={}).status_code == 200
        assert client.get("/api/manage/schedules").json()[0]["state"] == "cancelled"
        assert client.get("/api/campaigns").json()[0]["schedule"] is None
        client.post(f"/api/campaigns/{cid}/stop", json={})


def test_schedule_database_failure_rolls_back_contacts_and_campaign(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    try:
        payload = CampaignInput(
            name="Atómica", template="Hola", agent_number="999",
            contacts=[Contact(phone="123", credit_id="CRED-123")]
        )
        with pytest.raises(sqlite3.IntegrityError):
            store.create_campaign(payload, schedule={"due_at": None, "timezone": "UTC"})
        assert store.campaigns() == []
        assert store.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    finally:
        store.close()
