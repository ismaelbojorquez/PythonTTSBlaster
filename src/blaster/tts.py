from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import queue
import struct
import wave
from collections import deque
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


class _KokoroProcess:
    def __init__(self, settings, worker_path: Path):
        self.settings = settings
        self.worker_path = worker_path
        self.process = None
        self.stderr_task = None
        self.stderr_tail: deque[str] = deque(maxlen=20)
        self.load_ms: float | None = None

    def command(self) -> list[str]:
        return [
            str(self.settings.python),
            "-u",
            str(self.worker_path),
            "--model",
            str(self.settings.model),
            "--voices",
            str(self.settings.voices),
            "--voice",
            self.settings.voice,
            "--language",
            self.settings.language,
            "--speed",
            str(self.settings.speed),
        ]

    async def drain_stderr(self) -> None:
        while self.process and self.process.stderr:
            line = await self.process.stderr.readline()
            if not line:
                return
            self.stderr_tail.append(line.decode("utf-8", "replace").strip())

    async def response(self) -> dict:
        if not self.process or not self.process.stdout:
            raise RuntimeError("La voz Kokoro no está iniciada")
        line = await self.process.stdout.readline()
        if not line:
            detail = self.stderr_tail[-1] if self.stderr_tail else "el proceso terminó"
            raise RuntimeError(f"La voz Kokoro dejó de responder: {detail}")
        response = json.loads(line)
        if response.get("error"):
            raise RuntimeError(str(response["error"]))
        return response

    async def start(self) -> None:
        environment = os.environ.copy()
        environment["ONNX_PROVIDER"] = "CPUExecutionProvider"
        started = asyncio.get_running_loop().time()
        self.process = await asyncio.create_subprocess_exec(
            *self.command(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
        self.stderr_task = asyncio.create_task(self.drain_stderr())
        async with asyncio.timeout(self.settings.startup_timeout):
            response = await self.response()
        if response.get("event") != "ready":
            raise RuntimeError("La voz Kokoro no confirmó su inicio")
        self.load_ms = (asyncio.get_running_loop().time() - started) * 1000

    async def synthesize(self, text: str, path: Path) -> dict:
        if not self.process or not self.process.stdin or self.process.returncode is not None:
            raise RuntimeError("La voz Kokoro no está disponible")
        request = json.dumps({"text": text, "path": str(path.resolve())}, ensure_ascii=False)
        self.process.stdin.write((request + "\n").encode("utf-8"))
        await self.process.stdin.drain()
        response = await self.response()
        if response.get("event") != "generated" or not path.is_file() or not path.stat().st_size:
            raise RuntimeError("Kokoro no produjo un archivo de audio válido")
        return response

    async def close(self) -> None:
        process, self.process = self.process, None
        if process and process.returncode is None:
            if process.stdin:
                with contextlib.suppress(Exception):
                    process.stdin.write(b'{"action":"close"}\n')
                    await process.stdin.drain()
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(5):
                    await process.wait()
            if process.returncode is None:
                process.terminate()
                with contextlib.suppress(Exception):
                    await process.wait()
        if self.stderr_task:
            self.stderr_task.cancel()
            await asyncio.gather(self.stderr_task, return_exceptions=True)
            self.stderr_task = None


class KokoroSpeech:
    """Pool of isolated, persistent Kokoro ONNX workers."""

    names = {
        "ef_dora": "Kokoro Dora",
        "em_alex": "Kokoro Alex",
        "em_santa": "Kokoro Santa",
    }

    def __init__(self, settings, workers: int, worker_path: Path | None = None):
        self.settings = settings
        self.worker_count = workers
        self.worker_path = worker_path or Path(__file__).with_name("kokoro_worker.py")
        self.processes: list[_KokoroProcess] = []
        self.available: asyncio.Queue[_KokoroProcess] = asyncio.Queue()
        self.load_ms: float | None = None
        self.last_metrics: dict = {}

    @property
    def display_name(self) -> str:
        return self.names.get(self.settings.voice, self.settings.voice)

    async def start(self) -> None:
        if self.processes:
            return
        if not self.settings.enabled:
            raise ValueError("Kokoro no está habilitado")
        if not all(
            path.is_file()
            for path in (self.settings.python, self.settings.model, self.settings.voices)
        ):
            raise ValueError("Falta instalar Kokoro y sus voces")
        processes = [
            _KokoroProcess(self.settings, self.worker_path) for _ in range(self.worker_count)
        ]
        started = asyncio.get_running_loop().time()
        try:
            await asyncio.gather(*(process.start() for process in processes))
        except BaseException:
            await asyncio.gather(*(process.close() for process in processes))
            raise
        self.processes = processes
        self.load_ms = (asyncio.get_running_loop().time() - started) * 1000
        for process in processes:
            self.available.put_nowait(process)

    async def synthesize(self, text: str, path: Path) -> Path:
        process = await self.available.get()
        work = asyncio.create_task(process.synthesize(text, path))
        try:
            self.last_metrics = await asyncio.shield(work)
            return path
        except asyncio.CancelledError:
            self.last_metrics = await work
            raise
        finally:
            if process.process and process.process.returncode is None:
                self.available.put_nowait(process)

    async def close(self) -> None:
        processes, self.processes = self.processes, []
        await asyncio.gather(*(process.close() for process in processes))


async def close_speech(speech) -> None:
    closer = getattr(speech, "close", None)
    if closer:
        await closer()


def speech_for(settings, workers: int | None = None):
    count = workers or settings.tts_workers
    if settings.tts_engine == "kokoro":
        return KokoroSpeech(settings.kokoro, count)
    return PiperSpeech(settings.voice_model, count)
