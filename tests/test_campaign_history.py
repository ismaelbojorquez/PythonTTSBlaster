import json
import sqlite3
from uuid import uuid4

import pytest
from conftest import remove_retries_schema
from fastapi.testclient import TestClient
from test_campaign_execution import CAMPAIGN, future, make_app
from test_management import ADMIN, app_for, setup

from blaster.store import Store, now


def payload(**fields):
    return {"request_id": str(uuid4()), "note": "Segundo envío solicitado", **fields}


def finish_source(app, client):
    cid = client.post("/api/campaigns", json=CAMPAIGN).json()["id"]
    client.post(f"/api/campaigns/{cid}/stop", json={})

    def evidence():
        jid = app.state.store.jobs(cid)[0]["id"]
        app.state.store.begin_call(jid, False)
        app.state.store.update_call(jid, finalized_at=now(), end_actor="customer")

    client.portal.call(evidence)
    return cid


def test_rerun_preserves_previous_jobs_cdr_and_audits_independent_execution(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        cid = finish_source(app, client)
        before = client.get(f"/api/campaigns/{cid}/jobs").json()
        request = payload()
        response = client.post(f"/api/campaigns/{cid}/rerun", json=request)
        assert response.status_code == 201, response.text
        new_id = response.json()["id"]
        assert new_id != cid
        assert client.get("/api/status").json()["active_campaign"] == new_id
        rows = client.get(f"/api/campaigns/{new_id}/jobs").json()
        for old, new in zip(before, rows, strict=True):
            assert old["id"] != new["id"]
            for field in ("phone", "message", "variables"):
                assert old[field] == new[field]
        assert client.get(f"/api/campaigns/{cid}/jobs").json() == before
        history = client.get(f"/api/campaigns/{cid}/history").json()
        assert history["total"] == 2
        assert history["items"][0]["execution_number"] == 2
        assert history["items"][0]["actor_name"] == "local"
        assert history["items"][0]["started_by"] == "local"
        assert history["items"][0]["note"] == request["note"]
        with sqlite3.connect(tmp_path / "blaster.sqlite3") as db:
            assert db.execute(
                "SELECT COUNT(*) FROM call_records WHERE job_id=?", (before[0]["id"],)
            ).fetchone()[0] == 1
            audit = db.execute(
                "SELECT action,detail FROM audit WHERE target=?", (new_id,)
            ).fetchall()
            assert {r[0] for r in audit} >= {
                "campaign.rerun_created", "campaign.start_requested", "campaign.rerun_started",
            }
            details = json.loads(audit[0][1])
            assert details["source_id"] == cid and details["contacts"] == 2
        retry = client.post(f"/api/campaigns/{cid}/rerun", json=request)
        assert retry.status_code == 201 and retry.json()["id"] == new_id
        assert retry.json()["replayed"] is True
        assert len(client.get("/api/campaigns").json()) == 2
        assert client.post(f"/api/campaigns/{cid}/rerun", json=payload()).status_code == 422
        client.post(f"/api/campaigns/{new_id}/stop", json={})
        third = client.post(f"/api/campaigns/{new_id}/rerun", json=payload()).json()["id"]
        lineage = client.get(f"/api/campaigns/{third}/history").json()["lineage"]
        assert lineage["root_id"] == cid and lineage["source_id"] == new_id
        assert lineage["execution_number"] == 3
        client.post(f"/api/campaigns/{third}/stop", json={})


def test_duplicate_is_an_independent_draft_with_no_schedule_or_previous_results(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        cid = client.post("/api/campaigns", json={
            **CAMPAIGN, "execution": "scheduled", "local_at": future(),
            "schedule_timezone": "UTC",
        }).json()["id"]
        request = payload(name="Nueva copia")
        copied = client.post(f"/api/campaigns/{cid}/duplicate", json=request)
        assert copied.status_code == 201, copied.text
        new_id = copied.json()["id"]
        new = next(c for c in client.get("/api/campaigns").json() if c["id"] == new_id)
        assert new["name"] == "Nueva copia" and new["status"] == "draft"
        assert new["schedule"] is None and new["counts"] == {"queued": 2}
        assert new["lineage"]["root_id"] == new_id
        assert new["lineage"]["source_id"] == cid
        assert client.get(f"/api/campaigns/{new_id}/history").json()["total"] == 1
        assert client.get("/api/status").json()["active_campaign"] is None
        assert len(client.get("/api/manage/schedules").json()) == 1
        client.post(f"/api/campaigns/{cid}/duplicate", json=request)
        assert len(client.get("/api/campaigns").json()) == 2
        assert client.post(
            f"/api/campaigns/{cid}/duplicate", json={**request, "name": "Distinta"}
        ).status_code == 422


def test_rerun_requires_finished_source_same_mode_and_available_engine(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        cid = client.post("/api/campaigns", json=CAMPAIGN).json()["id"]
        assert client.post(f"/api/campaigns/{cid}/rerun", json=payload()).status_code == 422
        client.post(f"/api/campaigns/{cid}/stop", json={})
        app.state.engine.telephony.available = False
        assert client.post(f"/api/campaigns/{cid}/rerun", json=payload()).status_code == 422
        app.state.engine.telephony.available = True

        def mode_change():
            with app.state.store.db:
                app.state.store.db.execute("UPDATE campaigns SET mode='sip' WHERE id=?", (cid,))

        client.portal.call(mode_change)
        assert client.post(f"/api/campaigns/{cid}/rerun", json=payload()).status_code == 422
        assert len(client.get("/api/campaigns").json()) == 1
        assert client.post(f"/api/campaigns/{cid}/duplicate", json=payload()).status_code == 201


def test_late_start_failure_keeps_draft_and_never_retries_calls(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        cid = finish_source(app, client)
        real_start = app.state.engine.start_campaign

        def fail(cid):
            raise ValueError("La troncal se desconectó")

        monkeypatch.setattr(app.state.engine, "start_campaign", fail)
        request = payload()
        response = client.post(f"/api/campaigns/{cid}/rerun", json=request)
        assert response.status_code == 201 and response.json()["start_error"]
        new_id = response.json()["id"]
        monkeypatch.setattr(app.state.engine, "start_campaign", real_start)
        replay = client.post(f"/api/campaigns/{cid}/rerun", json=request)
        assert replay.json()["id"] == new_id and replay.json()["replayed"]
        assert client.get("/api/status").json()["active_campaign"] is None
        assert client.post(f"/api/campaigns/{cid}/rerun", json=payload()).status_code == 422
        assert client.post(f"/api/campaigns/{new_id}/start", json={}).status_code == 200
        client.post(f"/api/campaigns/{new_id}/stop", json={})


def test_copy_transaction_rolls_back_if_audit_fails(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    from blaster.models import CampaignInput, Contact

    cid = store.create_campaign(CampaignInput(
        name="Original", template="Hola", agent_number="999",
        contacts=[Contact(phone="123", credit_id="CRED-123")],
    ))
    store.db.execute("CREATE TRIGGER fail_copy_audit BEFORE INSERT ON audit "
                     "BEGIN SELECT RAISE(ABORT,'audit unavailable'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.history.copy(cid, "duplicate", "Copia", "", str(uuid4()), {}, "simulation", "hash")
    assert len(store.campaigns()) == 1
    assert store.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert store.db.execute("SELECT COUNT(*) FROM campaign_copies").fetchone()[0] == 0
    store.close()


def test_copy_request_survives_application_restart(tmp_path):
    request = payload()
    with TestClient(make_app(tmp_path)) as client:
        cid = client.post("/api/campaigns", json=CAMPAIGN).json()["id"]
        new_id = client.post(f"/api/campaigns/{cid}/duplicate", json=request).json()["id"]
    with TestClient(make_app(tmp_path)) as client:
        assert client.post(f"/api/campaigns/{cid}/duplicate", json=request).json()["id"] == new_id
        assert len(client.get("/api/campaigns").json()) == 2


def test_role_origin_and_audit_actor_are_enforced(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        setup(client)
        cid = client.post("/api/campaigns", json=CAMPAIGN).json()["id"]
        analyst = {**ADMIN, "username": "consulta", "role": "analyst"}
        operator = {**ADMIN, "username": "operador", "role": "operator"}
        client.post("/api/manage/users", json=analyst)
        client.post("/api/manage/users", json=operator)
        client.post("/api/auth/logout", json={})
        client.post("/api/auth/login", json=analyst)
        for action in ("duplicate", "rerun"):
            assert client.post(f"/api/campaigns/{cid}/{action}", json=payload()).status_code == 403
        assert client.get(f"/api/campaigns/{cid}/history").status_code == 200
        client.post("/api/auth/logout", json={})
        client.post("/api/auth/login", json=operator)
        assert client.post(f"/api/campaigns/{cid}/duplicate", json=payload(),
                           headers={"Origin": "https://other.invalid"}).status_code == 403
        new_id = client.post(f"/api/campaigns/{cid}/duplicate", json=payload()).json()["id"]
        history = client.get(f"/api/campaigns/{new_id}/history").json()
        assert history["items"][0]["actor_name"] == "operador"


def test_v4_migration_preserves_existing_jobs_and_only_backs_up_once(tmp_path):
    path = tmp_path / "old.sqlite3"
    store = Store(path)
    from blaster.models import CampaignInput, Contact

    cid = store.create_campaign(CampaignInput(
        name="Histórica", template="Hola", agent_number="999",
        contacts=[Contact(phone="123", credit_id="CRED-123")],
    ))
    before = store.jobs(cid)
    before[0]["credit_id"] = ""
    with store.db:
        remove_retries_schema(store.db)
        store.db.execute("DROP TABLE campaign_copies")
        store.db.execute("PRAGMA user_version=4")
    store.close()
    for _ in range(2):
        store = Store(path)
        assert store.jobs(cid) == before
        assert store.history.history(cid)["items"][0]["actor_name"] is None
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 8
        store.close()
    assert len(list(tmp_path.glob("*.before-executions-*.bak"))) == 1
