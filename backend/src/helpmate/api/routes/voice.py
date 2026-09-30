"""Voice endpoints (Workstream C).

Audio arrives as a raw request body (Content-Type: audio/webm, audio/mp4, ...), not multipart.
Multipart uploads get spooled to a temp file past 1 MB; a raw body stays in memory, is handed to
the STT port and then dropped. Nothing is written to disk.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from helpmate.adapters.speech_http import SpeechInputError, SpeechServiceUnavailable
from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import SpeakIn
from helpmate.domain.models import Transcript

router = APIRouter(prefix="/voice", tags=["voice"], dependencies=[Depends(current_user)])

MAX_AUDIO_BYTES = 5 * 1024 * 1024  # ~20 min of opus; push-to-talk clips are tens of KB
AUDIO_TYPES = ("audio/webm", "audio/mp4", "audio/ogg", "audio/wav", "audio/mpeg")

_audio_body = {
    "required": True,
    "content": {t: {"schema": {"type": "string", "format": "binary"}} for t in AUDIO_TYPES},
}


@router.post("/transcribe", response_model=Transcript, openapi_extra={"requestBody": _audio_body})
async def transcribe(
    request: Request, container: ContainerDep, language: str | None = None
) -> Transcript:
    mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime not in AUDIO_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"expected one of {AUDIO_TYPES}"
        )
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_AUDIO_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "audio too large")

    audio = bytearray()
    async for chunk in request.stream():
        audio += chunk
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "audio too large")
    if not audio:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "empty audio")

    full_mime = request.headers["content-type"]
    try:
        return await container.stt.transcribe(bytes(audio), full_mime, language)
    except SpeechServiceUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except SpeechInputError as exc:  # e.g. a recording too short to decode
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    finally:
        audio.clear()


@router.post(
    "/speak",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def speak(body: SpeakIn, container: ContainerDep) -> Response:
    try:
        wav = await container.tts.speak(body.text, body.voice)
    except SpeechServiceUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})
