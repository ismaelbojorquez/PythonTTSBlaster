from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from blaster.dialing import DialFormat


class SIPSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    domain: str = ""
    username: str = ""
    auth_username: str = ""
    caller_id: str = ""
    password: str = Field(default="", repr=False, exclude=True)
    registrar: str = ""
    proxy: str = ""
    registration_enabled: bool = True
    dial_format: DialFormat = "as_entered"
    transport: Literal["udp", "tcp"] = "udp"
    bind_address: str = "0.0.0.0"
    public_address: str = ""
    local_port: int = Field(default=5060, ge=1024, le=65535)
    rtp_port: int = Field(default=10000, ge=1024, le=65000)
    rtp_port_range: int = Field(default=200, ge=4, le=4000)

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", value):
            raise ValueError("domain debe ser un host o host:puerto, sin sip:")
        return value

    @field_validator("username", "auth_username", "caller_id")
    @classmethod
    def valid_identity(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z0-9_.+%-]+", value):
            raise ValueError("Identidad SIP inválida")
        return value

    @field_validator("registrar", "proxy")
    @classmethod
    def valid_uri(cls, value: str) -> str:
        if value and (not value.startswith("sip:") or re.search(r"[\s<>]", value)):
            raise ValueError("Usa una URI sip: sin espacios")
        return value


class AMDSettings(BaseModel):
    """Deterministic PCM analysis; durations in milliseconds, no trained models."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False  # Existing configurations keep their previous call flow.
    unknown_action: Literal["hangup", "continue"] = "hangup"
    total_analysis_ms: int = Field(default=6500, ge=1000, le=15000)
    initial_silence_ms: int = Field(default=5000, ge=500, le=10000)
    after_greeting_silence_ms: int = Field(default=1000, ge=300, le=3000)
    greeting_speech_ms: int = Field(default=2400, ge=500, le=10000)
    minimum_word_ms: int = Field(default=100, ge=40, le=500)
    minimum_human_speech_ms: int = Field(default=200, ge=40, le=2000)
    between_words_silence_ms: int = Field(default=100, ge=40, le=500)
    maximum_words: int = Field(default=5, ge=2, le=20)
    silence_threshold: int = Field(default=256, ge=32, le=5000)
    beep_enabled: bool = True
    beep_min_ms: int = Field(default=240, ge=100, le=1000)
    beep_min_hz: int = Field(default=600, ge=400, le=3000)
    beep_max_hz: int = Field(default=2000, ge=500, le=3500)
    beep_purity: float = Field(default=0.90, ge=0.8, le=0.99)
    beep_frequency_tolerance_hz: int = Field(default=35, ge=10, le=100)
    calibration_capture_enabled: bool = False
    calibration_retention_days: int = Field(default=14, ge=1, le=365)
    calibration_max_samples: int = Field(default=500, ge=10, le=5000)

    @model_validator(mode="after")
    def coherent_timings(self) -> AMDSettings:
        if max(self.initial_silence_ms, self.greeting_speech_ms) > self.total_analysis_ms:
            raise ValueError("Los límites de silencio/saludo AMD deben caber en total_analysis_ms")
        if self.minimum_word_ms + self.after_greeting_silence_ms > self.total_analysis_ms:
            raise ValueError("El saludo y su pausa AMD deben caber en total_analysis_ms")
        if max(self.minimum_word_ms, self.minimum_human_speech_ms) >= self.greeting_speech_ms:
            raise ValueError("La voz mínima humana debe ser menor que el saludo de buzón AMD")
        if self.minimum_human_speech_ms + self.after_greeting_silence_ms > self.total_analysis_ms:
            raise ValueError("La voz mínima humana y su pausa deben caber en total_analysis_ms")
        if self.between_words_silence_ms >= self.after_greeting_silence_ms:
            raise ValueError("La pausa entre palabras AMD debe ser menor que la pausa final")
        if self.beep_min_hz >= self.beep_max_hz:
            raise ValueError("beep_min_hz debe ser menor que beep_max_hz")
        return self


class TrunkSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    priority: int = Field(default=10, ge=0, le=1000)
    weight: int = Field(default=1, ge=1, le=100)
    channels: int = Field(default=40, ge=2, le=60)
    calls_per_second: float = Field(default=1, gt=0, le=20)
    sip: SIPSettings = Field(default_factory=SIPSettings)


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    enabled: bool = True
    session_hours: int = Field(default=8, ge=1, le=72)
    bootstrap_username: str = Field(default="", pattern=r"^$|^[a-zA-Z0-9_.@-]{1,80}$")
    bootstrap_password: str = Field(default="", max_length=256, repr=False, exclude=True)
    bootstrap_display_name: str = Field(default="Administrador", min_length=1, max_length=100)

    @model_validator(mode="after")
    def bootstrap_credentials(self) -> AuthSettings:
        if bool(self.bootstrap_username) != bool(self.bootstrap_password):
            raise ValueError("Configura juntos auth.bootstrap_username y auth.bootstrap_password")
        if self.bootstrap_password and len(self.bootstrap_password) < 12:
            raise ValueError("auth.bootstrap_password necesita al menos 12 caracteres")
        return self


class RecordingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    retention_days: int = Field(default=30, ge=1, le=3650)
    max_storage_mb: int = Field(default=10240, ge=100, le=1000000)
    min_free_mb: int = Field(default=256, ge=50, le=100000)


class AutomationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    poll_seconds: float = Field(default=5, ge=0.1, le=60)
    late_schedule_minutes: int = Field(default=60, ge=1, le=1440)
    trunk_alert_seconds: int = Field(default=60, ge=5, le=3600)
    failure_alert_percent: int = Field(default=50, ge=1, le=100)
    failure_alert_min_calls: int = Field(default=10, ge=1, le=1000)
    report_retention_days: int = Field(default=90, ge=1, le=3650)


class KokoroSettings(BaseModel):
    """Optional commercial-friendly TTS engine isolated from the main environment."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    python: Path = Path(".venv-kokoro/bin/python")
    model: Path = Path(".cache/kokoro/models/kokoro-v1.0.onnx")
    voices: Path = Path(".cache/kokoro/models/voices-v1.0.bin")
    voice: str = Field(default="ef_dora", pattern=r"^[a-z]{2}_[a-z0-9_]+$", max_length=80)
    language: str = Field(default="es", pattern=r"^[a-z]{2}(?:-[a-z]{2})?$", max_length=10)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    startup_timeout: float = Field(default=90, ge=10, le=600)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    mode: Literal["simulation", "sip"] = "simulation"
    web_port: int = Field(default=8765, ge=1024, le=65535)
    web_public_url: str = ""
    data_dir: Path = Path("data")
    reporting_timezone: str = "America/Mexico_City"
    report_max_rows: int = Field(default=20000, ge=100, le=100000)
    concurrency: int = Field(default=20, ge=1, le=30)
    trunk_channels: int = Field(default=40, ge=2, le=60)
    calls_per_second: float = Field(default=1, gt=0, le=20)
    ring_timeout: float = Field(default=40, gt=0, le=180)
    agent_timeout: float = Field(default=30, gt=0, le=180)
    choice_timeout: float = Field(default=12, gt=0, le=120)
    max_call_seconds: float = Field(default=1800, gt=0, le=14400)
    max_repeats: int = Field(default=2, ge=0, le=10)
    tts_workers: int = Field(default=2, ge=1, le=8)
    tts_timeout: float = Field(default=90, gt=0, le=300)
    tts_engine: Literal["piper", "kokoro"] = "piper"
    voice_model: Path = Path("voices/es_MX-claude-high.onnx")
    kokoro: KokoroSettings = Field(default_factory=KokoroSettings)
    sip: SIPSettings = Field(default_factory=SIPSettings)
    amd: AMDSettings = Field(default_factory=AMDSettings)
    trunks: list[TrunkSettings] = Field(default_factory=list, max_length=8)
    routing: Literal["priority", "weighted"] = "priority"
    auth: AuthSettings = Field(default_factory=AuthSettings)
    recordings: RecordingSettings = Field(default_factory=RecordingSettings)
    automation: AutomationSettings = Field(default_factory=AutomationSettings)
    config_path: Path | None = Field(default=None, exclude=True)

    @field_validator("web_public_url")
    @classmethod
    def public_origin(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(r"[A-Za-z0-9.-]+", parsed.hostname)
            or re.search(r"\s", value)
        ):
            raise ValueError(
                "web_public_url debe ser la URL pública http(s), sin ruta ni credenciales"
            )
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("Puerto inválido en web_public_url")
        authority = parsed.hostname.lower()
        if port is not None and port != {"http": 80, "https": 443}[parsed.scheme]:
            authority += f":{port}"
        return f"{parsed.scheme}://{authority}"

    def trunk_profiles(self) -> list[TrunkSettings]:
        return self.trunks or [
            TrunkSettings(
                id="default",
                name="Troncal principal",
                sip=self.sip,
                channels=self.trunk_channels,
                calls_per_second=self.calls_per_second,
            )
        ]

    @model_validator(mode="after")
    def check_capacity(self) -> Settings:
        if self.web_public_url and not self.auth.enabled:
            raise ValueError("El acceso por dominio requiere auth.enabled = true")
        try:
            ZoneInfo(self.reporting_timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("reporting_timezone debe ser una zona IANA válida") from error
        if self.concurrency * 2 > self.trunk_channels:
            raise ValueError("Se necesitan al menos 2 canales por llamada concurrente")
        if not self.trunks:
            if self.sip.rtp_port + self.sip.rtp_port_range > 65535:
                raise ValueError("El rango RTP excede 65535")
            if self.sip.rtp_port % 2 or self.sip.rtp_port_range < self.trunk_channels * 2:
                raise ValueError("RTP necesita puerto inicial par y 2 puertos por canal")
        if len({t.id for t in self.trunks}) != len(self.trunks):
            raise ValueError("Cada troncal debe tener un id único")
        if self.tts_engine == "kokoro" and not self.kokoro.enabled:
            raise ValueError("Activa kokoro.enabled para usar una voz Kokoro")
        for trunk in self.trunks:
            sip = trunk.sip
            if (
                sip.rtp_port % 2
                or sip.rtp_port_range < trunk.channels * 2
                or sip.rtp_port + sip.rtp_port_range > 65535
            ):
                raise ValueError(f"Rango RTP insuficiente o inválido: {trunk.id}")
        return self

    def validate_live(self) -> None:
        for trunk in self.trunk_profiles():
            if not trunk.enabled:
                continue
            if not trunk.sip.domain or not trunk.sip.username:
                raise ValueError(f"Configura dominio y usuario de la troncal {trunk.id}")
            if trunk.sip.registration_enabled and not trunk.sip.password:
                raise ValueError(
                    f"Configura sip.password en config.toml para la troncal {trunk.id}"
                )
        if self.tts_engine == "piper":
            if not self.voice_model.is_file() or not Path(f"{self.voice_model}.json").is_file():
                raise ValueError("Faltan el modelo Piper .onnx y su archivo .onnx.json")
        elif self.tts_engine == "kokoro" and not all(
            path.is_file() for path in (self.kokoro.python, self.kokoro.model, self.kokoro.voices)
        ):
            raise ValueError("Faltan los archivos locales de Kokoro")


def load_settings(path: Path | None) -> Settings:
    if path is None:
        return Settings()
    with path.open("rb") as source:
        data = tomllib.load(source)
    settings = Settings.model_validate(data)
    settings.config_path = path.resolve()
    # Las rutas de la configuración se resuelven junto a su archivo.
    for key in ("data_dir", "voice_model"):
        value = getattr(settings, key)
        if not value.is_absolute():
            setattr(settings, key, path.resolve().parent / value)
    for key in ("python", "model", "voices"):
        value = getattr(settings.kokoro, key)
        if not value.is_absolute():
            setattr(settings.kokoro, key, path.resolve().parent / value)
    return settings
