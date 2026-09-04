from __future__ import annotations

import csv
import io
import re
from string import Formatter

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
}


def phone_number(value: str) -> str:
    value = re.sub(r"[+ ()-]", "", value.strip())
    if not re.fullmatch(r"[0-9]{3,20}", value):
        raise ValueError("Usa un número de 3 a 20 dígitos")
    return value


class MissingTemplateVariable(ValueError):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Falta la variable {{{name}}} en un contacto")


def render_message(template: str, variables: dict[str, str]) -> str:
    for _, name, spec, conversion in Formatter().parse(template):
        if name is not None:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) or spec or conversion:
                raise ValueError("Las variables deben ser simples: {nombre}, {fecha}, {folio}")
            if name not in variables:
                raise MissingTemplateVariable(name)
    message = template.format_map(variables).strip()
    if not message or len(message) > 4000:
        raise ValueError("Cada mensaje debe tener entre 1 y 4000 caracteres")
    return message


class Contact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str
    variables: dict[str, str] = Field(default_factory=dict)

    _phone = field_validator("phone")(phone_number)

    @field_validator("variables")
    @classmethod
    def bounded_variables(cls, values: dict[str, str]) -> dict[str, str]:
        if len(values) > 30 or any(len(k) > 64 or len(v) > 1000 for k, v in values.items()):
            raise ValueError("Máximo 30 variables de 1000 caracteres")
        return values


class CampaignInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    template: str = Field(min_length=1, max_length=4000)
    agent_number: str
    contacts: list[Contact] = Field(min_length=1, max_length=10000)

    _agent = field_validator("agent_number")(phone_number)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Escribe un nombre para la campaña")
        return value.strip()

    @model_validator(mode="after")
    def valid_messages(self) -> CampaignInput:
        for contact in self.contacts:
            render_message(self.template, {**contact.variables, "telefono": contact.phone})
        return self


def parse_contacts(content: str) -> list[Contact]:
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    if not reader.fieldnames or "telefono" not in reader.fieldnames:
        raise ValueError("El CSV debe incluir la columna telefono")
    if len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("El CSV contiene columnas repetidas")
    contacts = []
    for row in reader:
        if len(contacts) >= 10000:
            raise ValueError("Máximo 10 000 contactos por campaña")
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"La fila {reader.line_num} tiene columnas incompletas o extra")
        contacts.append(
            Contact(
                phone=row.pop("telefono"),
                variables=row,
            )
        )
    if not contacts:
        raise ValueError("El CSV no contiene contactos")
    return contacts
