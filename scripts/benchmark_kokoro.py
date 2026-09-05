#!/usr/bin/env python3
"""Generate a sample through the same Kokoro wrapper used by live calls."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blaster.config import load_settings  # noqa: E402
from blaster.tts import KokoroSpeech  # noqa: E402
from blaster.voices import recommendation  # noqa: E402

DEFAULT_TEXT = (
    "Hola Ana. Te recordamos que tu pago vence el doce de septiembre. "
    "Presiona uno para repetir o dos para hablar con un agente."
)


async def benchmark(config: Path, text: str, output: Path) -> dict:
    settings = load_settings(config)
    if not settings.kokoro.enabled:
        raise ValueError("Activa kokoro.enabled en config.toml para realizar la prueba")
    speech = KokoroSpeech(settings.kokoro, 1)
    try:
        await speech.start()
        await speech.synthesize(text, output)
        with wave.open(str(output), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
        generation_ms = float(speech.last_metrics["generation_ms"])
        return {
            "engine": "Kokoro ONNX 1.0",
            "voice": settings.kokoro.voice,
            "workers": 1,
            "load_ms": round(speech.load_ms or 0, 1),
            "generation_ms": generation_ms,
            "audio_seconds": round(seconds, 3),
            "real_time_factor": round(generation_ms / 1000 / seconds, 3),
            "recommendation": recommendation(generation_ms, seconds),
            "output": str(output.resolve()),
        }
    finally:
        await speech.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Medición local de Kokoro")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument(
        "--output", type=Path, default=Path(".cache/kokoro/benchmarks/integrated.wav")
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        print(json.dumps(asyncio.run(benchmark(args.config, args.text, args.output)), indent=2))
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        parser.exit(2, f"No se pudo completar la medición: {error}\n")


if __name__ == "__main__":
    main()
