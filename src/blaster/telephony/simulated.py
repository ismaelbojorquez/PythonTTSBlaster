from __future__ import annotations

import asyncio
import math
import struct
import wave
from contextlib import asynccontextmanager
from pathlib import Path

from blaster.telephony.base import AudioStream, CallEnded, Leg, Telephony


class SimulatedLeg(Leg):
    def __init__(self, number: str, role: str, backend: SimulatedTelephony):
        super().__init__(number, role)
        self.backend = backend
        self.play_count = 0
        self.playing = False
        self.answer_task = asyncio.create_task(self._answer())
        self.capturing = False

    @asynccontextmanager
    async def capture_audio(self):
        stream = AudioStream()
        self.capturing = True

        async def produce():
            pcm = self.backend.amd_audio.get(self.number)
            if pcm is None:
                # Artificial multi-frequency greeting, not a claim about real accuracy.
                pcm = b"".join(
                    struct.pack(
                        "<h",
                        int(
                            sum(
                                1800 * math.sin(2 * math.pi * hz * i / 8000)
                                for hz in (170, 430, 790)
                            )
                        ),
                    )
                    for i in range(3200)
                )
            for index in range(0, len(pcm), 320):
                stream.push(pcm[index : index + 320].ljust(320, b"\0"))
                await asyncio.sleep(max(0.001, 0.02 * self.backend.audio_speed))
            while True:
                stream.push(bytes(320))
                await asyncio.sleep(max(0.001, 0.02 * self.backend.audio_speed))

        task = asyncio.create_task(produce())
        try:
            yield stream
        finally:
            stream.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.capturing = False

    async def _answer(self) -> None:
        await asyncio.sleep(self.backend.answer_delay)
        code = self.backend.outcomes.get(self.number, 200)
        if code != 200:
            self.code = code
            self.end_by("trunk", "sip_response", "simulation")
            self.emit("closed", code=code)
            self.closed.set()
        else:
            self.emit("answered")
            self.emit("media_ready")
            self.ready.set()

    async def play(self, path: Path, *, loop: bool = False) -> None:
        if self.closed.is_set():
            raise CallEnded(self.code)
        self.play_count += 1
        self.playing = True
        try:
            with wave.open(str(path), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
            if loop:
                await asyncio.Future()
            else:
                await asyncio.sleep(duration * self.backend.audio_speed)
        finally:
            self.playing = False

    async def hangup(self) -> None:
        if not self.closed.is_set():
            self.end_by("system", "cleanup", "simulation")
        self.emit("closed", code=self.code)
        self.answer_task.cancel()
        await asyncio.gather(self.answer_task, return_exceptions=True)
        self.closed.set()
        self.backend.legs.pop(self.id, None)


class SimulatedTelephony(Telephony):
    def __init__(self, *, answer_delay: float = 0.7, audio_speed: float = 1):
        self.answer_delay = answer_delay
        self.audio_speed = audio_speed
        self.outcomes: dict[str, int] = {}
        self.amd_audio: dict[str, bytes] = {}
        self.legs: dict[str, SimulatedLeg] = {}
        self.bridges: list[tuple[str, str]] = []
        self.max_live_legs = 0
        self.recordings = {}
        self.selected_trunk = "default"

    async def start(self) -> None:
        self.status = "Simulación lista"
        self.available = True

    async def stop(self) -> None:
        for leg in list(self.legs.values()):
            await leg.hangup()
        self.available = False

    async def dial(self, number: str, role: str) -> SimulatedLeg:
        leg = SimulatedLeg(number, role, self)
        leg.trunk_id = self.selected_trunk
        self.legs[leg.id] = leg
        self.track(leg)
        leg.emit("invite_sent")
        leg.emit("ringing")
        self.max_live_legs = max(self.max_live_legs, len(self.legs))
        return leg

    async def dial_on(self, number, role, trunk_id):
        self.selected_trunk = trunk_id
        return await self.dial(number, role)

    async def start_recording(self, customer, path):
        # Simulation generates synthetic silence; it is never a real conversation.
        self.recordings[customer.id] = (path, asyncio.get_running_loop().time())
        with wave.open(str(path), "wb") as wav:
            wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            wav.writeframes(bytes(320))

    async def stop_recording(self, customer):
        item = self.recordings.pop(customer.id, None)
        if item:
            path, started = item
            frames = max(160, int((asyncio.get_running_loop().time() - started) * 8000))
            with wave.open(str(path), "wb") as wav:
                wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                wav.writeframes(bytes(frames * 2))

    async def bridge(self, customer: Leg, agent: Leg) -> None:
        if customer.closed.is_set() or agent.closed.is_set():
            raise CallEnded()
        self.bridges.append((customer.id, agent.id))
