from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from blaster.agent_pool import AgentStrategy
from blaster.contact_files import credit_column, phone_column, read_csv
from blaster.countries import country_code, international_number
from blaster.retries import RetryPolicy

MENU = "Presiona 1 para escuchar de nuevo el mensaje. Presiona 2 para hablar con un agente."
TERMINAL = {
    "completed",
    "busy",
    "no_answer",
    "failed",
    "cancelled",
    "interrupted",
    "no_input",
    "machine",
    "amd_unknown",
    "temporary_error",
}


def phone_number(value: str) -> str:
    value = re.sub(r"[+ ()-]", "", value.strip())
    if not re.fullmatch(r"[0-9]{3,20}", value):
        raise ValueError("Usa un número de 3 a 20 dígitos")
    return value


def transfer_numbers(text: str, legacy: str = "", country: str | None = None) -> list[str]:
    rows = text.splitlines() if text.strip() else [legacy]
    values = [value.strip() for value in rows if value.strip()]
    if len(values) > 50:
        raise ValueError("Máximo 50 teléfonos en el pool de transferencia")
    result = []
    for index, value in enumerate(values, 1):
        try:
            number = international_number(value, country) if country else phone_number(value)
        except ValueError as error:
            raise ValueError(f"Teléfono de transferencia {index}: {error}") from error
        if number in result:
            raise ValueError(f"Teléfono de transferencia {index}: número repetido en el pool")
        result.append(number)
    return result


class MissingTemplateVariable(ValueError):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Falta la variable {{{name}}} en un contacto")


TEMPLATE_TOKENS = re.compile(r"\{\{|\}\}|\{([^{}\r\n]+)\}|[{}]")


def template_variables(template: str) -> set[str]:
    names = set()
    for match in TEMPLATE_TOKENS.finditer(template):
        if match.group() in {"{{", "}}"}:
            continue
        name = match.group(1)
        if name is None:
            raise ValueError("Revisa las llaves del mensaje: usa {Encabezado} para cada variable")
        name = unicodedata.normalize("NFC", name)
        if not name.strip() or len(name) > 64:
            raise ValueError("Cada variable debe tener de 1 a 64 caracteres")
        names.add(name)
    return names


def render_message(template: str, variables: dict[str, str]) -> str:
    for name in template_variables(template):
        if name not in variables:
            raise MissingTemplateVariable(name)

    def replace(match):
        token = match.group()
        if token in {"{{", "}}"}:
            return token[0]
        name = match.group(1)
        name = unicodedata.normalize("NFC", name)
        # Exact dictionary lookup only: never evaluate attributes, indexes or format specs.
        return variables[name]

    message = TEMPLATE_TOKENS.sub(replace, template).strip()
    if not message or len(message) > 4000:
        raise ValueError("Cada mensaje debe tener entre 1 y 4000 caracteres")
    return message


class Contact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str
    credit_id: str
    variables: dict[str, str] = Field(default_factory=dict)

    _phone = field_validator("phone")(phone_number)

    @field_validator("credit_id")
    @classmethod
    def valid_credit(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", value.strip())
        if not value:
            raise ValueError("Credito es obligatorio")
        if len(value) > 255 or any(ord(character) < 32 for character in value):
            raise ValueError("Credito debe tener de 1 a 255 caracteres sin saltos")
        return value

    @field_validator("variables")
    @classmethod
    def bounded_variables(cls, values: dict[str, str]) -> dict[str, str]:
        if len(values) > 102 or any(len(k) > 64 or len(v) > 1000 for k, v in values.items()):
            raise ValueError(
                "Máximo 100 variables además de Credito y Telefono, de 1000 caracteres"
            )
        return values


class CampaignInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    template: str = Field(min_length=1, max_length=4000)
    agent_number: str = ""
    agent_numbers: list[str] = Field(default_factory=list, max_length=50)
    agent_strategy: AgentStrategy = "round_robin"
    agent_pool_wait: float = Field(default=30, ge=0, le=300)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    contacts: list[Contact] = Field(min_length=1, max_length=10000)
    country: str | None = None
    agent_country: str | None = None

    @field_validator("agent_number")
    @classmethod
    def single_agent(cls, value):
        return phone_number(value) if value else ""

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Escribe un nombre para la campaña")
        return value.strip()

    @model_validator(mode="after")
    def valid_messages(self) -> CampaignInput:
        self.agent_numbers = transfer_numbers("\n".join(self.agent_numbers), self.agent_number)
        if not self.agent_numbers:
            raise ValueError("Agrega al menos un teléfono de transferencia")
        self.agent_number = self.agent_numbers[0]
        if self.country:
            self.country = country_code(self.country)
            self.agent_country = country_code(self.agent_country or self.country)
            # The form has already normalized these numbers. Re-parsing E.164 digits
            # as national numbers is ambiguous in variable-length plans such as DE.
        for index, contact in enumerate(self.contacts, 2):
            try:
                render_message(
                    self.template,
                    {
                        **contact.variables,
                        "telefono": contact.phone,
                        "phone": contact.phone,
                        "telephone": contact.phone,
                        "credito": contact.credit_id,
                        "credit": contact.credit_id,
                        "account": contact.credit_id,
                        "account_id": contact.credit_id,
                    },
                )
            except ValueError as error:
                raise ValueError(f"Fila {index}: {error}") from error
        return self


def parse_contacts(content: str, country: str | None = None) -> list[Contact]:
    table = read_csv(content)
    telephone = phone_column(table.headers)
    credit = credit_column(table.headers)
    contacts = []
    for index, values in enumerate(table.rows, 2):
        row = dict(zip(table.headers, values, strict=True))
        try:
            phone = row.pop(telephone)
            credit_id = row.pop(credit).strip()
            phone = international_number(phone, country) if country else phone_number(phone)
            if telephone != "telefono":
                row[telephone] = phone
            if credit != "credito":
                row[credit] = credit_id
            contacts.append(
                Contact(
                    phone=phone,
                    credit_id=credit_id,
                    variables=row,
                )
            )
        except ValueError as error:
            raise ValueError(f"Fila {index}: {error}") from error
    return contacts
