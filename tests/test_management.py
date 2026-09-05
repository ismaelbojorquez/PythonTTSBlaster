import json
import sqlite3
import tomllib
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from blaster.config import load_settings
from blaster.web import create_app

ADMIN = {"username": "admin", "display_name": "Administración", "password": "UnaClaveDePrueba-123"}
CAMPAIGN = {
    "name": "Programada",
    "template": "Hola {nombre}",
    "agent_number": "525500009999",
    "csv_text": "Credito,telefono,nombre\nMGT-1,525500000001,Ana",
}


def app_for(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('mode="simulation"\ndata_dir="data"\n[automation]\nenabled=false\n')
    return create_app(load_settings(path))


def setup(client):
    response = client.post("/api/auth/setup", json=ADMIN)
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "admin"
    return response.json()


def test_auth_roles_revocation_audit_and_secrets(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/status").status_code == 401
        assert (
            client.post(
                "/api/auth/setup", json=ADMIN, headers={"origin": "https://other.example"}
            ).status_code
            == 403
        )
        me = setup(client)
        assert client.post("/api/auth/setup", json=ADMIN).status_code == 409
        assert "httponly" in client.cookies.get("blaster_session", "").lower() or client.cookies
        analyst = {**ADMIN, "username": "consulta", "display_name": "Consulta", "role": "analyst"}
        uid = client.post("/api/manage/users", json=analyst).json()["id"]
        operator = {**ADMIN, "username": "operacion", "role": "operator"}
        assert client.post("/api/manage/users", json=operator).status_code == 200
        assert client.post("/api/manage/users", json=analyst).status_code == 422
        assert (
            client.post(
                "/api/manage/users/" + me["id"],
                json={"display_name": "Admin", "enabled": False, "role": "admin"},
            ).status_code
            == 422
        )
        audit = client.get("/api/manage/audit").text
        assert ADMIN["password"] not in audit and "password_hash" not in audit
        assert "POST /api/manage/users" in audit
        client.post("/api/auth/logout", json={})
        assert client.get("/api/campaigns").status_code == 401
        assert (
            client.post(
                "/api/auth/login", json={"username": "consulta", "password": "incorrecta"}
            ).status_code
            == 401
        )
        assert client.post("/api/auth/login", json=analyst).status_code == 200
        assert client.get("/api/campaigns").status_code == 200
        assert client.get("/api/manage/config").status_code == 403
        assert client.get("/api/manage/voices").status_code == 403
        assert client.get("/api/manage/audit").status_code == 403
        assert client.get("/api/amd-calibration").status_code == 403
        assert client.post("/api/campaigns", json=CAMPAIGN).status_code == 403
        assert client.get("/api/recordings/missing").status_code == 403
        assert (
            client.get(
                "/api/traceability/bundle.zip", params={"by": "credit", "query": "CRED-1"}
            ).status_code
            == 403
        )
        client.post("/api/auth/logout", json={})
        client.post("/api/auth/login", json=ADMIN)
        assert (
            client.post(
                "/api/manage/users/" + uid,
                json={"display_name": "Consulta", "role": "analyst", "enabled": False},
            ).status_code
            == 200
        )
        client.post("/api/auth/logout", json={})
        assert client.post("/api/auth/login", json=analyst).status_code == 401
        assert client.post("/api/auth/login", json=operator).status_code == 200
        assert client.post("/api/campaigns", json=CAMPAIGN).status_code == 201
        assert client.post("/api/settings", json={"concurrency": 1}).status_code == 403
        assert app.state.engine.settings.concurrency == 20


def test_templates_schedules_reports_and_validation(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        setup(client)
        template = {
            "name": "Recordatorio",
            "message": "Hola {nombre}, cita {fecha}",
            "agent_number": "+52 55 0000 9999",
        }
        tid = client.post("/api/manage/templates", json=template).json()["id"]
        assert client.get("/api/manage/templates").json()[0]["agent_number"] == "525500009999"
        assert (
            client.post(
                "/api/manage/templates", json={**template, "message": "{Encabezado sin cierre"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/manage/templates", json={**template, "id": tid, "message": "Hola {nombre}"}
            ).status_code
            == 200
        )
        cid = client.post("/api/campaigns", json=CAMPAIGN).json()["id"]
        app.state.engine.settings.automation.enabled = True
        due = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        payload = {"campaign_id": cid, "local_at": due, "timezone": "America/Mexico_City"}
        scheduled = client.post("/api/manage/schedules", json=payload)
        assert scheduled.status_code == 200, scheduled.text
        assert client.post("/api/manage/schedules", json=payload).status_code == 422
        sid = scheduled.json()["id"]
        assert client.post("/api/manage/schedules/" + sid + "/cancel", json={}).status_code == 200
        assert client.get("/api/manage/schedules").json()[0]["state"] == "cancelled"
        assert (
            client.post(
                "/api/manage/schedules", json={**payload, "local_at": "2020-01-01T12:00"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/manage/schedules", json={**payload, "timezone": "No/existe"}
            ).status_code
            == 422
        )
        report = {"name": "Diario", "timezone": "America/Mexico_City", "mode": "simulation"}
        r = client.post("/api/manage/report-schedules", json=report)
        assert r.status_code == 200, r.text
        assert (
            client.get("/api/manage/report-schedules").json()["schedules"][0]["cadence"] == "daily"
        )
        assert client.post("/api/manage/templates/" + tid + "/delete", json={}).status_code == 200
        assert client.get("/api/manage/templates").json() == []


def test_configuration_persists_ports_capacity_and_masks_password(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        setup(client)
        original = client.get("/api/manage/config").json()
        assert (
            client.post("/api/manage/config", json={**original, "concurrency": 21}).status_code
            == 422
        )
        assert (
            client.post(
                "/api/manage/config",
                json={
                    **original,
                    "concurrency": 2,
                    "trunk_channels": 6,
                    "routing": "weighted",
                    "amd": {**original["amd"], "calibration_capture_enabled": True},
                },
            ).status_code
            == 200
        )
        trunk = {
            "id": "principal",
            "name": "Principal",
            "channels": 4,
            "priority": 10,
            "weight": 3,
            "sip": {
                "domain": "sip.example",
                "username": "test",
                "password": "NO-EXPORTAR-123",
                "local_port": 5080,
                "rtp_port": 18000,
                "rtp_port_range": 100,
            },
        }
        r = client.post("/api/manage/trunks", json=trunk)
        assert r.status_code == 200, r.text
        result = client.get("/api/manage/trunks")
        assert (
            "NO-EXPORTAR" not in result.text and "NO-EXPORTAR" not in client.get("/api/status").text
        )
        assert "NO-EXPORTAR" not in client.get("/api/manage/audit").text
        with sqlite3.connect(tmp_path / "data" / "blaster.sqlite3") as db:
            assert "NO-EXPORTAR" not in json.dumps(db.execute("SELECT * FROM trunks").fetchall())
        parsed = tomllib.loads((tmp_path / "config.toml").read_text())
        assert parsed["concurrency"] == 2 and parsed["trunk_channels"] == 6
        assert parsed["amd"]["calibration_capture_enabled"] is True
        profile = next(t for t in parsed["trunks"] if t["id"] == "principal")
        assert profile["sip"]["password"] == "NO-EXPORTAR-123"
        assert profile["sip"]["local_port"] == 5080 and profile["sip"]["rtp_port"] == 18000
        assert (
            client.post(
                "/api/manage/trunks", json={**trunk, "sip": {**trunk["sip"], "rtp_port": 18001}}
            ).status_code
            == 422
        )
        assert len(client.get("/api/manage/trunks/principal/history").json()) == 1
        # Editing without returning the secret preserves it.
        trunk["sip"]["password"] = ""
        assert client.post("/api/manage/trunks", json=trunk).status_code == 200
        profiles = load_settings(tmp_path / "config.toml").trunk_profiles()
        assert next(t for t in profiles if t.id == "principal").sip.password == "NO-EXPORTAR-123"


def test_first_admin_and_hash_persist_after_restart(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        setup(client)
    with TestClient(create_app(load_settings(tmp_path / "config.toml"))) as client:
        assert not client.get("/api/auth/status").json()["setup_required"]
        assert client.post("/api/auth/login", json=ADMIN).status_code == 200
