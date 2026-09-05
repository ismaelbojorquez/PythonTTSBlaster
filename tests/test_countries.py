import sqlite3

import pytest
from conftest import remove_retries_schema
from fastapi.testclient import TestClient

from blaster.config import Settings
from blaster.countries import countries, history_phone_number, international_number
from blaster.models import parse_contacts
from blaster.preview import AudioPreviewInput
from blaster.store import Store
from blaster.telephony.pjsua import PJSUATelephony
from blaster.web import create_app


@pytest.mark.parametrize(
    "region, entered, expected",
    [
        ("MX", "55 1234-5678", "525512345678"),
        ("MX", "+52 (55) 1234-5678", "525512345678"),
        ("MX", "525512345678", "525512345678"),
        ("US", "2025550123", "12025550123"),
        ("US", "12025550123", "12025550123"),
        ("CA", "4165550123", "14165550123"),
        ("ES", "612345678", "34612345678"),
        ("GB", "020 7946 0018", "442079460018"),
        ("IT", "06 6982 1234", "390669821234"),
        ("AR", "011 15-2345-6789", "5491123456789"),
        ("CO", "3211234567", "573211234567"),
    ],
)
def test_national_and_existing_international_numbers(region, entered, expected):
    assert international_number(entered, region) == expected
    assert international_number(expected, region) == expected


def test_history_search_accepts_national_or_explicit_international_number():
    assert history_phone_number("55 7856 4016", "MX") == "525578564016"
    assert history_phone_number("+52 55 7856 4016", "US") == "525578564016"
    assert history_phone_number("202 555 0123", "US") == "12025550123"


@pytest.mark.parametrize(
    "region, number",
    [
        ("MX", "123"),
        ("MX", "5215512345678"),
        ("US", "525512345678"),
        ("MX", "+12025550123"),
        ("ZZ", "5512345678"),
        ("MX", "5512345678 ext 1"),
    ],
)
def test_wrong_country_length_or_extension_is_rejected(region, number):
    with pytest.raises(ValueError):
        international_number(number, region)


def test_variable_length_plan_is_not_normalized_twice_or_guessed():
    from blaster.web import CampaignForm

    payload = CampaignForm(
        name="Alemania",
        country="DE",
        agent_number="01512 3456789",
        csv_text="Credito,telefono\nDE-1,01512 3456789",
        template="{telefono}",
    ).campaign(Settings())
    assert payload.contacts[0].phone == payload.agent_number == "4915123456789"
    assert international_number("+4915123456789", "DE") == "4915123456789"
    with pytest.raises(ValueError, match="ambiguo"):
        international_number("4915123456789", "DE")


def test_csv_uses_country_preserves_variables_and_identifies_invalid_row():
    csv = '\ufeffCredito,nombre,telefono,nota\nUS-1,"Ana, María",2025550123,"Suma +1"'
    contact = parse_contacts(csv, "US")[0]
    assert contact.phone == "12025550123"
    assert contact.credit_id == "US-1"
    assert contact.variables == {
        "Credito": "US-1", "nombre": "Ana, María", "nota": "Suma +1"
    }
    with pytest.raises(ValueError, match="Fila 3"):
        parse_contacts("Credito,telefono\nUS-1,2025550123\nUS-2,525512345678", "US")
    assert {r["code"]: r["calling_code"] for r in countries()}["MX"] == "52"


def test_country_persists_and_preview_export_and_agent_share_canonical_numbers(tmp_path):
    payload = {
        "name": "Contactos de Estados Unidos",
        "country": "US",
        "agent_country": "MX",
        "agent_number": "5512345678",
        "template": "Hola {nombre}, {telefono}",
        "csv_text": "Credito,telefono,nombre\nUS-1,2025550123,Ana",
    }
    app = create_app(Settings(data_dir=tmp_path, auth={"enabled": False}))
    with TestClient(app) as client:
        assert client.get("/api/countries").status_code == 200
        preview = client.post("/api/preview", json=payload).json()["samples"][0]
        audio_message, audio_phone = AudioPreviewInput(**payload).sample()
        assert preview == {"phone": audio_phone, "message": audio_message}
        assert audio_phone == "12025550123"
        response = client.post("/api/campaigns", json=payload)
        assert response.status_code == 201, response.text
        cid = response.json()["id"]
        campaign = client.get("/api/campaigns").json()[0]
        assert campaign["country"] == "US" and campaign["agent_country"] == "MX"
        assert campaign["agent_number"] == "525512345678"
        assert client.get(f"/api/campaigns/{cid}/jobs").json()[0]["phone"] == audio_phone
        assert audio_phone in client.get(f"/api/campaigns/{cid}/export").text
        # The default for a new campaign remains Mexico, including the agent.
        mexican = {**payload, "csv_text": "Credito,telefono,nombre\nMX-1,5512345678,Ana"}
        del mexican["country"]
        del mexican["agent_country"]
        cid = client.post("/api/campaigns", json=mexican).json()["id"]
        saved = next(c for c in client.get("/api/campaigns").json() if c["id"] == cid)
        assert saved["country"] == saved["agent_country"] == "MX"
        assert app.state.engine.telephony.legs == {}
    store = Store(tmp_path / "blaster.sqlite3")
    assert store.campaign(cid)["country"] == "MX"
    store.close()


async def test_international_destinations_reach_sip_unchanged():
    phone = PJSUATelephony(Settings())
    phone.available = True
    phone.trunk_states = {"default": {"available": True}}
    commands = []

    async def command(*args):
        commands.append(args)

    phone.command = command
    await phone.dial(international_number("2025550123", "US"), "customer")
    await phone.dial(international_number("5512345678", "MX"), "agent")
    assert [c[2] for c in commands] == ["12025550123", "525512345678"]


def test_template_retains_independent_agent_country(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, auth={"enabled": False}))) as client:
        response = client.post(
            "/api/manage/templates",
            json={
                "name": "Agente británico",
                "message": "Hola {nombre}",
                "agent_country": "GB",
                "agent_number": "02079460018",
            },
        )
        assert response.status_code == 200, response.text
        template = client.get("/api/manage/templates").json()[0]
        assert template["agent_number"] == "442079460018"
        assert template["agent_country"] == "GB"
        assert template["agent_national"] == "020 7946 0018"


def test_country_migration_preserves_old_numbers_and_does_not_invent_country(tmp_path):
    path = tmp_path / "v2.sqlite3"
    Store(path).close()
    with sqlite3.connect(path) as db:
        remove_retries_schema(db)
        db.execute("DROP TABLE campaign_copies")
        for table in ("campaigns", "templates"):
            for column in ("agent_numbers", "agent_strategy", "agent_pool_wait"):
                db.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        db.execute("ALTER TABLE campaigns DROP COLUMN agent_cursor")
        for column in ("agent_selected_number", "agent_strategy", "agent_pool_wait_seconds"):
            db.execute(f"ALTER TABLE call_records DROP COLUMN {column}")
        db.execute("ALTER TABLE campaigns DROP COLUMN country")
        db.execute("ALTER TABLE campaigns DROP COLUMN agent_country")
        db.execute("ALTER TABLE templates DROP COLUMN agent_country")
        db.execute("PRAGMA user_version=2")
        db.execute("INSERT INTO campaigns VALUES('c','Anterior','Hola','999','draft','2026','sip')")
    for _ in range(2):
        store = Store(path)
        campaign = store.campaign("c")
        assert campaign["agent_number"] == "999"
        assert campaign["country"] is None and campaign["agent_country"] is None
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 8
        store.close()
    assert len(list(tmp_path.glob("*.before-countries-*.bak"))) == 1
