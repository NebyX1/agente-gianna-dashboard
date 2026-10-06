"""Piper HTTP process compatible with PiperHttpTTSService. Native 22050 Hz, real resampling."""

import io
import asyncio
import wave
from math import gcd
import numpy as np
from scipy.signal import resample_poly
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from gianna.runtime.cancellation import NativeWorker


class SynthesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=6000)
    voice: str | None = "es_AR-daniela-high"
    sample_rate: int = Field(default=24000, ge=8000, le=48000)
    speed: float = Field(default=1, ge=0.65, le=1.4)


class PiperResident:
    def __init__(self, config):
        self.config = config
        self.worker = NativeWorker("piper")
        self.voice = None
        self.cache = {}

    def load(self):
        from piper import PiperVoice

        self.voice = PiperVoice.load(
            str(self.config.models_dir / "piper/es_AR-daniela-high.onnx"), use_cuda=False
        )
        if self.voice.config.sample_rate != 22050:
            raise RuntimeError("Wrong Piper native sample rate")
        self.synthesize(SynthesisRequest(text="Gianna está lista."))

    def synthesize(self, req):
        from piper.config import SynthesisConfig

        if req.voice not in {None, "es_AR-daniela-high"}:
            raise ValueError("Only es_AR-daniela-high is installed")
        public = {
            "Gianna está lista.",
            "Por supuesto, decime qué necesitás registrar.",
            "¿De qué oficina, área o municipio viene el pedido?",
            "¿Qué equipo debe recibir el pedido?",
            "¿Qué tipo de problema es?",
            "Cuando necesites algo, llamame.",
            "Hola, soy Gianna y ya estoy activada.",
        }
        key = (req.text, req.sample_rate, req.speed)
        if key in self.cache:
            return self.cache[key]
        chunks = list(self.voice.synthesize(req.text, SynthesisConfig(length_scale=1 / req.speed)))
        a = np.concatenate([c.audio_float_array for c in chunks])
        d = gcd(22050, req.sample_rate)
        if req.sample_rate != 22050:
            a = resample_poly(a, req.sample_rate // d, 22050 // d)
        pcm = np.clip(a * 32767, -32768, 32767).astype(np.int16).tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(req.sample_rate)
            w.writeframes(pcm)
        result = buf.getvalue()
        if req.text in public:
            if len(self.cache) >= 64:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = result
        return result


def piper_app(config):
    from contextlib import asynccontextmanager

    resident = PiperResident(config)
    reservation = asyncio.Lock()
    waiting = [0]

    @asynccontextmanager
    async def lifespan(app):
        await resident.worker.run(resident.load)
        yield
        await resident.worker.close()

    app = FastAPI(lifespan=lifespan)

    @app.post("/")
    async def synthesize(req: SynthesisRequest):
        if waiting[0] >= 4:
            raise HTTPException(429, "Cola de Piper llena")
        waiting[0] += 1
        try:
            async with asyncio.timeout(30):
                async with reservation:
                    if resident.worker.inflight and not resident.worker.inflight.done():
                        await asyncio.shield(resident.worker.inflight)
                    audio = await resident.worker.run(resident.synthesize, req)
            return Response(audio, media_type="audio/wav")
        except TimeoutError:
            raise HTTPException(504, "Piper excedió el plazo")
        except RuntimeError:
            raise HTTPException(429, "Piper ocupado")
        finally:
            waiting[0] -= 1

    @app.get("/health")
    async def health():
        return {
            "voice": "es_AR-daniela-high",
            "native_sample_rate": 22050,
            "runtime": "1.4.2",
            "ready": resident.voice is not None,
        }

    return app
