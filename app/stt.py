"""Speech-to-text backends.

The browser sends 16 kHz mono WAV, so no ffmpeg is needed on either path.

Whisper tends to "clean up" a learner's grammar while transcribing. To keep
mistakes visible to the tutor we decode greedily (temperature 0), never give it
a prompt, and never condition on earlier text.
"""
import asyncio
import io
import re
from typing import Protocol

import httpx

from .config import Settings

# Phrases Whisper is known to invent on silence or noise.
_PHANTOM_PHRASES = {
    "thank you",
    "thanks for watching",
    "thank you for watching",
    "you",
    "bye",
    "subtitles by the amara.org community",
}


class STTError(RuntimeError):
    pass


class Transcriber(Protocol):
    async def transcribe(self, wav_bytes: bytes) -> str: ...


def clean_transcript(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)  # [BLANK_AUDIO], (music) ...
    text = re.sub(r"\s+", " ", text).strip()
    if text.lower().strip(" .!?") in _PHANTOM_PHRASES:
        return ""
    return text


class WhisperCppTranscriber:
    """Client for whisper.cpp's `whisper-server` (Vulkan build runs on AMD GPUs)."""

    def __init__(self, base_url: str, timeout: float = 60.0):
        self.base_url = base_url
        self.timeout = timeout

    async def transcribe(self, wav_bytes: bytes) -> str:
        data = {
            "temperature": "0.0",
            "temperature_inc": "0.0",
            "response_format": "json",
            "language": "en",
        }
        files = {"file": ("speech.wav", wav_bytes, "audio/wav")}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/inference", data=data, files=files)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise STTError(f"whisper-server unreachable at {self.base_url}: {exc}") from exc
        payload = resp.json()
        if "error" in payload:
            raise STTError(f"whisper-server error: {payload['error']}")
        return clean_transcript(payload.get("text", ""))


class FasterWhisperTranscriber:
    """Runs Whisper on the CPU in-process. Slower, but needs no extra server."""

    def __init__(self, model_name: str, compute_type: str):
        self.model_name = model_name
        self.compute_type = compute_type
        self._model = None
        self._lock = asyncio.Lock()

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise STTError(
                    "faster-whisper is not installed: pip install -r requirements-cpu-stt.txt"
                ) from exc
            self._model = WhisperModel(self.model_name, device="cpu", compute_type=self.compute_type)
        return self._model

    def _run(self, wav_bytes: bytes) -> str:
        model = self._load()
        segments, _ = model.transcribe(
            io.BytesIO(wav_bytes),
            language="en",
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=True,
        )
        return clean_transcript(" ".join(s.text for s in segments))

    async def transcribe(self, wav_bytes: bytes) -> str:
        async with self._lock:  # one CPU transcription at a time
            return await asyncio.to_thread(self._run, wav_bytes)


def build_transcriber(settings: Settings) -> Transcriber:
    if settings.stt_backend == "faster-whisper":
        return FasterWhisperTranscriber(settings.faster_whisper_model, settings.faster_whisper_compute_type)
    if settings.stt_backend == "whispercpp":
        return WhisperCppTranscriber(settings.whisper_server_url)
    raise ValueError(f"Unknown STT_BACKEND: {settings.stt_backend!r}")
