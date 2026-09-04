from __future__ import annotations


def error_detail(error: Exception, password: str = "") -> str:
    """Readable diagnostics, including native PJSUA2 errors, without SIP passwords."""
    info = getattr(error, "info", None)
    detail = info() if callable(info) else str(error)
    if password:
        for secret in {password, repr(password)[1:-1]}:
            detail = detail.replace(secret, "[contraseña oculta]")
    detail = " ".join("".join(c if c.isprintable() else " " for c in detail).split())
    return f"{type(error).__name__}: {detail or 'sin detalle adicional'}"[:500]
