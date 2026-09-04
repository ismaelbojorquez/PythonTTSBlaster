#!/usr/bin/env python3
"""Evaluate a local PCM WAV with the configured AMD rules, without opening SIP."""

from __future__ import annotations

import argparse
import json
import sys
import wave
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blaster.amd import Detector  # noqa: E402
from blaster.config import load_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Prueba AMD local sin llamadas ni IA")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--wav", type=Path, required=True, help="PCM16 mono a 8000 Hz")
    args = parser.parse_args()
    try:
        detector = Detector(load_settings(args.config).amd)
        with wave.open(str(args.wav), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 8000):
                raise ValueError("El WAV debe ser PCM de 16 bits, mono, a 8000 Hz")
            while detector.result is None:
                pcm = wav.readframes(160)
                if not pcm:
                    break
                detector.feed(pcm)
        result = detector.result or detector.finish(
            "unknown", "insufficient_audio" if detector.audio_ms else "no_audio"
        )
        # In this offline tool elapsed_ms is audio duration, not execution time.
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        print(result.detail)
        print("Prueba de archivo local; no se abrió la troncal ni se realizaron llamadas.")
    except (OSError, ValueError, wave.Error) as error:
        parser.exit(2, f"No se pudo analizar: {error}\n")


if __name__ == "__main__":
    main()
