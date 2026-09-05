"""Ephemeral voice previews, using the same Piper synthesis as outgoing calls."""

from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, Field

from blaster.countries import country_code
from blaster.models import MENU, MissingTemplateVariable, parse_contacts, render_message
from blaster.tts import PiperSpeech, speech_for
from blaster.voices import recommendation, wav_duration


class AudioPreviewInput(BaseModel):
    template: str = Field(min_length=1, max_length=4000)
    csv_text: str = Field(default="", max_length=8_000_000)
    country: str = "MX"

    def sample(self):
        region = country_code(self.country)
        contact = parse_contacts(self.csv_text, region)[0] if self.csv_text.strip() else None
        variables = (
            {
                **contact.variables,
                "telefono": contact.phone,
                "phone": contact.phone,
                "telephone": contact.phone,
                "credito": contact.credit_id,
                "credit": contact.credit_id,
                "account": contact.credit_id,
                "account_id": contact.credit_id,
            }
            if contact
            else {}
        )
        try:
            message = render_message(self.template, variables)
        except MissingTemplateVariable as error:
            if contact:
                raise
            raise ValueError(
                f"Agrega un contacto con la columna {error.name} o reemplaza "
                f"{{{error.name}}} por texto para escuchar la muestra."
            ) from error
        return message, contact.phone if contact else None


class SpeechPreview:
    def __init__(self, settings, speech=None):
        self.settings, self.speech = settings, speech
        self.lock = asyncio.Lock()

    async def generate(self, message, phone):
        load_ms = None
        if self.speech is None:
            if self.settings.tts_engine == "piper":
                model = self.settings.voice_model
                if not model.is_file() or not Path(str(model) + ".json").is_file():
                    raise ValueError("Falta la voz local. Revisa voice_model en config.toml.")
            speech = (
                PiperSpeech(self.settings.voice_model, 1)
                if self.settings.tts_engine == "piper"
                else speech_for(self.settings, 1)
            )
            started = time.perf_counter()
            loading = asyncio.create_task(speech.start())
            try:
                await asyncio.shield(loading)
            except asyncio.CancelledError:
                # Native loading cannot be interrupted; finish before allowing another load.
                await loading
                self.speech = speech
                raise
            self.speech = speech
            load_ms = (time.perf_counter() - started) * 1000
        with TemporaryDirectory(prefix="blaster-voice-preview-") as folder:
            path = Path(folder) / "preview.wav"
            started = time.perf_counter()
            await self.speech.synthesize(f"{message}\n{MENU}", path)
            generation_ms = (time.perf_counter() - started) * 1000
            audio_seconds = await asyncio.to_thread(wav_duration, path)
            audio = await asyncio.to_thread(path.read_bytes)
        ratio = generation_ms / 1000 / audio_seconds if audio_seconds else 0
        return {
            "message": message,
            "phone": phone,
            "voice": getattr(self.speech, "display_name", self.settings.voice_model.stem),
            "load_ms": round(load_ms, 1) if load_ms is not None else None,
            "model_cached": load_ms is None,
            "generation_ms": round(generation_ms, 1),
            "audio_seconds": round(audio_seconds, 2),
            "real_time_factor": round(ratio, 3),
            "recommendation": recommendation(generation_ms, audio_seconds),
            "audio_base64": base64.b64encode(audio).decode("ascii"),
        }
