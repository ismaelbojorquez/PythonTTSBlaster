"""Credit/telephone traceability migration and bounded recording bundles."""

from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from blaster.recordings import safe_recording_path

_EN_VALUES = {
    "Finalizada": "Completed",
    "Buzón probable": "Probable voicemail",
    "Respuesta no identificada": "Unidentified answer",
    "Sin respuesta": "No answer",
    "Sin selección": "No selection",
    "Ocupada": "Busy",
    "Fallida": "Failed",
    "Proveedor no disponible": "Provider unavailable",
    "Cancelada": "Canceled",
    "Interrumpida": "Interrupted",
}


def migrate(db, path: Path) -> None:
    if db.execute("PRAGMA user_version").fetchone()[0] >= 7:
        return
    if db.execute("SELECT 1 FROM jobs LIMIT 1").fetchone():
        backup = path.with_name(f"{path.name}.before-traceability-{uuid4().hex[:8]}.bak")
        with sqlite3.connect(backup) as target:
            db.backup(target)
        backup.chmod(0o600)
    with db:
        db.execute("BEGIN")
        # Historical calls did not capture a credit. Keep that absence explicit.
        db.execute("ALTER TABLE jobs ADD COLUMN credit_id TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX jobs_credit ON jobs(credit_id)")
        db.execute("CREATE INDEX jobs_phone ON jobs(phone)")
        db.execute("PRAGMA user_version=7")


def _safe_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def build_recording_bundle(
    target: Path,
    rows: list[dict],
    xlsx: bytes,
    recording_directory: Path,
    language: str = "es",
) -> dict:
    """Write the report, manifest and trustworthy ready Ogg files into a ZIP."""
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = recording_directory.resolve()
    manifest = io.StringIO(newline="")
    writer = csv.writer(manifest, lineterminator="\n")
    headers = (
        [
            "account",
            "phone",
            "provider",
            "provider_id",
            "call_id",
            "campaign",
            "started",
            "outcome",
            "attempt",
            "recording_status",
            "file_in_zip",
            "details",
        ]
        if language == "en"
        else [
            "credito",
            "telefono",
            "troncal",
            "id_troncal",
            "id_llamada",
            "campaña",
            "inicio",
            "resultado",
            "intento",
            "estado_grabacion",
            "archivo_en_zip",
            "detalle",
        ]
    )
    writer.writerow(headers)
    included, unavailable, bytes_total = 0, 0, 0
    with ZipFile(target, "w", allowZip64=True) as archive:
        archive.writestr(
            "tracking-report.xlsx" if language == "en" else "reporte-trazabilidad.xlsx",
            xlsx,
            compress_type=ZIP_DEFLATED,
        )
        audio_entries = []
        for row in rows:
            jid = str(row["id"])
            stored_name = row.get("recording_filename")
            status = row.get("recording_status") or (
                "no_recording" if language == "en" else "sin_grabacion"
            )
            archive_name, detail = "", row.get("recording_detail") or ""
            source = safe_recording_path(recording_directory, stored_name)
            ready = (
                status == "ready"
                and source is not None
                and source.is_file()
                and source.resolve().parent == root
            )
            if ready:
                archive_name = f"{'recordings' if language == 'en' else 'grabaciones'}/{source.name}"
                audio_entries.append((source, archive_name))
                included += 1
                bytes_total += source.stat().st_size
                detail = "Included" if language == "en" else "Incluida"
            else:
                unavailable += 1
                if status == "ready":
                    status, detail = (
                        ("file_unavailable", "The file is no longer available")
                        if language == "en"
                        else ("archivo_no_disponible", "El archivo ya no está disponible")
                    )
            writer.writerow(
                [
                    _safe_cell(row.get("credit_id")),
                    _safe_cell(row.get("phone")),
                    _safe_cell(row.get("customer_trunk_name")),
                    _safe_cell(row.get("customer_trunk_id")),
                    jid,
                    _safe_cell(row.get("campaign_name")),
                    row.get("started_at") or "",
                    _safe_cell(
                        _EN_VALUES.get(row.get("status_label"), row.get("status_label"))
                        if language == "en"
                        else row.get("status_label")
                    ),
                    row.get("attempt_number") or 1,
                    status,
                    archive_name,
                    _safe_cell(detail),
                ]
            )
        archive.writestr(
            "recording-manifest.csv" if language == "en" else "manifest-grabaciones.csv",
            "\ufeff" + manifest.getvalue(),
            compress_type=ZIP_DEFLATED,
        )
        # Ogg Opus is already compressed; storing it avoids needless CPU and memory pressure.
        for source, archive_name in audio_entries:
            archive.write(source, archive_name, compress_type=ZIP_STORED)
    target.chmod(0o600)
    return {
        "calls": len(rows),
        "recordings": included,
        "unavailable": unavailable,
        "recording_bytes": bytes_total,
    }
