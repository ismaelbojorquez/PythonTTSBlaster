from __future__ import annotations

import asyncio
import queue
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from blaster.telemetry import CallEvent


class CallEnded(Exception):
    def __init__(self, code: int = 0, reason: str = ""):
        self.code = code
        text = "".join(char if char.isprintable() else " " for char in reason)
        self.reason = " ".join(text.split())[:240]
        self.detail = f"Respuesta SIP {code}" + (f": {self.reason}" if self.reason else "")
        super().__init__(self.detail)


@dataclass(frozen=True)
class CallProgress:
    event: Literal["invite_sent", "response"]
    timestamp: float
    code: int = 0


class AudioStream:
    """Bounded mailbox from the native media clock to the asyncio consumer.

    No disk I/O, blocking waits or unbounded call_soon callbacks on the clock.
    One second of 20 ms PCM frames is the maximum retained per call.
    """

    def __init__(self):
        self.frames: queue.Queue[bytes] = queue.Queue(maxsize=50)
        self.error: str | None = None
        self.stopped = False

    def push(self, pcm: bytes) -> None:
        if self.stopped or self.error:
            return
        if len(pcm) != 320:
            self.error = "invalid_audio"
            return
        try:
            self.frames.put_nowait(pcm)
        except queue.Full:
            self.error = "audio_overflow"

    async def read(self) -> bytes:
        while not self.error and not self.stopped:
            try:
                return self.frames.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
        if self.stopped:
            raise CallEnded()
        return b""

    def stop(self) -> None:
        self.stopped = True
        while True:
            try:
                self.frames.get_nowait()
            except queue.Empty:
                break


async def first(*awaitables):
    """Return (index, result), cancelling and collecting all losing operations."""
    tasks = [asyncio.ensure_future(item) for item in awaitables]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        winner = next(task for task in tasks if task in done)
        return tasks.index(winner), winner.result()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class Leg(ABC):
    def __init__(self, number: str, role: str):
        self.id = uuid4().hex
        self.number = number
        self.role = role
        self.ready = asyncio.Event()
        self.closed = asyncio.Event()
        self.digits: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
        self.progress: asyncio.Queue[CallProgress] = asyncio.Queue(maxsize=16)
        self.code = 0
        self.reason = ""
        self.observer = None
        self.termination = None
        self._milestones = set()

    def emit(self, kind: str, **data) -> None:
        self.record(CallEvent(kind, data))

    def record(self, event: CallEvent) -> None:
        if event.kind in {"invite_sent", "ringing", "answered", "media_ready", "closed"}:
            if event.kind in self._milestones:
                return
            self._milestones.add(event.kind)
        if self.observer:
            self.observer(event)

    def end_by(self, actor: str, reason: str, evidence: str) -> None:
        if self.termination is None:
            self.termination = (actor, reason, evidence)
            self.emit("termination", actor=actor, reason=reason, evidence=evidence)

    async def wait_ready(self, timeout: float) -> None:
        async with asyncio.timeout(timeout):
            await first(self.closed.wait(), self.ready.wait())
        if self.closed.is_set():
            raise CallEnded(self.code, self.reason)

    def receive_digit(self, digit: str) -> None:
        if not self.closed.is_set() and not self.digits.full():
            if digit in {"1", "2"}:
                self.emit("dtmf", digit=digit, actor=self.role)
            self.digits.put_nowait(digit)

    @abstractmethod
    async def play(self, path: Path, *, loop: bool = False) -> None: ...

    @abstractmethod
    async def hangup(self) -> None: ...

    @asynccontextmanager
    async def capture_audio(self):
        raise NotImplementedError("Este motor no ofrece captura PCM para AMD")
        yield  # pragma: no cover


class Telephony(ABC):
    status = "Desconectada"
    available = False
    on_leg = None

    def track(self, leg: Leg) -> None:
        if self.on_leg:
            self.on_leg(leg)

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def dial(self, number: str, role: str) -> Leg: ...

    async def dial_on(self, number, role, trunk_id):
        return await self.dial(number, role)

    async def start_recording(self, customer, path):
        raise NotImplementedError("Grabación no soportada por este motor")

    async def stop_recording(self, customer):
        return None

    @abstractmethod
    async def bridge(self, customer: Leg, agent: Leg) -> None: ...
