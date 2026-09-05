from fastapi.testclient import TestClient

from blaster.config import Settings
from blaster.web import create_app

PAYLOAD = {
    "name": "Prueba",
    "template": "Hola {nombre}",
    "agent_number": "+525550009999",
    "csv_text": "Credito,telefono,nombre\nWEB-1,+525550000101,Ana",
}


def test_create_preview_export_validation_and_origin(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, auth={"enabled": False}))) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/status").json()["mode"] == "simulation"
        preview = client.post("/api/preview", json=PAYLOAD)
        assert preview.json()["samples"][0]["message"] == "Hola Ana"
        assert preview.json()["samples"][0]["phone"] == "525550000101"
        created = client.post("/api/campaigns", json=PAYLOAD)
        assert created.status_code == 201
        cid = created.json()["id"]
        summary = client.get("/api/analytics/summary?mode=simulation").json()
        assert summary["counts"]["total"] == 0  # queued work is not a call attempt
        assert summary["answer_rate"] is None
        calls = client.get("/api/calls?mode=simulation").json()
        assert calls == {"total": 0, "limit": 50, "offset": 0, "items": []}
        xlsx = client.get("/api/reports/xlsx?mode=simulation")
        assert xlsx.status_code == 200 and xlsx.content.startswith(b"PK")
        assert "blaster-reporte.xlsx" in xlsx.headers["content-disposition"]
        cdr = client.get("/api/reports/csv?mode=simulation")
        assert cdr.status_code == 200 and "ID llamada" in cdr.content.decode("utf-8-sig")
        assert client.get("/api/calls/unknown").status_code == 404
        job = client.get(f"/api/campaigns/{cid}/jobs").json()[0]
        assert job["status"] == "queued"
        assert job["phone"] == "525550000101"
        assert job["customer_trunk_id"] is None
        assert job["customer_trunk_name"] is None
        assert client.get("/api/campaigns").json()[0]["agent_number"] == "525550009999"
        csv = client.get(f"/api/campaigns/{cid}/export")
        assert "troncal,id_troncal" in csv.text
        assert "525550000101" in csv.text
        assert "+525550000101" not in csv.text
        assert (
            client.post("/api/campaigns", json={**PAYLOAD, "template": "{fecha}"}).status_code
            == 422
        )
        assert (
            client.post(
                "/api/campaigns", json=PAYLOAD, headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 400
        assert client.post("/api/settings", json={"concurrency": 21}).status_code == 422
        assert client.post("/api/settings", json={"concurrency": 2}).json()["concurrency"] == 2
        assert client.get("/api/campaigns/unknown/jobs").status_code == 404


def test_only_one_process_can_own_data(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, auth={"enabled": False}))):
        import pytest

        with pytest.raises(RuntimeError, match="instancia"):
            with TestClient(create_app(Settings(data_dir=tmp_path, auth={"enabled": False}))):
                pass
