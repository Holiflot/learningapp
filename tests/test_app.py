import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.stt import clean_transcript
from app.tutor import START_INSTRUCTION, Tutor, parse_turn


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def chat(self, messages, schema):
        self.calls.append(messages)
        last = messages[-1]["content"]
        if "Review this speaking practice session" in last:
            return json.dumps({
                "overall_feedback": "Good job.",
                "strengths": ["Fluent"],
                "common_mistakes": ["Third person -s"],
                "next_steps": ["Practice present simple"],
            })
        if last == START_INSTRUCTION:
            return json.dumps({"reply": "Hi! How was your day?", "corrections": [], "better_version": "",
                               "vocabulary": [{"word": "hectic", "meaning": "very busy", "example": "A hectic day."}]})
        return json.dumps({
            "reply": "Nice! What does he do?",
            "corrections": [
                {"original": "he go", "corrected": "he goes", "explanation": "third person -s"},
                {"original": "to work", "corrected": "to work", "explanation": "no-op"},
            ],
            "better_version": "My brother goes to work every day.",
            "vocabulary": [],
        })


class FakeSTT:
    async def transcribe(self, wav_bytes):
        return "my brother he go to work every day"


@pytest.fixture
def client_and_llm():
    llm = FakeLLM()
    app = create_app(transcriber=FakeSTT(), tutor=Tutor(llm))
    return TestClient(app), llm


def test_full_lesson_flow(client_and_llm):
    client, llm = client_and_llm
    res = client.post("/api/sessions", json={"topic_id": "small-talk", "level": "B1"})
    assert res.status_code == 200, res.text
    sid = res.json()["session_id"]
    assert res.json()["turn"]["reply"] == "Hi! How was your day?"

    text = client.post("/api/transcribe", files={"audio": ("a.wav", b"RIFF....", "audio/wav")}).json()["text"]
    turn = client.post(f"/api/sessions/{sid}/messages", json={"text": text}).json()
    assert turn["reply"] == "Nice! What does he do?"
    # the no-op "correction" is dropped
    assert turn["corrections"] == [{"original": "he go", "corrected": "he goes", "explanation": "third person -s"}]

    # history keeps system prompt + opening + learner turn
    second_call = llm.calls[1]
    assert second_call[0]["role"] == "system"
    assert "Small talk" in second_call[0]["content"]
    assert second_call[-1] == {"role": "user", "content": text}

    summary = client.post(f"/api/sessions/{sid}/summary").json()
    assert summary["common_mistakes"] == ["Third person -s"]
    assert summary["vocabulary"][0]["word"] == "hectic"


def test_custom_topic_and_validation(client_and_llm):
    client, _ = client_and_llm
    assert client.post("/api/sessions", json={}).status_code == 422
    assert client.post("/api/sessions", json={"topic_id": "travel", "level": "Z9"}).status_code == 422
    res = client.post("/api/sessions", json={"custom_topic": "football", "explain_lang": "en"})
    assert res.json()["topic"] == "football"


def test_unknown_session_and_empty_summary(client_and_llm):
    client, _ = client_and_llm
    assert client.post("/api/sessions/nope/messages", json={"text": "hi"}).status_code == 404
    sid = client.post("/api/sessions", json={"topic_id": "travel"}).json()["session_id"]
    assert client.post(f"/api/sessions/{sid}/summary").status_code == 502


def test_parse_turn_falls_back_to_plain_text():
    turn = parse_turn("Sorry, plain text")
    assert turn["reply"] == "Sorry, plain text"
    assert turn["corrections"] == []


def test_clean_transcript():
    assert clean_transcript(" [BLANK_AUDIO] ") == ""
    assert clean_transcript("Thank you.") == ""
    assert clean_transcript("I  go (coughs) to school") == "I go to school"
