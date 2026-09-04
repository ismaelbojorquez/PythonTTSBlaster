#!/usr/bin/env python3
"""Evaluate a local PCM WAV with the configured AMD rules, without opening SIP."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import wave
from collections import Counter
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blaster.amd import DETECTOR_VERSION, Detector  # noqa: E402
from blaster.config import load_settings  # noqa: E402


def analyze(path, settings):
    detector = Detector(settings)
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 8000):
            raise ValueError("El WAV debe ser PCM de 16 bits, mono, a 8000 Hz")
        while detector.result is None:
            pcm = wav.readframes(160)
            if not pcm:
                break
            detector.feed(pcm)
    return detector.result or detector.finish(
        "unknown", "insufficient_audio" if detector.audio_ms else "no_audio"
    )


def read_manifest(path):
    samples, seen = [], set()
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not {"wav", "label"}.issubset(reader.fieldnames or []):
            raise ValueError("El CSV requiere encabezados wav,label (human o machine)")
        for line, row in enumerate(reader, 2):
            label, filename = (row.get("label") or "").strip(), (row.get("wav") or "").strip()
            if not filename or label not in {"human", "machine"}:
                raise ValueError(f"Fila {line}: indica WAV y etiqueta human o machine")
            wav = (path.parent / filename).resolve()
            if wav in seen:
                raise ValueError(f"Fila {line}: el mismo WAV aparece más de una vez")
            seen.add(wav)
            samples.append((filename, wav, label))
            if len(samples) > 500:
                raise ValueError("Evalúa como máximo 500 muestras por lote")
    if not samples:
        raise ValueError("El CSV no contiene muestras")
    return samples


def evaluate(samples, settings):
    matrix = {label: dict.fromkeys(("human", "machine", "unknown"), 0)
              for label in ("human", "machine")}
    results = []
    for filename, path, label in samples:
        result = analyze(path, settings)
        matrix[label][result.verdict] += 1
        results.append({"wav": filename, "label": label, **asdict(result)})
    count = len(results)
    correct = matrix["human"]["human"] + matrix["machine"]["machine"]
    unknown = matrix["human"]["unknown"] + matrix["machine"]["unknown"]
    reasons = Counter(row["reason"] for row in results)
    return {
        "detector_version": DETECTOR_VERSION,
        "parameters": settings.model_dump(),
        "samples": count,
        "labels": {label: sum(row.values()) for label, row in matrix.items()},
        "confusion": matrix,
        "accuracy_all_samples": correct / count,
        "unknown_samples": unknown,
        "decision_coverage": (count - unknown) / count,
        "humans_rejected_by_policy": matrix["human"]["machine"] + (
            matrix["human"]["unknown"] if settings.unknown_action == "hangup" else 0
        ),
        "machines_allowed_by_policy": matrix["machine"]["human"] + (
            matrix["machine"]["unknown"] if settings.unknown_action == "continue" else 0
        ),
        "mean_audio_ms": sum(row["audio_ms"] for row in results) / count,
        "reasons": dict(reasons),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prueba AMD local sin llamadas ni IA")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--wav", type=Path, help="PCM16 mono a 8000 Hz")
    inputs.add_argument("--manifest", type=Path, help="CSV wav,label con human o machine")
    parser.add_argument("--compare-config", type=Path, help="Compara otro TOML con este detector")
    parser.add_argument("--report", type=Path, help="Guarda el resultado JSON del lote")
    args = parser.parse_args()
    if not args.manifest and (args.compare_config or args.report):
        parser.error("--compare-config y --report requieren --manifest")
    try:
        settings = load_settings(args.config).amd
        if args.manifest:
            samples = read_manifest(args.manifest)
            report = {
                "note": "Resultados de estas muestras; no estiman la precisión de toda la troncal. "
                        "Las dos configuraciones usan el mismo detector actual. "
                        "No se modificó config.toml ni se guardó audio.",
                "current": evaluate(samples, settings),
            }
            if args.compare_config:
                report["comparison"] = evaluate(samples, load_settings(args.compare_config).amd)
            content = json.dumps(report, ensure_ascii=False, indent=2)
            if args.report:
                # Do not overwrite existing files, credentials, manifests or samples.
                fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(content + "\n")
            print(content)
        else:
            result = analyze(args.wav, settings)
            # elapsed_ms is audio duration here, not execution time.
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
            print(result.detail)
        print("Prueba de archivo local; no se abrió la troncal ni se realizaron llamadas.")
    except (OSError, ValueError, wave.Error, EOFError, csv.Error) as error:
        parser.exit(2, f"No se pudo analizar: {error}\n")


if __name__ == "__main__":
    main()
