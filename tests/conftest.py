import pytest

from blaster.config import Settings
from blaster.engine import Engine
from blaster.models import CampaignInput, Contact
from blaster.store import Store
from blaster.telephony.simulated import SimulatedTelephony
from blaster.tts import SimulatedSpeech


def remove_retries_schema(db):
    """Build a genuine pre-v6 database for migration tests."""
    db.execute("DROP INDEX jobs_credit")
    db.execute("DROP INDEX jobs_phone")
    db.execute("ALTER TABLE jobs DROP COLUMN credit_id")
    db.execute("DROP TABLE retry_decisions")
    db.execute("DROP TRIGGER jobs_contact_root")
    for name in ("jobs_contact_attempt", "jobs_retry_parent", "jobs_due"):
        db.execute(f"DROP INDEX {name}")
    for name in ("contact_id", "attempt_number", "retry_of", "available_at"):
        db.execute(f"ALTER TABLE jobs DROP COLUMN {name}")
    db.execute("ALTER TABLE campaigns DROP COLUMN retry_policy")


@pytest.fixture
async def engine(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        concurrency=2,
        trunk_channels=4,
        calls_per_second=20,
        ring_timeout=0.3,
        agent_timeout=0.1,
        choice_timeout=0.25,
        max_call_seconds=5,
    )
    store = Store(tmp_path / "test.sqlite3")
    phone = SimulatedTelephony(answer_delay=0.005, audio_speed=0.005)
    instance = Engine(settings, store, phone, SimulatedSpeech())
    await instance.start()
    yield instance
    await instance.close()
    store.close()


def campaign(engine, count=1, mode="simulation"):
    return engine.store.create_campaign(
        CampaignInput(
            name="Prueba",
            template="Hola {nombre}",
            agent_number="+525550009999",
            contacts=[
                Contact(
                    phone=f"+5255500001{i:02}",
                    credit_id=f"CRED-{i:03}",
                    variables={"nombre": f"Persona {i}"},
                )
                for i in range(count)
            ],
        ),
        mode=mode,
    )
