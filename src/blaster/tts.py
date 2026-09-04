from __future__ import annotations

import asyncio
import math
import queue
import struct
import wave
from pathlib import Path


def write_tone(path: Path, seconds: float = 2) -> None:
    """Local, low-volume waiting tone. No device, network, or third party service."""
    rate = 8000
    pcm = bytearray()
    for i in range(int(rate * seconds)):
        t = i / rate
        envelope = min(1, (t % 2) * 50, max(0, (0.8 - t % 2) * 50))
        value = int(1800 * envelope * math.sin(2 * math.pi * 440 * t))
        pcm.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)


class SimulatedSpeech:
    async def start(self) -> None:
        pass

    async def synthesize(self, text: str, path: Path) -> Path:
        # Simulation models elapsed speech time; it does not claim to generate voice.
        with wave.open(str(path), "wb") as wav:
            wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\0\0" * int(8000 * min(5, max(0.2, len(text) / 65))))
        return path


class PiperSpeech:
    """Bounded pool of in-process voices. A voice is never shared concurrently."""

    def __init__(self, model: Path, workers: int):
        self.model = model
        self.workers = workers
        self.voices: queue.Queue = queue.Queue()

    async def start(self) -> None:
        await asyncio.to_thread(self._load)

    def _load(self) -> None:
        from piper import PiperVoice

        for _ in range(self.workers):
            self.voices.put(PiperVoice.load(str(self.model)))

    async def synthesize(self, text: str, path: Path) -> Path:
        work = asyncio.create_task(asyncio.to_thread(self._synthesize, text, path))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            # Python cannot interrupt native inference. Join before deleting its WAV.
            await work
            raise

    def _synthesize(self, text: str, path: Path) -> Path:
        voice = self.voices.get()
        try:
            with wave.open(str(path), "wb") as wav:
                voice.synthesize_wav(text, wav)
            return path
        finally:
            self.voices.put(voice)
