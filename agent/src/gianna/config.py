from pathlib import Path
import os
from urllib.parse import urlsplit
from pydantic import AliasChoices, Field, field_validator, model_validator
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_prefix="GIANNA_", extra="forbid", populate_by_name=True
    )
    host: str = "127.0.0.1"
    port: int = Field(default=7860, ge=1024, le=65535)
    profile: str = "idl-tickets"
    data_dir: Path = Path(os.getenv("LOCALAPPDATA", Path.home() / ".local/share")) / "Gianna"
    tickets_api: str = "http://localhost:5000"
    tickets_web: str = "http://localhost:5173"
    ollama_url: str = "http://127.0.0.1:11434"
    tev_model: str = "tev1:0.8b"
    interpreter_model: str = "qwen3:4b"
    interpreter_backend: Literal["cloud", "local"] = "cloud"
    interpreter_timeout: float = Field(default=15, gt=0, le=30)
    tev_timeout: float = Field(default=5, gt=0, le=15)
    activation_threshold: float = Field(default=0.45, ge=0, le=1)
    catalog_threshold: float = Field(default=0.70, ge=0, le=1)
    cloud_model: str = Field(
        default="deepseek-v4.1-flash:cloud",
        validation_alias=AliasChoices("OLLAMA_MODEL", "GIANNA_CLOUD_MODEL"),
    )
    cloud_url: str = "https://ollama.com"
    cloud_timeout: float = Field(default=45, gt=0, le=45)
    cloud_api_key: str = Field(
        default="",
        repr=False,
        validation_alias=AliasChoices("OLLAMA_API_KEY", "GIANNA_CLOUD_API_KEY"),
    )
    stt_device: str = "cuda"
    stt_compute_type: str = "int8_float16"
    piper_port: int = Field(default=5001, ge=1024, le=65535)
    transport_sample_rate: int = 24000
    idle_seconds: float = Field(default=120, gt=0, le=300)
    confirmation_seconds: float = Field(default=120, gt=0, le=300)
    stt_grace_seconds: float = Field(default=15, gt=0, le=60)
    max_turn_seconds: float = Field(default=90, gt=0, le=90)
    max_events: int = Field(default=256, ge=8, le=1024)
    max_tool_calls: int = Field(default=12, ge=1, le=12)
    raw_audio: bool = False
    diagnostics: bool = False
    model_dir: Path | None = None
    nltk_dir: Path | None = None
    dev_origin: str = ""
    vad_confidence: float = 0.60
    vad_start_seconds: float = 0.2
    vad_stop_seconds: float = 0.8
    vad_min_volume: float = 0.10
    turn_settle_seconds: float = Field(default=0.4, ge=0, le=3)
    turn_stop_seconds: float = Field(default=2.0, ge=0.5, le=5)

    @model_validator(mode="after")
    def supported_engines(self):
        if (self.stt_device, self.stt_compute_type) not in {
            ("cuda", "int8_float16"),
            ("cpu", "int8"),
        }:
            raise ValueError("Usá CUDA/int8_float16 o explícitamente CPU/int8; nunca hay fallback")
        if (
            self.cloud_url != "https://ollama.com"
            or self.cloud_model.removesuffix(":cloud") != "deepseek-v4.1-flash"
            or self.tev_model != "tev1:0.8b"
        ):
            raise ValueError("Los modelos y el origen cloud de esta etapa son fijos")
        if self.transport_sample_rate not in {16000, 24000, 48000} or self.port == self.piper_port:
            raise ValueError("Frecuencia o puertos incompatibles")
        if not (
            0 < self.vad_confidence <= 1
            and 0 < self.vad_start_seconds <= 1
            and 0 < self.vad_stop_seconds <= 2
            and 0 <= self.vad_min_volume <= 1
        ):
            raise ValueError("Parámetros VAD fuera de rango")
        return self

    @field_validator("host")
    @classmethod
    def loopback(cls, v):
        if v not in {"127.0.0.1", "::1"}:
            raise ValueError("Gianna sólo admite loopback")
        return v

    @field_validator("tickets_api", "tickets_web", "ollama_url", "dev_origin")
    @classmethod
    def origin(cls, v):
        if not v:
            return v
        u = urlsplit(v)
        if (
            u.scheme not in {"http", "https"}
            or not u.hostname
            or u.username
            or u.password
            or u.query
            or u.fragment
            or u.path not in {"", "/"}
        ):
            raise ValueError("Se requiere un origen HTTP(S) exacto, sin credenciales ni ruta")
        return v.rstrip("/")

    @property
    def models_dir(self):
        return self.model_dir or self.data_dir / "models"

    @property
    def console_origin(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def conversation_model(self):
        return self.cloud_model if self.interpreter_backend == "cloud" else self.interpreter_model


def settings():
    return Settings()
