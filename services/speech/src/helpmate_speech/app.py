"""Speech service HTTP API. Called only by the core (helpmate.adapters.speech_http) over loopback.

Models are CPU-bound and blocking, so each request runs in a worker thread. Audio arrives as a
raw body, stays in memory and is dropped after transcription; nothing is logged but durations.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from helpmate_speech import __version__
from helpmate_speech.engines import AudioDecodeError, Engine, TranscriptOut, load_engine
from helpmate_speech.settings import SpeechSettings

log = logging.getLogger("helpmate.speech")

MAX_AUDIO_BYTES = 5 * 1024 * 1024


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    voice: str | None = None


class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    engine: str
    stt_model: str
    tts_model: str


def create_app(settings: SpeechSettings | None = None) -> FastAPI:
    settings = settings or SpeechSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = await run_in_threadpool(load_engine, settings)  # model loading can take seconds
        app.state.engine = engine
        log.info(
            "speech engine %s up (stt=%s, tts=%s)", engine.name, engine.stt_model, engine.tts_model
        )
        yield

    app = FastAPI(title="HelpMate speech service", version=__version__, lifespan=lifespan)

    def engine_of(request: Request) -> Engine:
        return request.app.state.engine

    @app.get("/health", response_model=HealthOut)
    async def health(request: Request) -> HealthOut:
        e = engine_of(request)
        return HealthOut(
            version=__version__, engine=e.name, stt_model=e.stt_model, tts_model=e.tts_model
        )

    @app.post("/transcribe", response_model=TranscriptOut)
    async def transcribe(request: Request, language: str | None = None) -> TranscriptOut:
        mime = request.headers.get("content-type", "application/octet-stream")
        audio = bytearray()
        async for chunk in request.stream():
            audio += chunk
            if len(audio) > MAX_AUDIO_BYTES:
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "audio too large")
        if not audio:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "empty audio")
        try:
            result = await run_in_threadpool(
                engine_of(request).transcribe,
                bytes(audio),
                mime,
                language or settings.whisper_language,
            )
        except AudioDecodeError as exc:
            log.info("undecodable upload: %d bytes of %s", len(audio), mime)  # sizes only
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Couldn't read the recording. It was probably too short: hold the button while you "
                "talk.",
            ) from exc
        finally:
            audio.clear()
        log.info("transcribed %d ms of audio in %d ms", result.duration_ms, result.stt_ms)
        return result

    @app.post("/speak", response_class=Response)
    async def speak(body: SpeakIn, request: Request) -> Response:
        wav = await run_in_threadpool(
            engine_of(request).speak, body.text, body.voice or settings.kokoro_voice
        )
        return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    return app


def run() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = SpeechSettings()
    uvicorn.run(
        "helpmate_speech.app:create_app", factory=True, host=settings.host, port=settings.port
    )
