"""Native mixed WAV capture followed by bounded local Opus compression."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from datetime import UTC, datetime, timedelta

from blaster.store import now


class Recordings:
    def __init__(self, settings, ops, phone):
        self.settings, self.ops, self.phone = settings, ops, phone
        self.directory = settings.data_dir / "recordings"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        self.workers = asyncio.Semaphore(2)
        self.active = set()

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
        path = self.directory / (jid + ".wav")
        with self.ops.db:
            self.ops.db.execute(
                "INSERT INTO recordings "
                "(job_id,status,started_at,evidence,filename) VALUES(?,?,?,?,?)",
                (jid, "recording", now(), evidence, path.name),
            )
        try:
            await self.phone.start_recording(session.customer, path)
            path.chmod(0o600)
            self.active.add(jid)
            session.trace.event("recording_started", evidence=evidence)
        except Exception:
            with contextlib.suppress(Exception):
                await self.phone.stop_recording(session.customer)
            path.unlink(missing_ok=True)
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
        source, target = (self.directory / (jid + ext) for ext in (".wav", ".ogg"))
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
            session.trace.event("recording_ready", size_bytes=size, duration_seconds=duration)
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
            self.active.discard(jid)

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
            if filename and filename == row["job_id"] + ".ogg":
                with contextlib.suppress(FileNotFoundError):
                    (self.directory / filename).unlink()
            with self.ops.db:
                self.ops.db.execute(
                    "UPDATE recordings SET status='expired',filename=NULL WHERE job_id=?",
                    (row["job_id"],),
                )
        if self.capacity():
            self.ops.resolve("recording_storage")
