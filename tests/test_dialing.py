import pytest

from blaster.config import Settings
from blaster.dialing import DialingError, format_dial_number
from blaster.models import CampaignInput, Contact
from blaster.telephony.pjsua import PJSUATelephony
from blaster.web import CampaignForm


@pytest.mark.parametrize(
    "number", ["+525500000101", "525500000101", "5500000101", "+52 (55) 0000-0101"]
)
def test_mexico_number_is_twelve_digits_without_duplicate_country_code(number):
    assert format_dial_number(number, "mexico_52") == "525500000101"


@pytest.mark.parametrize("number", ["+15550000101", "91525500000101", "+5215500000101", "123"])
def test_mexico_format_does_not_guess_at_other_countries_or_internal_prefixes(number):
    with pytest.raises(DialingError):
        format_dial_number(number, "mexico_52")


def test_default_format_keeps_international_and_extension_dialing():
    assert format_dial_number("+1 (555) 000-0101", "as_entered") == "15550000101"
    assert format_dial_number("123", "as_entered") == "123"


async def test_contact_and_agent_use_the_trunk_format_before_sip_commands():
    settings = Settings(sip={"dial_format": "mexico_52"})
    phone = PJSUATelephony(settings)
    phone.available = True
    phone.trunk_states = {"default": {"available": True}}
    commands = []

    async def command(*args):
        commands.append(args)

    phone.command = command
    customer = await phone.dial("+525500000101", "customer")
    agent = await phone.dial("5500000102", "agent")
    assert commands == [
        ("dial", customer.id, "525500000101", "default"),
        ("dial", agent.id, "525500000102", "default"),
    ]
    with pytest.raises(DialingError):
        await phone.dial("91525500000101", "customer")
    assert len(commands) == 2


@pytest.mark.parametrize("invalid_role", ["customer", "agent"])
async def test_existing_campaign_is_validated_before_starting_any_calls(engine, invalid_role):
    engine.settings.mode = "sip"
    engine.settings.sip.dial_format = "mexico_52"
    cid = engine.store.create_campaign(
        CampaignInput(
            name="Cambio de formato de troncal",
            template="Hola",
            agent_number="123" if invalid_role == "agent" else "+525500000102",
            contacts=[Contact(
                phone="123" if invalid_role == "customer" else "+525500000101",
                credit_id="CRED-1",
            )],
        ),
        mode="sip",
    )
    with pytest.raises(DialingError):
        engine.start_campaign(cid)
    assert engine.active_campaign is None
    assert not engine.telephony.legs
    assert engine.store.jobs(cid)[0]["status"] == "queued"


def test_campaign_form_removes_plus_and_checks_the_agent():
    settings = Settings(mode="sip", sip={"dial_format": "mexico_52"})
    form = CampaignForm(
        name="Prueba",
        template="Hola",
        agent_number="5500000102",
        csv_text="Credito,telefono,nombre\nDIAL-1,+525500000101,Ana",
    )
    campaign = form.campaign(settings)
    assert campaign.contacts[0].phone == "525500000101"
    assert campaign.agent_number == "525500000102"
    form.agent_number = "+15550000102"
    with pytest.raises(ValueError, match="país"):
        form.campaign(settings)
