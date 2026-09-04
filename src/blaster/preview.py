"""Ephemeral voice previews, using the same Piper synthesis as outgoing calls."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, Field

from blaster.countries import country_code
from blaster.models import MENU, MissingTemplateVariable, parse_contacts, render_message
from blaster.tts import PiperSpeech


class AudioPreviewInput(BaseModel):
    template: str = Field(min_length=1, max_length=4000)
    csv_text: str = Field(default="", max_length=8_000_000)
    country: str = "MX"

    def sample(self):
        region = country_code(self.country)
        contact = parse_contacts(self.csv_text, region)[0] if self.csv_text.strip() else None
        variables = (
            {**contact.variables, "telefono": contact.phone, "credito": contact.credit_id}
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
        if self.speech is None:
            model = self.settings.voice_model
            if not model.is_file() or not Path(str(model) + ".json").is_file():
                raise ValueError("Falta la voz local. Revisa voice_model en config.toml.")
            speech = PiperSpeech(model, 1)
            loading = asyncio.create_task(speech.start())
            try:
                await asyncio.shield(loading)
            except asyncio.CancelledError:
                # Native loading cannot be interrupted; finish before allowing another load.
                await loading
                self.speech = speech
                raise
            self.speech = speech
        with TemporaryDirectory(prefix="blaster-voice-preview-") as folder:
            path = Path(folder) / "preview.wav"
            await self.speech.synthesize(f"{message}\n{MENU}", path)
            audio = await asyncio.to_thread(path.read_bytes)
        return {
            "message": message,
            "phone": phone,
            "voice": self.settings.voice_model.stem,
            "audio_base64": base64.b64encode(audio).decode("ascii"),
        }
