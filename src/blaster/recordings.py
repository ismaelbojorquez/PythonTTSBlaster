"""Native mixed WAV capture followed by bounded local Opus compression."""

from __future__ import annotations

import asyncio
import contextlib
import re
import shutil
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from blaster.store import now


def _credit_filename_part(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return text[:72].rstrip("-") or "sin-credito"


def recording_filename(job: dict, started_at: str, timezone: str) -> str:
    """Return a readable, portable name without trusting imported CSV values."""
    instant = datetime.fromisoformat(started_at)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    stamp = instant.astimezone(ZoneInfo(timezone)).strftime("%Y%m%d_%H%M%S_%f")[:-3]
    credit = _credit_filename_part(job.get("credit_id"))
    phone = re.sub(r"\D", "", str(job.get("phone") or ""))[:32] or "sin-telefono"
    return f"{credit}_{phone}_{stamp}.ogg"


def safe_recording_path(directory: Path, filename: object) -> Path | None:
    """Resolve one DB filename while containing access to the recordings directory."""
    if not isinstance(filename, str) or Path(filename).name != filename:
        return None
    if not filename.endswith(".ogg"):
        return None
    path = directory / filename
    if path.is_symlink() or path.resolve().parent != directory.resolve():
        return None
    return path


class Recordings:
    def __init__(self, settings, ops, phone):
        self.settings, self.ops, self.phone = settings, ops, phone
        self.directory = settings.data_dir / "recordings"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        self.workers = asyncio.Semaphore(2)
        self.active: dict[str, tuple[Path, Path]] = {}

    def _available_target(self, desired: str, jid: str) -> Path:
        """Avoid overwriting another CDR if two calls finish in the same millisecond."""
        stem = Path(desired).stem
        candidates = [desired, f"{stem}_{jid[:8]}.ogg"]
        candidates.extend(f"{stem}_{jid[:8]}_{index}.ogg" for index in range(2, 100))
        active_names = {target.name for _, target in self.active.values()}
        for name in candidates:
            used = self.ops.db.execute(
                "SELECT 1 FROM recordings WHERE filename=? LIMIT 1", (name,)
            ).fetchone()
            path = self.directory / name
            if not used and name not in active_names and not path.exists():
                return path
        raise RuntimeError("No se pudo reservar un nombre único para la grabación")

    def capacity(self):
        cfg = self.settings.recordings
        used = sum(p.stat().st_size for p in self.directory.iterdir() if p.is_file())
        reserve = int(self.settings.max_call_seconds * 16000)
        free = shutil.disk_usage(self.directory).free
        return (
            used + reserve * (len(self.active) + 1) < cfg.max_storage_mb * 1024**2
            and free > cfg.min_free_mb * 1024**2 + reserve
        )

    async def start(self, session, evidence):
        jid = session.job["id"]
        if not self.settings.recordings.enabled or jid in self.active:
            return
        if self.ops.db.execute("SELECT 1 FROM recordings WHERE job_id=?", (jid,)).fetchone():
            return
        if not self.capacity():
            self.ops.alert(
                "recording_storage",
                "Espacio de grabaciones insuficiente",
                "No se inició una grabación. Revisa el límite y el espacio libre.",
                "error",
            )
            with self.ops.db:
                self.ops.db.execute(
                    "INSERT INTO recordings "
                    "(job_id,status,started_at,evidence,detail) VALUES(?,?,?,?,?)",
                    (jid, "failed", now(), evidence, "Límite de almacenamiento"),
                )
            return
        started_at = now()
        target = self._available_target(
            recording_filename(session.job, started_at, self.settings.reporting_timezone), jid
        )
        source = self.directory / f".{jid}.wav"
        with self.ops.db:
            self.ops.db.execute(
                "INSERT INTO recordings "
                "(job_id,status,started_at,evidence,filename) VALUES(?,?,?,?,?)",
                (jid, "recording", started_at, evidence, target.name),
            )
        try:
            await self.phone.start_recording(session.customer, source)
            source.chmod(0o600)
            self.active[jid] = (source, target)
            session.trace.event(
                "recording_started", evidence=evidence, filename=target.name
            )
        except Exception:
            with contextlib.suppress(Exception):
                await self.phone.stop_recording(session.customer)
            source.unlink(missing_ok=True)
            with self.ops.db:
                self.ops.db.execute(
                    "UPDATE recordings SET status='failed',detail=? WHERE job_id=?",
                    ("No se pudo iniciar la captura", jid),
                )
            self.ops.alert(
                "recording_capture",
                "Fallo al grabar audio",
                "La llamada continúa. Revisa el motor y el almacenamiento.",
                "error",
            )

    @staticmethod
    def compress(source, target):
        import soundfile as sf

        with sf.SoundFile(source) as src:
            duration = len(src) / src.samplerate
            if duration <= 0:
                raise ValueError("La captura no contiene audio")
            with sf.SoundFile(
                target,
                "w",
                samplerate=src.samplerate,
                channels=src.channels,
                format="OGG",
                subtype="OPUS",
                compression_level=0.85,
            ) as dst:
                for block in src.blocks(blocksize=32000, dtype="float32"):
                    dst.write(block)
        with sf.SoundFile(target) as check:
            if len(check) <= 0:
                raise ValueError("Audio comprimido vacío")
        target.chmod(0o600)
        return duration, target.stat().st_size

    async def finish(self, session):
        jid = session.job["id"]
        if jid not in self.active:
            return
        source, target = self.active[jid]
        try:
            await self.phone.stop_recording(session.customer)
            with self.ops.db:
                self.ops.db.execute(
                    "UPDATE recordings SET status='encoding',ended_at=? WHERE job_id=?",
                    (now(), jid),
                )
            async with self.workers:
                duration, size = await asyncio.to_thread(self.compress, source, target)
            with self.ops.db:
                self.ops.db.execute(
                    "UPDATE recordings SET status='ready',filename=?,"
                    "size_bytes=?,duration_seconds=? WHERE job_id=?",
                    (target.name, size, duration, jid),
                )
            session.trace.event(
                "recording_ready",
                filename=target.name,
                size_bytes=size,
                duration_seconds=duration,
            )
        except Exception:
            with self.ops.db:
                self.ops.db.execute(
                    "UPDATE recordings SET status='failed',detail=? WHERE job_id=?",
                    ("No se pudo finalizar el audio", jid),
                )
            self.ops.alert(
                "recording_encode",
                "Fallo al comprimir una grabación",
                "Consulta el CDR para identificar la llamada afectada.",
                "error",
            )
            target.unlink(missing_ok=True)
        finally:
            source.unlink(missing_ok=True)
            self.active.pop(jid, None)

    def recover(self):
        with self.ops.db:
            self.ops.db.execute(
                "UPDATE recordings SET status='failed',detail=? "
                "WHERE status IN ('recording','encoding')",
                ("Captura interrumpida por cierre del proceso",),
            )
        ready = {
            row["filename"]
            for row in self.ops.rows("SELECT filename FROM recordings WHERE status='ready'")
        }
        for path in self.directory.glob("*.ogg"):
            if path.name not in ready:
                path.unlink()
        for path in self.directory.glob("*.wav"):
            path.unlink()
        self.prune()

    def prune(self):
        cutoff = (
            datetime.now(UTC) - timedelta(days=self.settings.recordings.retention_days)
        ).isoformat()
        for row in self.ops.rows(
            "SELECT * FROM recordings WHERE status='ready' AND started_at<?", (cutoff,)
        ):
            filename = row["filename"]
            path = safe_recording_path(self.directory, filename)
            if path is not None:
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
            with self.ops.db:
                self.ops.db.execute(
                    "UPDATE recordings SET status='expired',filename=NULL WHERE job_id=?",
                    (row["job_id"],),
                )
        if self.capacity():
            self.ops.resolve("recording_storage")
