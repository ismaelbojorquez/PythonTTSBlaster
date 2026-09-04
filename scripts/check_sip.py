"""One SIP registration attempt using config.toml; no calls, TTS, or web server."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blaster.config import Settings, load_settings  # noqa: E402

STATUS = {
    200: "OK",
    401: "solicitud de autenticación",
    403: "acceso rechazado por el servidor",
    404: "cuenta o dominio no encontrado",
    407: "solicitud de autenticación del proxy",
    408: "tiempo de espera agotado",
    423: "intervalo de registro demasiado corto",
    503: "servicio no disponible",
}


def register_once(settings: Settings) -> int:
    import pjsua2 as pj

    sip = settings.sip
    result = None
    closing = False
    account = None
    ep = pj.Endpoint()

    class SummaryLog(pj.LogWriter):
        def write(self, entry):
            # Only emit locally constructed summaries: no SIP headers, Digest, or raw logs.
            if not re.search(r"(?im)^CSeq:\s*\d+\s+REGISTER\s*$", entry.msg):
                return
            if re.search(r"\bTX \d+ bytes", entry.msg):
                action = "cierre del registro" if closing else "registro"
                print(f"TX REGISTER — {action}", flush=True)
            elif re.search(r"\bRX \d+ bytes", entry.msg):
                match = re.search(r"(?m)^SIP/2\.0 (\d{3})\b", entry.msg)
                if match:
                    code = int(match[1])
                    print(f"RX {code} — {STATUS.get(code, 'respuesta SIP')}", flush=True)

    class RegistrationAccount(pj.Account):
        def onRegState(self, prm):
            nonlocal result
            if not closing and prm.code >= 200:
                info = self.getInfo()
                result = (bool(info.regIsActive), prm.code, prm.status, bool(prm.rdata.wholeMsg))

        def onIncomingCall(self, prm):
            call = pj.Call(self, prm.callId)
            params = pj.CallOpParam()
            params.statusCode = 486
            call.hangup(params)

    def destroy(obj):
        type(obj).__swig_destroy__(obj)
        obj.thisown = False

    try:
        ep.libCreate()
        config = pj.EpConfig()
        config.uaConfig.threadCnt = 0
        config.uaConfig.mainThreadOnly = True
        config.logConfig.level = 4
        config.logConfig.consoleLevel = 4
        config.logConfig.msgLogging = True
        writer = SummaryLog()
        config.logConfig.writer = writer
        # PJSUA2's Endpoint takes ownership of this native LogWriter.
        writer.thisown = False
        ep.libInit(config)
        transport = pj.TransportConfig()
        transport.port = sip.local_port
        transport.boundAddress = sip.bind_address
        transport.publicAddress = sip.public_address
        kind = pj.PJSIP_TRANSPORT_UDP if sip.transport == "udp" else pj.PJSIP_TRANSPORT_TCP
        transport_id = ep.transportCreate(kind, transport)
        ep.libStart()

        cfg = pj.AccountConfig()
        cfg.idUri = f"sip:{sip.caller_id or sip.username}@{sip.domain}"
        cfg.sipConfig.transportId = transport_id
        cfg.regConfig.registrarUri = sip.registrar or f"sip:{sip.domain}"
        cfg.regConfig.registerOnAdd = True
        cfg.regConfig.retryIntervalSec = 0
        cfg.regConfig.unregWaitMsec = 2000
        if sip.proxy:
            cfg.sipConfig.proxies.append(sip.proxy)
        cfg.sipConfig.authCreds.append(
            pj.AuthCredInfo("digest", "*", sip.auth_username or sip.username, 0, sip.password)
        )
        account = RegistrationAccount()
        print(
            f"Cuenta en {sip.domain}; transporte {sip.transport.upper()}; "
            f"puerto local {sip.local_port}.",
            flush=True,
        )
        print(
            "Intentando registro; espera hasta 45 segundos. No se realizarán llamadas.", flush=True
        )
        account.create(cfg)
        deadline = time.monotonic() + 45
        while result is None and time.monotonic() < deadline:
            ep.libHandleEvents(50)
        if result is None:
            print("SIN RESULTADO: se agotaron los 45 segundos de la prueba.", flush=True)
            return 1
        active, code, status, received = result
        origin = "respuesta recibida del servidor" if received else "resultado local de PJSIP"
        print(f"Resultado: {code} — {STATUS.get(code, 'estado SIP')} ({origin}).", flush=True)
        if active and 200 <= code < 300:
            print("REGISTRO CORRECTO. El servidor aceptó la cuenta.", flush=True)
            return 0
        if code == 408 and not received:
            print("No se recibió una respuesta final a tiempo; revisa destino, red y filtro de IP.")
        elif code in (401, 407):
            print(
                "No se completó la autenticación; revisa usuario, contraseña "
                "y requisitos del proveedor."
            )
        if status:
            print(f"Código interno de PJSIP: {status}", flush=True)
        return 1
    except pj.Error as error:
        # Native errors can embed account details; print only the numeric status.
        print(f"Error local PJSIP: {error.status}. Revisa configuración, puerto y conectividad.")
        return 2
    finally:
        closing = True
        if account is not None:
            with contextlib.suppress(pj.Error):
                account.shutdown()
            destroy(account)
        with contextlib.suppress(pj.Error):
            ep.libDestroy()
        destroy(ep)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--trunk", help="Identificador de la troncal; por defecto, la primera")
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        profiles = settings.trunk_profiles()
        selected = (
            next((t for t in profiles if t.id == args.trunk), None) if args.trunk else profiles[0]
        )
        if selected is None:
            raise ValueError("No existe esa troncal en el TOML")
        settings.sip = selected.sip
        if not settings.sip.registration_enabled:
            raise ValueError(
                "Esta prueba usa REGISTER. Tu troncal tiene registration_enabled = false."
            )
        if not settings.sip.domain or not settings.sip.username or not settings.sip.password:
            raise ValueError("Completa sip.domain, sip.username y sip.password en el TOML.")
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with (settings.data_dir / "app.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("Detén el panel con Ctrl+C antes de ejecutar la prueba SIP.", file=sys.stderr)
                return 2
            return register_once(settings)
    except ImportError:
        print("Falta pjsua2. Ejecuta el script con .venv/bin/python.", file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"No se pudo ejecutar la prueba: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nPrueba interrumpida.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
