"""Local-only SIP peer used by the opt-in native integration test."""

import contextlib
import math
import struct
import sys
import time
import wave
from pathlib import Path

import pjsua2 as pj


def run(directory: Path, port: int):
    ep = pj.Endpoint()
    ep.libCreate()
    cfg = pj.EpConfig()
    cfg.uaConfig.threadCnt = 0
    cfg.uaConfig.mainThreadOnly = True
    cfg.uaConfig.maxCalls = 8
    cfg.logConfig.level = 1
    cfg.logConfig.consoleLevel = 1
    ep.libInit(cfg)
    transport = pj.TransportConfig()
    transport.port = port
    transport.boundAddress = "127.0.0.1"
    ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, transport)
    ep.libStart()
    ep.audDevManager().setNullDev()
    for codec in ep.codecEnum2():
        ep.codecSetPriority(codec.codecId, 0)
    ep.codecSetPriority("PCMU/8000/1", 255)
    calls, retired, dirty = {}, set(), set()

    def destroy(obj):
        type(obj).__swig_destroy__(obj)
        obj.thisown = False

    class PeerCall(pj.Call):
        def __init__(self, call_id):
            super().__init__(account, call_id)
            self.name = self.getInfo().localUri.split("sip:")[1].split("@")[0]
            self.player = self.recorder = None
            self.answer_at = None

        def onCallState(self, prm):
            if self.getInfo().state == pj.PJSIP_INV_STATE_DISCONNECTED:
                retired.add(self.name)
            else:
                dirty.add(self.name)

        def onCallMediaState(self, prm):
            dirty.add(self.name)

        def onDtmfDigit(self, prm):
            (directory / f"digit-{self.name}").write_text(prm.digit)

        def start_audio(self):
            info = self.getInfo()
            if self.player or info.state != pj.PJSIP_INV_STATE_CONFIRMED:
                return
            if not any(m.status == pj.PJSUA_CALL_MEDIA_ACTIVE for m in info.media):
                return
            media = self.getAudioMedia(-1)
            frequency = 600 if self.name == "100" else 900
            path = directory / f"tone-{self.name}.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                wav.writeframes(
                    b"".join(
                        struct.pack("<h", int(6000 * math.sin(2 * math.pi * frequency * i / 8000)))
                        for i in range(8000)
                    )
                )
            self.player = pj.AudioMediaPlayer()
            source = directory / f"source-{self.name}.wav"
            self.player.createPlayer(
                str(source if source.exists() else path),
                pj.PJMEDIA_FILE_NO_LOOP if source.exists() else 0,
            )
            self.player.startTransmit(media)
            self.recorder = pj.AudioMediaRecorder()
            self.recorder.createRecorder(str(directory / f"received-{self.name}.wav"))
            media.startTransmit(self.recorder)
            (directory / f"ready-{self.name}").touch()

    class PeerAccount(pj.Account):
        def onIncomingCall(self, prm):
            call = PeerCall(prm.callId)
            calls[call.name] = call
            (directory / f"invite-{call.name}").touch()
            params = pj.CallOpParam()
            params.statusCode = 403 if call.name == "403" else 200
            if call.name == "403":
                params.reason = "Forbidden: outbound route denied"
            delay = directory / "agent-answer-delay"
            if call.name == "200" and delay.exists():
                params.statusCode = 180
                call.answer_at = time.monotonic() + float(delay.read_text())
            call.answer(params)

    account = PeerAccount()
    cfg = pj.AccountConfig()
    cfg.idUri = f"sip:peer@127.0.0.1:{port}"
    cfg.regConfig.registerOnAdd = False
    cfg.mediaConfig.transportConfig.boundAddress = "127.0.0.1"
    cfg.mediaConfig.transportConfig.port = 0
    account.create(cfg)
    (directory / "ready").touch()
    deadline = time.monotonic() + 30
    try:
        while not (directory / "stop").exists() and time.monotonic() < deadline:
            ep.libHandleEvents(10)
            for call in list(calls.values()):
                if (
                    call.name not in retired and call.answer_at is not None
                    and time.monotonic() >= call.answer_at
                ):
                    call.answer_at = None
                    params = pj.CallOpParam()
                    params.statusCode = 200
                    call.answer(params)
            for name in list(dirty):
                dirty.discard(name)
                if name in calls and name not in retired:
                    calls[name].start_audio()
            send = directory / "send-digit"
            if send.exists():
                name, digit = send.read_text().split(":")
                send.unlink()
                calls[name].dialDtmf(digit)
            hangup = directory / "hangup"
            if hangup.exists():
                name = hangup.read_text()
                hangup.unlink()
                calls[name].hangup(pj.CallOpParam())
            for name in list(retired):
                retired.discard(name)
                call = calls.pop(name)
                if call.player:
                    destroy(call.player)
                    destroy(call.recorder)
                    call.player = call.recorder = None
                destroy(call)
                (directory / f"closed-{name}").touch()
                call = None
    finally:
        ep.hangupAllCalls()
        for _ in range(20):
            ep.libHandleEvents(10)
        for call in calls.values():
            with contextlib.suppress(Exception):
                if call.player:
                    destroy(call.player)
                    destroy(call.recorder)
                    call.player = call.recorder = None
                destroy(call)
        calls.clear()
        call = None
        account.shutdown()
        destroy(account)
        ep.libDestroy()
        destroy(ep)


if __name__ == "__main__":
    run(Path(sys.argv[1]), int(sys.argv[2]))
