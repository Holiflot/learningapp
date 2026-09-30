"""The English-teacher conversation logic on top of Ollama."""
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings

LEVELS = {
    "A2": "elementary (CEFR A2): use very simple words and short sentences, speak slowly and clearly",
    "B1": "intermediate (CEFR B1): use everyday vocabulary and clear sentences, introduce a few useful phrases",
    "B2": "upper-intermediate (CEFR B2): speak naturally, use common idioms and phrasal verbs",
    "C1": "advanced (CEFR C1): speak like a native speaker, use rich vocabulary and nuanced expressions",
}

CORRECTION_MODES = {
    "all": "List every grammar, word-choice and naturalness mistake in the learner's last message.",
    "important": (
        "List only mistakes that change the meaning or are basic grammar errors (tense, "
        "articles, subject-verb agreement, word order). At most 3. Skip tiny style issues."
    ),
    "none": (
        "Do not list corrections (return an empty list). Instead, naturally reuse the correct "
        "form of what the learner said inside your reply."
    ),
}

EXPLAIN_LANGS = {
    "en": "Write the explanations and meanings in simple English.",
    "tr": "Write the explanations and meanings in Turkish. Everything else stays in English.",
}

MAX_HISTORY_MESSAGES = 24

START_INSTRUCTION = (
    "(Start the lesson now: greet me in one short sentence, set the scene for today's topic, "
    "and ask me the first question.)"
)

TURN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "original": {"type": "string"},
                    "corrected": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["original", "corrected", "explanation"],
            },
        },
        "better_version": {"type": "string"},
        "vocabulary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "meaning": {"type": "string"},
                    "example": {"type": "string"},
                },
                "required": ["word", "meaning", "example"],
            },
        },
    },
    "required": ["reply", "corrections", "better_version", "vocabulary"],
}

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overall_feedback": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "common_mistakes": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["overall_feedback", "strengths", "common_mistakes", "next_steps"],
}


class LLMError(RuntimeError):
    pass


@dataclass
class Session:
    topic_title: str
    scenario: str
    level: str
    correction_mode: str
    explain_lang: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    history: list[dict[str, str]] = field(default_factory=list)
    learner_messages: list[str] = field(default_factory=list)
    corrections: list[dict[str, str]] = field(default_factory=list)
    vocabulary: list[dict[str, str]] = field(default_factory=list)


def system_prompt(s: Session) -> str:
    return f"""You are a friendly, patient English teacher having a spoken conversation with a Turkish learner.

TOPIC: {s.topic_title}
SCENARIO: {s.scenario}
LEARNER LEVEL: {LEVELS[s.level]}.

How to talk:
- Keep "reply" short: 1-4 sentences, like real spoken conversation. Do not lecture.
- Stay on the topic and scenario; if it is a role-play, stay in character.
- Always end "reply" with a question or a prompt that makes the learner speak again.
- If the learner asks what a word means or how to say something, help briefly, then continue.
- Never put corrections inside "reply"; they go in "corrections".

About the learner's messages:
- They are automatic speech-to-text transcripts. Ignore punctuation, capitalization and
  filler words (um, uh). If a word looks like a speech-recognition error rather than a real
  mistake, do not correct it.

Corrections ("corrections" field): {CORRECTION_MODES[s.correction_mode]}
- "original" is the exact wrong part the learner said, "corrected" is the fixed version,
  "explanation" is one short sentence explaining the rule.
- If there are no mistakes, return an empty list. Never invent mistakes.
"better_version": the learner's whole last message rewritten the way a native speaker would say it
  at the learner's level. Use an empty string if it was already natural or if there is no learner message yet.
"vocabulary": 0-2 useful words or phrases from YOUR reply or related to the topic that suit the learner's level.
{EXPLAIN_LANGS[s.explain_lang]}"""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9' ]+", "", text.lower()).strip()


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_turn(content: str) -> dict[str, Any]:
    """Parse and sanitise the model's JSON answer. Falls back to plain text."""
    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        return {"reply": content.strip(), "corrections": [], "better_version": "", "vocabulary": []}

    corrections = []
    for c in data.get("corrections") or []:
        if not isinstance(c, dict):
            continue
        original, corrected = _str(c.get("original")), _str(c.get("corrected"))
        # Models sometimes "correct" something into the same text.
        if not original or not corrected or _norm(original) == _norm(corrected):
            continue
        corrections.append({"original": original, "corrected": corrected,
                            "explanation": _str(c.get("explanation"))})

    vocabulary = []
    for v in data.get("vocabulary") or []:
        if isinstance(v, dict) and _str(v.get("word")):
            vocabulary.append({"word": _str(v.get("word")), "meaning": _str(v.get("meaning")),
                               "example": _str(v.get("example"))})

    return {
        "reply": _str(data.get("reply")),
        "corrections": corrections,
        "better_version": _str(data.get("better_version")),
        "vocabulary": vocabulary,
    }


class OllamaClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def chat(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
        s = self.settings
        body: dict[str, Any] = {
            "model": s.ollama_model,
            "messages": messages,
            "stream": False,
            "format": schema,
            "keep_alive": s.ollama_keep_alive,
            "options": {"temperature": s.llm_temperature, "num_ctx": 8192},
        }
        if s.ollama_think is not None:
            body["think"] = s.ollama_think
        try:
            async with httpx.AsyncClient(timeout=s.llm_timeout) as client:
                resp = await client.post(f"{s.ollama_url}/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama unreachable at {s.ollama_url}: {exc}") from exc
        if resp.status_code != 200:
            try:
                detail = resp.json().get("error", resp.text)
            except ValueError:
                detail = resp.text
            raise LLMError(f"Ollama error ({resp.status_code}): {detail}")
        return resp.json().get("message", {}).get("content", "")


class Tutor:
    def __init__(self, llm: OllamaClient):
        self.llm = llm

    def _messages(self, session: Session) -> list[dict[str, str]]:
        return [{"role": "system", "content": system_prompt(session)}] + session.history[-MAX_HISTORY_MESSAGES:]

    async def _respond(self, session: Session, user_content: str) -> dict[str, Any]:
        messages = self._messages(session) + [{"role": "user", "content": user_content}]
        turn = parse_turn(await self.llm.chat(messages, TURN_SCHEMA))
        if not turn["reply"]:
            raise LLMError("The model returned an empty reply")
        # Only commit to history once the model has answered successfully.
        session.history.append({"role": "user", "content": user_content})
        session.history.append({"role": "assistant", "content": turn["reply"]})
        return turn

    async def start(self, session: Session) -> dict[str, Any]:
        turn = await self._respond(session, START_INSTRUCTION)
        turn["corrections"], turn["better_version"] = [], ""
        session.vocabulary.extend(turn["vocabulary"])
        return turn

    async def reply(self, session: Session, learner_text: str) -> dict[str, Any]:
        turn = await self._respond(session, learner_text)
        session.learner_messages.append(learner_text)
        session.corrections.extend(turn["corrections"])
        session.vocabulary.extend(turn["vocabulary"])
        return turn

    async def summary(self, session: Session) -> dict[str, Any]:
        if not session.learner_messages:
            raise LLMError("Nothing to summarise yet: say something first")
        said = "\n".join(f"- {m}" for m in session.learner_messages)
        mistakes = "\n".join(
            f"- {c['original']} -> {c['corrected']} ({c['explanation']})" for c in session.corrections
        ) or "- (none recorded)"
        prompt = f"""You are an English teacher. Review this speaking practice session.
Topic: {session.topic_title}. Learner level: {session.level}.

What the learner said (speech transcripts, ignore punctuation):
{said}

Mistakes noted during the session:
{mistakes}

Give encouraging but honest feedback: a short overall comment, 1-3 strengths, the recurring
mistake patterns (group similar ones, max 5), and 2-4 concrete next steps.
{EXPLAIN_LANGS[session.explain_lang]}"""
        content = await self.llm.chat([{"role": "user", "content": prompt}], SUMMARY_SCHEMA)
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise LLMError("The model returned an invalid summary") from exc
        return {
            "overall_feedback": _str(data.get("overall_feedback")),
            "strengths": [_str(x) for x in data.get("strengths") or [] if _str(x)],
            "common_mistakes": [_str(x) for x in data.get("common_mistakes") or [] if _str(x)],
            "next_steps": [_str(x) for x in data.get("next_steps") or [] if _str(x)],
            "vocabulary": _dedupe_vocab(session.vocabulary),
        }


def _dedupe_vocab(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen, out = set(), []
    for v in items:
        key = v["word"].lower()
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out
