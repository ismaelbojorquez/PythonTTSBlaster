"""Local AMD using energy, timing and spectral tone purity. No ML or recordings.

PCM contract: 8 kHz, mono, signed 16-bit native endian. The native conference
bridge converts codecs/rates before delivering audio. Analysis runs outside its
clock callback. This is a heuristic, not proof that the speaker is human.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

from blaster.config import AMDSettings
from blaster.telephony.base import CallEnded, Leg, first

RATE = 8000
FRAME_MS = 20
SAMPLES = RATE * FRAME_MS // 1000
FRAME_BYTES = SAMPLES * 2

REASONS = {
    "short_greeting": "saludo breve seguido de una pausa",
    "long_greeting": "saludo con demasiada voz acumulada",
    "many_words": "demasiados segmentos de voz en el saludo",
    "beep": "tono sostenido compatible con buzón",
    "initial_silence": "sin saludo válido dentro del tiempo inicial",
    "analysis_timeout": "se agotó el tiempo de análisis",
    "no_audio": "no se recibieron muestras de audio",
    "insufficient_audio": "el archivo terminó antes de poder decidir",
    "audio_overflow": "se perdieron muestras por saturación del análisis",
    "invalid_audio": "formato de audio inválido",
}


@dataclass(frozen=True)
class AMDResult:
    verdict: Literal["human", "machine", "unknown"]
    reason: str
    elapsed_ms: int
    audio_ms: int
    voiced_ms: int
    words: int

    @property
    def detail(self) -> str:
        label = {"human": "Humano probable", "machine": "Buzón probable", "unknown": "Incierto"}
        return (
            f"AMD: {label[self.verdict]}; {REASONS[self.reason]}; "
            f"{self.elapsed_ms / 1000:.2f} s; voz {self.voiced_ms} ms; "
            f"segmentos {self.words}"
        )


class Detector:
    """One detector per call. Voice segments are not linguistic words.

    A short burst must last minimum_word_ms to qualify as a greeting. Beeps
    require a stable, nearly single-frequency signal across several windows;
    DTMF/dial tones with two comparable components do not satisfy that rule.
    """

    def __init__(self, settings: AMDSettings):
        self.settings = settings
        self.pending = bytearray()
        self.audio_ms = self.voiced_ms = self.words = 0
        self.voice_run_ms = self.silence_ms = 0
        self.word_counted = False
        self.previous = None
        self.beep_ms = 0
        self.beep_frequency = None
        self.window = np.hanning(SAMPLES * 2)
        self.result: AMDResult | None = None

    def finish(self, verdict, reason) -> AMDResult:
        if self.result is None:
            self.result = AMDResult(
                verdict, reason, self.audio_ms, self.audio_ms, self.voiced_ms, self.words
            )
        return self.result

    def feed(self, pcm: bytes) -> AMDResult | None:
        if self.result is not None:
            return self.result
        self.pending.extend(pcm)
        while len(self.pending) >= FRAME_BYTES:
            samples = np.frombuffer(bytes(self.pending[:FRAME_BYTES]), dtype=np.int16).astype(float)
            del self.pending[:FRAME_BYTES]
            result = self._frame(samples)
            if result is not None:
                return result
        return None

    def _tone(self, samples, voiced: bool) -> bool:
        cfg = self.settings
        frequency = None
        if cfg.beep_enabled and voiced and self.previous is not None:
            signal = np.concatenate((self.previous, samples)) * self.window
            power = np.abs(np.fft.rfft(signal)) ** 2
            peak = int(np.argmax(power[1:])) + 1
            total = float(power.sum())
            purity = float(power[max(1, peak - 1) : peak + 2].sum()) / max(total, 1)
            hz = peak * RATE / len(signal)
            if cfg.beep_min_hz <= hz <= cfg.beep_max_hz and purity >= cfg.beep_purity:
                frequency = hz
        self.previous = samples
        if frequency is None:
            self.beep_ms = 0
            self.beep_frequency = None
            return False
        if (
            self.beep_frequency is None
            or abs(frequency - self.beep_frequency) > cfg.beep_frequency_tolerance_hz
        ):
            self.beep_ms = 0
            self.beep_frequency = frequency
        self.beep_ms += FRAME_MS
        return self.beep_ms >= cfg.beep_min_ms

    def _frame(self, samples) -> AMDResult | None:
        cfg = self.settings
        self.audio_ms += FRAME_MS
        samples -= samples.mean()  # DC offset is not speech.
        voiced = float(np.sqrt(np.mean(samples * samples))) >= cfg.silence_threshold
        if self._tone(samples, voiced):
            return self.finish("machine", "beep")
        if voiced:
            if self.silence_ms >= cfg.between_words_silence_ms:
                self.voice_run_ms = 0
                self.word_counted = False
            self.silence_ms = 0
            self.voice_run_ms += FRAME_MS
            self.voiced_ms += FRAME_MS
            if self.voice_run_ms >= cfg.minimum_word_ms and not self.word_counted:
                self.words += 1
                self.word_counted = True
            if self.words > cfg.maximum_words:
                return self.finish("machine", "many_words")
            if self.words and self.voiced_ms >= cfg.greeting_speech_ms:
                return self.finish("machine", "long_greeting")
        else:
            self.silence_ms += FRAME_MS
            if not self.word_counted:
                self.voice_run_ms = 0  # Separate clicks cannot form a valid word.
            if self.words and self.silence_ms >= cfg.after_greeting_silence_ms:
                return self.finish("human", "short_greeting")
        if not self.words and self.audio_ms >= cfg.initial_silence_ms:
            return self.finish("unknown", "initial_silence")
        if self.audio_ms >= cfg.total_analysis_ms:
            return self.finish("unknown", "analysis_timeout")
        return None


async def detect(leg: Leg, settings: AMDSettings) -> AMDResult:
    """Silently inspect only the answered customer's inbound audio, with a wall deadline."""
    detector = Detector(settings)
    loop = asyncio.get_running_loop()
    started = loop.time()

    async def listen():
        async with leg.capture_audio() as stream:
            while True:
                pcm = await stream.read()
                if stream.error:
                    return detector.finish("unknown", stream.error)
                result = detector.feed(pcm)
                if result:
                    return result

    try:
        async with asyncio.timeout(settings.total_analysis_ms / 1000):
            index, result = await first(leg.closed.wait(), listen())
        if index == 0 or leg.closed.is_set():
            raise CallEnded(leg.code, leg.reason)
    except TimeoutError:
        result = detector.finish("unknown", "analysis_timeout" if detector.audio_ms else "no_audio")
    return replace(result, elapsed_ms=round((loop.time() - started) * 1000))
