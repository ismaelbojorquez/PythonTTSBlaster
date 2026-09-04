from __future__ import annotations

import re
from typing import Literal

from blaster.models import phone_number

DialFormat = Literal["as_entered", "mexico_52"]


class DialingError(ValueError):
    pass


def format_dial_number(value: str, dial_format: DialFormat) -> str:
    """Convert a contact or agent number to the trunk's configured dial format."""
    number = phone_number(value)
    if dial_format == "as_entered":
        return number
    if dial_format == "mexico_52":
        if re.fullmatch(r"52[0-9]{10}", number):
            return number
        if re.fullmatch(r"[0-9]{10}", number):
            return f"52{number}"
        raise DialingError(
            "La troncal requiere un número de México: 10 dígitos nacionales o 52 más 10 dígitos."
        )
    raise DialingError("Formato de marcación desconocido")
