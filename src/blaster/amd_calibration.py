"""Temporary, bounded AMD greeting samples for operator calibration."""

from __future__ import annotations

import json
import sqlite3
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from blaster.store import now


def migrate(db, path: Path) -> None:
    if db.execute("PRAGMA user_version").fetchone()[0] >= 8:
        return
    if db.execute("SELECT 1 FROM jobs LIMIT 1").fetchone():
        backup = path.with_name(f"{path.name}.before-amd-calibration-{uuid4().hex[:8]}.bak")
        with sqlite3.connect(backup) as target:
            db.backup(target)
        backup.chmod(0o600)
    db.executescript("""
        BEGIN;
        CREATE TABLE IF NOT EXISTS amd_calibration_samples (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
            filename TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            size_bytes INTEGER NOT NULL,
            predicted_verdict TEXT NOT NULL
                CHECK(predicted_verdict IN ('human','machine','unknown')),
            predicted_reason TEXT NOT NULL,
            elapsed_ms INTEGER NOT NULL,
            audio_ms INTEGER NOT NULL,
            voiced_ms INTEGER NOT NULL,
            words INTEGER NOT NULL,
            detector_version TEXT NOT NULL,
            parameters TEXT NOT NULL,
            label TEXT CHECK(label IN ('human','machine')),
            labeled_at TEXT,
            labeled_by TEXT
        );
        CREATE INDEX IF NOT EXISTS amd_calibration_created
            ON amd_calibration_samples(created_at DESC);
        CREATE INDEX IF NOT EXISTS amd_calibration_label
            ON amd_calibration_samples(label,created_at DESC);
        PRAGMA user_version=8;
        COMMIT;
    """)


class AMDCalibration:
    def __init__(self, settings, store):
        self.settings, self.store, self.db = settings, store, store.db
        self.directory = settings.data_dir / "amd-calibration"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o700)

    @property
    def config(self):
        return self.settings.amd

    def _file(self, filename: str) -> Path:
        if not filename.endswith(".wav") or len(filename) != 36:
            raise ValueError("Nombre de muestra AMD inválido")
        sample_id = filename[:-4]
        if not all(character in "0123456789abcdef" for character in sample_id):
            raise ValueError("Nombre de muestra AMD inválido")
        return self.directory / filename

    def save(self, job: dict, result, pcm: bytes, detector_version: str, parameters: dict):
        if not self.config.calibration_capture_enabled or not pcm:
            return None
        maximum = self.config.total_analysis_ms * 8 * 2
        pcm = pcm[:maximum]
        sample_id = uuid4().hex
        filename = sample_id + ".wav"
        target = self._file(filename)
        temporary = self.directory / ("." + filename + ".tmp")
        with wave.open(str(temporary), "wb") as output:
            output.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            output.writeframes(pcm)
        temporary.chmod(0o600)
        temporary.replace(target)
        duration_ms = len(pcm) * 1000 // (8000 * 2)
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO amd_calibration_samples "
                    "(id,job_id,filename,created_at,duration_ms,size_bytes,predicted_verdict,"
                    "predicted_reason,elapsed_ms,audio_ms,voiced_ms,words,detector_version,"
                    "parameters) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        sample_id,
                        job["id"],
                        filename,
                        now(),
                        duration_ms,
                        target.stat().st_size,
                        result.verdict,
                        result.reason,
                        result.elapsed_ms,
                        result.audio_ms,
                        result.voiced_ms,
                        result.words,
                        detector_version,
                        json.dumps(parameters, ensure_ascii=False),
                    ),
                )
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        self.prune()
        return sample_id

    def prune(self) -> int:
        for temporary in self.directory.glob(".*.wav.tmp"):
            temporary.unlink(missing_ok=True)
        cutoff = (datetime.now(UTC) - timedelta(
            days=self.config.calibration_retention_days
        )).isoformat()
        rows = list(self.db.execute(
            "SELECT id,filename FROM amd_calibration_samples WHERE created_at<?",
            (cutoff,),
        ))
        remaining = self.db.execute(
            "SELECT COUNT(*) FROM amd_calibration_samples WHERE created_at>=?", (cutoff,)
        ).fetchone()[0]
        excess = max(0, remaining - self.config.calibration_max_samples)
        if excess:
            rows.extend(self.db.execute(
                "SELECT id,filename FROM amd_calibration_samples WHERE created_at>=? "
                "ORDER BY (label IS NULL),created_at LIMIT ?", (cutoff, excess),
            ))
        deleted = self._delete_rows(rows)
        known = {
            row["filename"]
            for row in self.db.execute("SELECT filename FROM amd_calibration_samples")
        }
        for path in self.directory.glob("*.wav"):
            if path.name not in known:
                path.unlink(missing_ok=True)
        return deleted

    def _delete_rows(self, rows) -> int:
        unique = {row["id"]: row["filename"] for row in rows}
        if not unique:
            return 0
        with self.db:
            self.db.executemany(
                "DELETE FROM amd_calibration_samples WHERE id=?",
                ((sample_id,) for sample_id in unique),
            )
        for filename in unique.values():
            self._file(filename).unlink(missing_ok=True)
        return len(unique)

    def summary(self) -> dict:
        row = self.db.execute(
            "SELECT COUNT(*) AS total,COUNT(label) AS reviewed,"
            "COUNT(CASE WHEN label IS NULL THEN 1 END) AS pending,"
            "COUNT(CASE WHEN label='human' THEN 1 END) AS human,"
            "COUNT(CASE WHEN label='machine' THEN 1 END) AS machine,"
            "COUNT(CASE WHEN label IS NOT NULL AND predicted_verdict IN ('human','machine') "
            "THEN 1 END) AS comparable,"
            "COUNT(CASE WHEN label=predicted_verdict THEN 1 END) AS matches,"
            "COALESCE(SUM(size_bytes),0) AS size_bytes FROM amd_calibration_samples"
        ).fetchone()
        result = dict(row)
        result["agreement_percent"] = (
            round(result["matches"] * 100 / result["comparable"], 1)
            if result["comparable"] else None
        )
        result["capture_enabled"] = self.config.calibration_capture_enabled
        result["retention_days"] = self.config.calibration_retention_days
        result["max_samples"] = self.config.calibration_max_samples
        result["capture_seconds"] = self.config.total_analysis_ms / 1000
        return result

    def list(self, label: str = "pending", limit: int = 100, offset: int = 0) -> dict:
        clauses, values = [], []
        if label == "pending":
            clauses.append("s.label IS NULL")
        elif label in {"human", "machine"}:
            clauses.append("s.label=?")
            values.append(label)
        elif label == "disagreement":
            clauses.append(
                "s.label IS NOT NULL AND s.predicted_verdict IN ('human','machine') "
                "AND s.label<>s.predicted_verdict"
            )
        elif label != "all":
            raise ValueError("Filtro de calibración no válido")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        total = self.db.execute(
            "SELECT COUNT(*) FROM amd_calibration_samples s" + where, values
        ).fetchone()[0]
        rows = self.db.execute(
            "SELECT s.id,s.job_id,s.created_at,s.duration_ms,s.size_bytes,"
            "s.predicted_verdict,s.predicted_reason,s.elapsed_ms,s.audio_ms,s.voiced_ms,"
            "s.words,s.detector_version,s.label,s.labeled_at,s.labeled_by,"
            "j.phone,j.credit_id,c.name AS campaign_name,c.mode "
            "FROM amd_calibration_samples s JOIN jobs j ON j.id=s.job_id "
            "JOIN campaigns c ON c.id=j.campaign_id" + where
            + " ORDER BY s.created_at DESC,s.id LIMIT ? OFFSET ?",
            (*values, limit, offset),
        )
        return {
            "summary": self.summary(),
            "filter": label,
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [dict(row) for row in rows],
        }

    def get(self, sample_id: str):
        row = self.db.execute(
            "SELECT * FROM amd_calibration_samples WHERE id=?", (sample_id,)
        ).fetchone()
        if not row:
            raise KeyError(sample_id)
        return dict(row)

    def label(self, sample_id: str, label: str, actor: dict) -> dict:
        if label not in {"human", "machine"}:
            raise ValueError("La etiqueta debe ser Persona o Buzón")
        row = self.get(sample_id)
        stamp = now()
        with self.db:
            self.db.execute(
                "UPDATE amd_calibration_samples SET label=?,labeled_at=?,labeled_by=? "
                "WHERE id=?",
                (label, stamp, actor.get("username", "local"), sample_id),
            )
        return {"id": sample_id, "label": label, "previous": row["label"]}

    def delete(self, sample_id: str) -> dict:
        row = self.get(sample_id)
        self._delete_rows([row])
        return row

    def delete_all(self) -> int:
        return self._delete_rows(list(self.db.execute(
            "SELECT id,filename FROM amd_calibration_samples"
        )))
