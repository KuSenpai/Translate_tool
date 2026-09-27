"""AI correction: provider abstraction, error mapping, and the suggest endpoint (mock provider)."""
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app import config
from app.ai import llm_service
from app.ai.correction_service import suggest_correction
from app.ai.llm_service import (AnthropicProvider, LLMAuthError, LLMEmptyResponse, LLMNotConfigured, LLMRateLimit,
                                LLMRequest, LLMTimeout, get_provider, parse_json_text)


def _upload(client, book):
    with open(book, "rb") as f:
        return client.post("/api/projects/upload", files={"file": ("ai-book.docx", f)}).json()["project"]["id"]


def test_suggest_endpoint_with_mock(client, book):
    pid = _upload(client, book)
    client.put(f"/api/projects/{pid}/glossary", json=[{"source": "Kim Su-hyeon", "target": "Kim Soo-hyun"}])
    client.post(f"/api/projects/{pid}/chapters/12/load", json={})
    before = client.get(f"/api/projects/{pid}/chapters/12").json()["draft"]
    r = client.post(f"/api/projects/{pid}/chapters/12/suggest",
                    json={"selected": "Kim Su-hyeon  nói với cô .", "context_before": [], "context_after": []})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["original"] == "Kim Su-hyeon  nói với cô ."
    assert s["suggestion"] == "Kim Soo-hyun nói với cô."
    assert s["changed"] and s["reason"] and s["provider"] == "mock"
    # Suggest never overwrites the draft.
    assert client.get(f"/api/projects/{pid}/chapters/12").json()["draft"] == before


def test_ai_status(client):
    assert client.get("/api/ai/status").json() == {"enabled": True, "provider": "mock", "model": "mock"}


def test_not_configured(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider, reason = get_provider()
    assert provider is None and "ANTHROPIC_API_KEY" in reason
    with pytest.raises(LLMNotConfigured):
        suggest_correction(chapter={"number": 1, "ko_blocks": []}, glossary=[], selected="x",
                           context_before=[], context_after=[])


def test_parse_json_text():
    assert parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_text('Here: {"a": 2} done') == {"a": 2}
    for bad in ("", "no json here"):
        with pytest.raises(LLMEmptyResponse):
            parse_json_text(bad)


_REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, code):
    return cls("err", response=httpx.Response(code, request=_REQ), body=None)


@pytest.mark.parametrize("exc,expected", [
    (anthropic.APITimeoutError(request=_REQ), LLMTimeout),
    (_status_error(anthropic.AuthenticationError, 401), LLMAuthError),
    (_status_error(anthropic.RateLimitError, 429), LLMRateLimit),
])
def test_anthropic_error_mapping(monkeypatch, exc, expected):
    p = AnthropicProvider("claude-opus-5", "test-key")

    def boom(**kwargs):
        raise exc
    monkeypatch.setattr(p.client.beta.messages, "create", boom)
    with pytest.raises(expected):
        p.complete_json(LLMRequest(system="s", cached_context="c", prompt="p", schema={}))


def test_anthropic_request_shape_and_empty(monkeypatch):
    p = AnthropicProvider("claude-opus-5", "test-key")
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="")],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    monkeypatch.setattr(p.client.beta.messages, "create", fake)
    with pytest.raises(LLMEmptyResponse):
        p.complete_json(LLMRequest(system="s", cached_context="c", prompt="p", schema={"type": "object"}))
    assert seen["model"] == "claude-opus-5" and seen["fallbacks"] == "default"
    assert seen["output_config"]["format"]["type"] == "json_schema"
    assert seen["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
