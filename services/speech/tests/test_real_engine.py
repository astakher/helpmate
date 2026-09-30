"""SPEECH_ENGINE=real. The round trip needs the `real` extra and the downloaded models, so it is
skipped in CI (which installs neither) and runs on a dev machine after ./scripts/get_models.ps1."""

from __future__ import annotations

import importlib.util
import io
import time
import wave

import pytest

from helpmate_speech.engines import load_engine
from helpmate_speech.settings import SpeechSettings

settings = SpeechSettings(_env_file=None, engine="real", whisper_model="base", cpu_threads=4)
have_real = (
    importlib.util.find_spec("faster_whisper") is not None
    and settings.kokoro_model.exists()
    and settings.kokoro_voices.exists()
)


def test_missing_models_explain_how_to_get_them(tmp_path):
    missing = SpeechSettings(
        _env_file=None,
        engine="real",
        kokoro_model=tmp_path / "kokoro-v1.0.onnx",
        kokoro_voices=tmp_path / "voices-v1.0.bin",
    )
    with pytest.raises(FileNotFoundError, match="get_models.ps1"):
        load_engine(missing)


def test_missing_whisper_model_explains_how_to_get_it():
    """Whisper loads with local_files_only, so a model that isn't downloaded is a clear error,
    never a silent download (the privacy check requires no run-time network access)."""
    if not have_real:
        pytest.skip("real speech models not installed (./scripts/get_models.ps1)")
    not_downloaded = "tiny"  # get_models.ps1 fetches only the configured model (base)
    with pytest.raises(FileNotFoundError, match="get_models.ps1"):
        load_engine(SpeechSettings(_env_file=None, engine="real", whisper_model=not_downloaded))


@pytest.fixture(scope="module")
def engine():
    if not have_real:
        pytest.skip("real speech models not installed (./scripts/get_models.ps1)")
    return load_engine(settings)


def test_a_bare_webm_header_is_an_audio_decode_error(engine):
    from helpmate_speech.engines import AudioDecodeError

    with pytest.raises(AudioDecodeError):
        engine.transcribe(b"\x1aE\xdf\xa3\x9fB\x86\x81\x01", "audio/webm;codecs=opus", "en")


def test_round_trip_kokoro_then_whisper(engine):
    started = time.perf_counter()
    wav = engine.speak("Remind me to buy milk tomorrow at nine.", "af_heart")
    tts_ms = (time.perf_counter() - started) * 1000
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getnchannels(), w.getsampwidth()) == (1, 2)
        seconds = w.getnframes() / w.getframerate()
    assert 1.0 < seconds < 6.0

    result = engine.transcribe(wav, "audio/wav", None)  # auto-detect the language
    text = result.text.lower()
    assert "milk" in text and "remind" in text, text
    assert result.language == "en"
    print(f"\nTTS {tts_ms:.0f} ms for {seconds:.1f} s of audio; STT {result.stt_ms} ms: {text!r}")
