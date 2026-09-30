import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _think_setting(value: str) -> bool | None:
    value = value.strip().lower()
    if value in ("", "none", "auto"):
        return None
    return value in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "gemma4:12b")
    ollama_keep_alive: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
    ollama_think: bool | None = _think_setting(os.getenv("OLLAMA_THINK", ""))
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.7"))
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "180"))

    stt_backend: str = os.getenv("STT_BACKEND", "whispercpp").strip().lower()
    whisper_server_url: str = os.getenv("WHISPER_SERVER_URL", "http://127.0.0.1:8178").rstrip("/")
    faster_whisper_model: str = os.getenv("FASTER_WHISPER_MODEL", "large-v3-turbo")
    faster_whisper_compute_type: str = os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8")


settings = Settings()
