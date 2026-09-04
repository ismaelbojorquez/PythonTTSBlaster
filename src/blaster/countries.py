"""Local numbering-plan metadata and national-to-international conversion."""

from __future__ import annotations

import re
from functools import lru_cache

import phonenumbers as pn


def country_code(value: str) -> str:
    region = value.strip().upper()
    if region not in pn.SUPPORTED_REGIONS:
        raise ValueError("Selecciona un país válido")
    return region


def international_number(value: str, country: str) -> str:
    region = country_code(country)
    code = pn.country_code_for_region(region)
    compact = re.sub(r"[\s().-]", "", value)
    if not re.fullmatch(r"\+?[0-9]{3,20}", compact):
        raise ValueError("Escribe un teléfono con dígitos, sin extensiones ni letras")
    try:
        number = pn.parse(compact, region)
    except pn.NumberParseException as error:
        raise ValueError(f"El teléfono no corresponde a {region} (+{code})") from error
    if compact.startswith(str(code)) and pn.is_possible_number(number):
        prefixed = pn.parse("+" + compact, None)
        if pn.is_possible_number(prefixed) and prefixed != number:
            example = pn.example_number_for_type(region, pn.PhoneNumberType.MOBILE)
            example = example or pn.example_number(region)
            hint = pn.format_number(example, pn.PhoneNumberFormat.NATIONAL) if example else ""
            raise ValueError(
                f"Número ambiguo para {region} (+{code}). "
                f"Usa el formato nacional, incluido su prefijo local; ejemplo: {hint}."
            )
    if number.country_code != code or not pn.is_possible_number(number):
        raise ValueError(
            f"El teléfono no corresponde a {region} (+{code}). "
            "Revisa el país y la cantidad de dígitos del número nacional."
        )
    # SIP providers receive digits only. Do not strip national leading zeroes by hand.
    return pn.format_number(number, pn.PhoneNumberFormat.E164).removeprefix("+")


@lru_cache(maxsize=1)
def countries() -> list[dict]:
    result = []
    for region in sorted(pn.SUPPORTED_REGIONS):
        example = pn.example_number_for_type(region, pn.PhoneNumberType.MOBILE)
        example = example or pn.example_number(region)
        result.append(
            {
                "code": region,
                "calling_code": str(pn.country_code_for_region(region)),
                "example": pn.format_number(example, pn.PhoneNumberFormat.NATIONAL)
                if example
                else "",
            }
        )
    return result


def stored_number_country(number: str) -> str | None:
    """Infer metadata for legacy templates without rewriting their saved number."""
    try:
        parsed = pn.parse("+" + number, None)
        return pn.region_code_for_number(parsed) if pn.is_possible_number(parsed) else None
    except pn.NumberParseException:
        return None


def national_display(number: str) -> str:
    try:
        return pn.format_number(pn.parse("+" + number, None), pn.PhoneNumberFormat.NATIONAL)
    except pn.NumberParseException:
        return number
