import time
import wave
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from blaster.amd import DETECTOR_VERSION, AMDResult
from blaster.amd_calibration import AMDCalibration
from blaster.config import Settings
from blaster.models import CampaignInput, Contact
from blaster.store import Store
from blaster.web import create_app


def test_calibration_review_audio_labels_and_bulk_delete(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        auth={"enabled": False},
        amd={"enabled": True, "calibration_capture_enabled": True},
    )
    payload = {
        "name": "Calibración",
        "template": "Hola {nombre}",
        "agent_number": "5550000199",
        "execution": "now",
        "csv_text": (
            "Credito,telefono,nombre\n"
            "CAL-1,5550000101,Ana\n"
            "CAL-2,5550000102,Luis"
        ),
    }
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/campaigns", json=payload)
        assert created.status_code == 201, created.text
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pending = client.get("/api/amd-calibration")
            if pending.json()["total"] == 2:
                break
            time.sleep(0.02)
        assert pending.status_code == 200
        body = pending.json()
        assert body["total"] == 2
        assert body["summary"]["pending"] == 2
        assert body["summary"]["capture_seconds"] == 6.5
        selected = body["items"][0]
        assert selected["predicted_verdict"] == "human"

        audio = client.get(f"/api/amd-calibration/{selected['id']}/audio")
        assert audio.status_code == 200
        assert audio.headers["content-type"].startswith("audio/wav")
        path = tmp_path / "download.wav"
        path.write_bytes(audio.content)
        with wave.open(str(path), "rb") as recording:
            assert recording.getparams()[:3] == (1, 2, 8000)

        labeled = client.post(
            f"/api/amd-calibration/{selected['id']}/label", json={"label": "human"}
        )
        assert labeled.status_code == 200
        assert client.get("/api/amd-calibration?label=human").json()["total"] == 1
        assert client.get("/api/amd-calibration?label=disagreement").json()["total"] == 0
        assert client.post(
            f"/api/amd-calibration/{selected['id']}/label", json={"label": "invalid"}
        ).status_code == 422

        deleted = client.post("/api/amd-calibration/delete-all", json={})
        assert deleted.json()["deleted"] == 2
        assert client.get("/api/amd-calibration?label=all").json()["total"] == 0
        assert not list((tmp_path / "amd-calibration").glob("*.wav"))


def test_calibration_prunes_labeled_and_expired_samples(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        amd={"calibration_capture_enabled": True, "calibration_max_samples": 10},
    )
    store = Store(tmp_path / "blaster.sqlite3")
    service = AMDCalibration(settings, store)
    cid = store.create_campaign(
        CampaignInput(
            name="Retención",
            template="Hola",
            agent_number="525550001999",
            contacts=[
                Contact(phone=f"525550001{i:03}", credit_id=f"RET-{i}")
                for i in range(11)
            ],
        )
    )
    jobs = store.jobs(cid)
    result = AMDResult("human", "short_greeting", 1400, 1400, 400, 1)
    first = service.save(jobs[0], result, bytes(320), DETECTOR_VERSION, {})
    service.label(first, "human", {"username": "prueba"})
    for job in jobs[1:]:
        service.save(job, result, bytes(320), DETECTOR_VERSION, {})
    assert service.summary()["total"] == 10
    assert store.db.execute(
        "SELECT 1 FROM amd_calibration_samples WHERE id=?", (first,)
    ).fetchone() is None

    expired = store.db.execute(
        "SELECT id,filename FROM amd_calibration_samples LIMIT 1"
    ).fetchone()
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    with store.db:
        store.db.execute(
            "UPDATE amd_calibration_samples SET created_at=? WHERE id=?", (old, expired["id"])
        )
    settings.amd.calibration_retention_days = 1
    assert service.prune() == 1
    assert not (service.directory / expired["filename"]).exists()
    store.close()
