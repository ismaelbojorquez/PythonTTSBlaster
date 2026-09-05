"""JSON-lines worker for the optional Kokoro ONNX environment."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path


def emit(stream, payload: dict) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    stream.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--voices", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--language", default="es")
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()

    protocol = sys.stdout
    sys.stdout = sys.stderr
    try:
        import soundfile as sf
        from kokoro_onnx import Kokoro

        started = time.perf_counter()
        engine = Kokoro(args.model, args.voices)
        emit(
            protocol,
            {
                "event": "ready",
                "load_ms": round((time.perf_counter() - started) * 1000, 1),
                "sample_rate": 24000,
            },
        )
        for line in sys.stdin:
            request = json.loads(line)
            if request.get("action") == "close":
                break
            target = Path(request["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            started = time.perf_counter()
            audio, sample_rate = engine.create(
                request["text"],
                voice=args.voice,
                speed=args.speed,
                lang=args.language,
            )
            sf.write(target, audio, sample_rate, subtype="PCM_16")
            elapsed = (time.perf_counter() - started) * 1000
            duration = len(audio) / sample_rate
            emit(
                protocol,
                {
                    "event": "generated",
                    "generation_ms": round(elapsed, 1),
                    "audio_seconds": round(duration, 3),
                    "real_time_factor": round(elapsed / 1000 / duration, 3),
                },
            )
    except BaseException as error:
        emit(protocol, {"error": f"{type(error).__name__}: {error}"})
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
