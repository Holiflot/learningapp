import asyncio
from collections import OrderedDict
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, settings as default_settings
from .stt import STTError, Transcriber, build_transcriber
from .topics import TOPICS, TOPICS_BY_ID
from .tutor import CORRECTION_MODES, EXPLAIN_LANGS, LEVELS, LLMError, OllamaClient, Session, Tutor

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
MAX_SESSIONS = 50
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # ~13 minutes of 16 kHz mono WAV


class NewSession(BaseModel):
    topic_id: str | None = None
    custom_topic: str | None = Field(default=None, max_length=300)
    level: str = "B1"
    correction_mode: str = "important"
    explain_lang: str = "tr"


class LearnerMessage(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def create_app(
    settings: Settings = default_settings,
    transcriber: Transcriber | None = None,
    tutor: Tutor | None = None,
) -> FastAPI:
    app = FastAPI(title="Speaking Tutor")
    transcriber = transcriber or build_transcriber(settings)
    tutor = tutor or Tutor(OllamaClient(settings))
    sessions: OrderedDict[str, tuple[Session, asyncio.Lock]] = OrderedDict()

    def get_session(session_id: str) -> tuple[Session, asyncio.Lock]:
        try:
            return sessions[session_id]
        except KeyError:
            raise HTTPException(404, "Session not found. Start a new lesson.") from None

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/config")
    async def config():
        return {
            "topics": [{"id": t.id, "title": t.title, "title_tr": t.title_tr} for t in TOPICS],
            "levels": list(LEVELS),
            "correction_modes": list(CORRECTION_MODES),
            "explain_langs": list(EXPLAIN_LANGS),
            "model": settings.ollama_model,
            "stt_backend": settings.stt_backend,
        }

    @app.get("/api/health")
    async def health():
        result = {"llm": {"ok": False, "detail": ""}, "stt": {"ok": False, "detail": ""}}
        async with httpx.AsyncClient(timeout=3) as client:
            try:
                resp = await client.get(f"{settings.ollama_url}/api/tags")
                names = {m.get("name") for m in resp.json().get("models", [])}
                model = settings.ollama_model
                if model in names or f"{model}:latest" in names:
                    result["llm"] = {"ok": True, "detail": model}
                else:
                    result["llm"]["detail"] = f"Ollama is running but '{model}' is not pulled: ollama pull {model}"
            except (httpx.HTTPError, ValueError):
                result["llm"]["detail"] = f"Ollama is not reachable at {settings.ollama_url}"
            if settings.stt_backend == "whispercpp":
                try:
                    await client.get(settings.whisper_server_url)
                    result["stt"] = {"ok": True, "detail": "whisper.cpp server"}
                except httpx.HTTPError:
                    result["stt"]["detail"] = f"whisper-server is not reachable at {settings.whisper_server_url}"
            else:
                result["stt"] = {"ok": True, "detail": f"faster-whisper ({settings.faster_whisper_model}, CPU)"}
        return result

    @app.post("/api/sessions")
    async def new_session(req: NewSession):
        if req.level not in LEVELS or req.correction_mode not in CORRECTION_MODES or req.explain_lang not in EXPLAIN_LANGS:
            raise HTTPException(422, "Invalid lesson settings")
        custom = (req.custom_topic or "").strip()
        if custom:
            title, scenario = custom, f"Have a conversation about: {custom}"
        elif req.topic_id in TOPICS_BY_ID:
            topic = TOPICS_BY_ID[req.topic_id]
            title, scenario = topic.title, topic.scenario
        else:
            raise HTTPException(422, "Choose a topic or write your own")

        session = Session(title, scenario, req.level, req.correction_mode, req.explain_lang)
        try:
            turn = await tutor.start(session)
        except LLMError as exc:
            raise HTTPException(502, str(exc)) from exc
        sessions[session.id] = (session, asyncio.Lock())
        while len(sessions) > MAX_SESSIONS:
            sessions.popitem(last=False)
        return {"session_id": session.id, "topic": title, "turn": turn}

    @app.post("/api/transcribe")
    async def transcribe(audio: UploadFile = File(...)):
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Recording is too long")
        if not data:
            raise HTTPException(422, "Empty recording")
        try:
            text = await transcriber.transcribe(data)
        except STTError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"text": text}

    @app.post("/api/sessions/{session_id}/messages")
    async def send_message(session_id: str, msg: LearnerMessage):
        session, lock = get_session(session_id)
        text = msg.text.strip()
        if not text:
            raise HTTPException(422, "Empty message")
        async with lock:
            try:
                return await tutor.reply(session, text)
            except LLMError as exc:
                raise HTTPException(502, str(exc)) from exc

    @app.post("/api/sessions/{session_id}/summary")
    async def summary(session_id: str):
        session, lock = get_session(session_id)
        async with lock:
            try:
                return await tutor.summary(session)
            except LLMError as exc:
                raise HTTPException(502, str(exc)) from exc

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def run():
    import os

    import uvicorn

    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )


if __name__ == "__main__":
    run()
