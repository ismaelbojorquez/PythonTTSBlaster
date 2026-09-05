"""Discovery and local performance measurements for installed Piper voices."""

from __future__ import annotations

import asyncio
import base64
import json
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from blaster.tts import KokoroSpeech, PiperSpeech, close_speech

BENCHMARK_TEXT = (
    "Hola, esta es una prueba de velocidad para mensajes personalizados "
    "generados durante una llamada."
)
KOKORO_PREFIX = "kokoro:"
KOKORO_VOICES = {
    "ef_dora": "Dora",
    "em_alex": "Alex",
    "em_santa": "Santa",
}


def recommendation(generation_ms: float, audio_seconds: float) -> dict[str, str]:
    """Classify observed synthesis latency for the live call workflow."""
    ratio = generation_ms / 1000 / audio_seconds if audio_seconds > 0 else float("inf")
    if generation_ms <= 3000 and ratio <= 0.5:
        return {
            "code": "recommended",
            "label": "Recomendada para campañas",
            "detail": (
                "Prepara el mensaje con rapidez y ofrece una espera mínima "
                "antes de la llamada."
            ),
        }
    if generation_ms <= 6000 and ratio <= 1:
        return {
            "code": "acceptable",
            "label": "Adecuada para campañas medianas",
            "detail": (
                "Puede añadir una espera breve. Prueba la cantidad de llamadas simultáneas "
                "antes de una campaña grande."
            ),
        }
    return {
        "code": "not_recommended",
        "label": "No recomendada para campañas",
        "detail": "La preparación puede retrasar el inicio de las llamadas en este equipo.",
    }


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


class VoiceManager:
    """Keeps model discovery bounded and benchmark results scoped to this process."""

    def __init__(self, settings):
        self.settings = settings
        self.lock = asyncio.Lock()
        self.results: dict[str, dict] = {}

    @property
    def root(self) -> Path:
        return self.settings.voice_model.parent.resolve()

    def resolve(self, model_id: str) -> Path:
        if not model_id or len(model_id) > 255 or "\\" in model_id:
            raise ValueError("Selecciona una voz local válida")
        root = self.root
        candidate = (root / model_id).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError("La voz debe estar dentro del directorio de voces") from error
        config = Path(str(candidate) + ".json").resolve()
        try:
            config.relative_to(root)
        except ValueError as error:
            raise ValueError(
                "La configuración de voz debe estar en el directorio de voces"
            ) from error
        if candidate.suffix.lower() != ".onnx":
            raise ValueError("La voz debe ser un modelo Piper .onnx")
        if not candidate.is_file() or not config.is_file():
            raise ValueError("La voz requiere los archivos .onnx y .onnx.json")
        return candidate

    def model_id(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError as error:
            raise ValueError("La voz activa debe estar dentro del directorio de voces") from error

    def describe(self, path: Path) -> dict:
        model_id = self.model_id(path)
        metadata = {}
        try:
            metadata = json.loads(Path(str(path) + ".json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            pass
        language = metadata.get("language") or {}
        audio = metadata.get("audio") or {}
        dataset = str(metadata.get("dataset") or path.stem).replace("_", " ")
        quality = str(audio.get("quality") or "unknown").lower()
        quality_label = {"high": "Alta", "medium": "Media", "low": "Baja"}.get(
            quality, "Sin especificar"
        )
        code = str(language.get("code") or "").replace("_", "-")
        return {
            "id": model_id,
            "provider": "piper",
            "name": dataset.title(),
            "language": str(language.get("name_native") or code or "Sin especificar"),
            "language_code": code,
            "quality": quality,
            "quality_label": quality_label,
            "sample_rate": audio.get("sample_rate"),
            "size_mb": round(path.stat().st_size / 1048576, 1),
            "active": (
                self.settings.tts_engine == "piper"
                and path.resolve() == self.settings.voice_model.resolve()
            ),
            "benchmark": self.results.get(model_id),
        }

    def kokoro_voice(self, model_id: str) -> str:
        if not model_id.startswith(KOKORO_PREFIX):
            raise ValueError("Selecciona una voz válida")
        voice = model_id.removeprefix(KOKORO_PREFIX)
        if voice not in KOKORO_VOICES:
            raise ValueError("Selecciona una voz Kokoro disponible")
        return voice

    def describe_kokoro(self, voice: str) -> dict:
        model_id = KOKORO_PREFIX + voice
        size = (
            self.settings.kokoro.model.stat().st_size
            + self.settings.kokoro.voices.stat().st_size
        )
        return {
            "id": model_id,
            "provider": "kokoro",
            "name": f"Kokoro {KOKORO_VOICES[voice]}",
            "language": "Español",
            "language_code": "es",
            "quality": "natural",
            "quality_label": "Voz natural",
            "sample_rate": 24000,
            "size_mb": round(size / 1048576, 1),
            "active": (
                self.settings.tts_engine == "kokoro"
                and self.settings.kokoro.voice == voice
            ),
            "benchmark": self.results.get(model_id),
            "commercial_use": True,
        }

    def catalog(self) -> dict:
        root = self.root
        paths = []
        if root.is_dir():
            for path in sorted(root.rglob("*.onnx")):
                try:
                    safe = self.resolve(path.relative_to(root).as_posix())
                except ValueError:
                    continue
                paths.append(safe)
                if len(paths) == 100:
                    break
        active = self.settings.voice_model.resolve()
        if active.is_file() and Path(str(active) + ".json").is_file() and active not in paths:
            paths.append(active)
        items = [self.describe(path) for path in paths]
        if self.settings.kokoro.enabled:
            items.extend(self.describe_kokoro(voice) for voice in KOKORO_VOICES)
        return {
            "directory": str(root),
            "benchmark_text": BENCHMARK_TEXT,
            "tts_workers": self.settings.tts_workers,
            "items": items,
        }

    async def measure(self, model_id: str, workers: int = 1) -> tuple[object, dict, bytes]:
        if model_id.startswith(KOKORO_PREFIX):
            if not self.settings.kokoro.enabled:
                raise ValueError("Kokoro no está habilitado")
            config = self.settings.kokoro.model_copy(
                update={"voice": self.kokoro_voice(model_id)}
            )
            speech = KokoroSpeech(config, workers)
        else:
            model = self.resolve(model_id)
            speech = PiperSpeech(model, workers)
        started = time.perf_counter()
        loading = asyncio.create_task(speech.start())
        try:
            await asyncio.shield(loading)
        except asyncio.CancelledError:
            # Loading runs in native code. Join it before releasing the operation lock.
            await loading
            raise
        try:
            load_ms = (time.perf_counter() - started) * 1000
            with TemporaryDirectory(prefix="blaster-voice-benchmark-") as folder:
                target = Path(folder) / "benchmark.wav"
                started = time.perf_counter()
                await speech.synthesize(BENCHMARK_TEXT, target)
                generation_ms = (time.perf_counter() - started) * 1000
                audio_seconds = await asyncio.to_thread(wav_duration, target)
                audio = await asyncio.to_thread(target.read_bytes)
        except BaseException:
            await close_speech(speech)
            raise
        ratio = generation_ms / 1000 / audio_seconds if audio_seconds else 0
        result = {
            "measured_at": datetime.now(UTC).isoformat(),
            "workers": workers,
            "load_ms": round(load_ms, 1),
            "generation_ms": round(generation_ms, 1),
            "audio_seconds": round(audio_seconds, 2),
            "real_time_factor": round(ratio, 3),
            "recommendation": recommendation(generation_ms, audio_seconds),
        }
        self.results[model_id] = result
        return speech, result, audio

    def response(self, model_id: str, result: dict, audio: bytes) -> dict:
        return {
            **(
                self.describe_kokoro(self.kokoro_voice(model_id))
                if model_id.startswith(KOKORO_PREFIX)
                else self.describe(self.resolve(model_id))
            ),
            "benchmark": result,
            "audio_base64": base64.b64encode(audio).decode("ascii"),
        }
