import pytest

from blaster.config import Settings, load_settings
from blaster.models import CampaignInput, Contact, parse_contacts, phone_number, render_message
from blaster.store import Store


@pytest.mark.parametrize(
    "text", ["{nombre.__class__}", "{nombre[0]}", "{nombre!r}", "{nombre:>20}", "{}"]
)
def test_templates_do_not_allow_expressions(text):
    with pytest.raises(ValueError):
        render_message(text, {"nombre": "Ana"})


def test_csv_and_template_validation():
    rows = parse_contacts('\ufefftelefono,nombre\n+525500000000,"Ana, María"\n')
    assert rows[0].variables["nombre"] == "Ana, María"
    assert rows[0].phone == "525500000000"
    assert (
        render_message("Hola {nombre}, {{literal}}", rows[0].variables)
        == "Hola Ana, María, {literal}"
    )
    with pytest.raises(ValueError, match="Falta la variable"):
        render_message("Hola {fecha}", rows[0].variables)
    for csv in [
        "nombre\nAna",
        "telefono,nombre\n123",
        "telefono,nombre\n123,Ana,extra",
        "telefono,telefono\n123,456",
        "telefono,nombre\n",
    ]:
        with pytest.raises(ValueError):
            parse_contacts(csv)
    with pytest.raises(ValueError):
        phone_number("sip:attacker@host")


def test_number_cleanup_preserves_csv_variables_and_cleans_the_agent():
    contacts = parse_contacts(
        '\ufeffnombre,"telefono",nota\r\n'
        '"Ana + Luis","+52 (55) 0000-0101","A + B, \"\"confirmado\"\"\nmañana"\r\n'
    )
    campaign = CampaignInput(
        name="Prueba", template="Hola {nombre}, {telefono}",
        agent_number="+52 (55) 0000-0102", contacts=contacts,
    )
    assert campaign.agent_number == "525500000102"
    assert contacts[0].phone == "525500000101"
    assert contacts[0].variables == {
        "nombre": "Ana + Luis", "nota": 'A + B, "confirmado"\nmañana',
    }
    assert phone_number("525500000101") == "525500000101"
    assert phone_number("5500000101") == "5500000101"
    with pytest.raises(ValueError):
        phone_number("+52abc5500000101")


def test_restart_marks_active_interrupted_and_keeps_queue(tmp_path):
    path = tmp_path / "test.sqlite3"
    store = Store(path)
    cid = store.create_campaign(
        CampaignInput(
            name="Prueba",
            template="Hola",
            agent_number="999",
            contacts=[Contact(phone="123"), Contact(phone="456")],
        )
    )
    store.set_campaign_status(cid, "running")
    store.transition(store.jobs(cid)[0]["id"], "bridged")
    store.close()
    reopened = Store(path)
    reopened.recover()
    assert reopened.campaign(cid)["status"] == "paused"
    assert [job["status"] for job in reopened.jobs(cid)] == ["interrupted", "queued"]
    reopened.close()


def test_settings_resolve_paths_and_capacity(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('data_dir="state"\n')
    assert load_settings(path).data_dir == tmp_path / "state"
    with pytest.raises(ValueError):
        Settings(concurrency=4, trunk_channels=6)
    with pytest.raises(ValueError):
        Settings(sip={"rtp_port": 10001})
