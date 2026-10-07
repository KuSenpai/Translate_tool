"""OmniRoute (local OpenAI-compatible gateway): configuration, format fallbacks, error mapping."""
import json
from types import SimpleNamespace

import openai
import pytest

from app.ai import omniroute
from app.ai.claude_code import LLMUsageLimit
from app.ai.llm_service import LLMAuthError, LLMError, LLMNotConfigured, LLMRateLimit
from app.ai.novel_translator import MODELS, LLMRefused, make_translator
from app.ai.omniroute import OmniRouteTranslator
from tests.test_grok import GOOD, api_error, reply


def fake(monkeypatch, outcomes, seen=None, key="om-test", model="kr-combo"):
    queue = list(outcomes)

    def create(**kw):
        if seen is not None:
            seen.append(kw)
        out = queue.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    for k, v in (("OMNIROUTE_API_KEY", key), ("OMNIROUTE_MODEL", model)):
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
    monkeypatch.setenv("TRANSLATE_PROVIDER", "anthropic")
    monkeypatch.setattr(openai.OpenAI, "__init__", lambda self, **kw: setattr(self, "_kw", kw))
    monkeypatch.setattr(openai.OpenAI, "chat", SimpleNamespace(completions=SimpleNamespace(create=create)), raising=False)


def translate(t, paras=("a", "b")):
    return t.translate(heading="1920. 다크 문", paragraphs=list(paras), glossary_text="", prev_tail=[], style="s")


def test_registered_and_factory(monkeypatch):
    assert MODELS["omniroute:default"]["provider"] == "omniroute"
    fake(monkeypatch, [])
    t = make_translator("omniroute:default", "medium")
    assert isinstance(t, OmniRouteTranslator) and t.slug == "kr-combo"
    assert t.client._kw["base_url"] == "http://localhost:20128/v1" and t.client._kw["api_key"] == "om-test"


def test_base_url_is_normalised(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:9999/")
    assert omniroute.base_url() == "http://127.0.0.1:9999/v1"
    monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:9999/v1")
    assert omniroute.base_url() == "http://127.0.0.1:9999/v1"


def test_missing_key_or_model(monkeypatch):
    fake(monkeypatch, [], key="")
    with pytest.raises(LLMNotConfigured, match="OMNIROUTE_API_KEY"):
        make_translator("omniroute:default", "medium")
    fake(monkeypatch, [], model="")
    with pytest.raises(LLMNotConfigured, match="OMNIROUTE_MODEL"):
        make_translator("omniroute:default", "medium")


def test_translate_success_labels_model(monkeypatch):
    seen = []
    fake(monkeypatch, [reply(json.dumps(GOOD))], seen)
    r = translate(make_translator("omniroute:default", "medium"))
    assert r.paragraphs == GOOD["paragraphs"] and r.model.startswith("omniroute:")
    assert seen[0]["model"] == "kr-combo" and seen[0]["response_format"]["type"] == "json_schema"


def test_degrades_json_schema_then_json_object_then_plain_text(monkeypatch):
    seen = []
    fake(monkeypatch, [api_error(openai.BadRequestError, 400, "unknown parameter"),
                       api_error(openai.UnprocessableEntityError, 422, "bad request"),
                       reply("Đây là kết quả:\n```json\n" + json.dumps(GOOD) + "\n```")], seen)
    r = translate(make_translator("omniroute:default", "medium"))
    assert r.heading == GOOD["heading"]
    assert [k.get("response_format", {}).get("type") for k in seen] == ["json_schema", "json_object", None]
    assert "single JSON object" in seen[2]["messages"][0]["content"]


@pytest.mark.parametrize("exc,expected", [
    (api_error(openai.AuthenticationError, 401, "bad key"), LLMAuthError),
    (api_error(openai.RateLimitError, 429, "slow down"), LLMRateLimit),
    (api_error(openai.RateLimitError, 429, "all accounts quota exhausted"), LLMUsageLimit),
    (api_error(openai.PermissionDeniedError, 403, "blocked by content policy"), LLMRefused),
    (api_error(openai.NotFoundError, 404, "model not found"), LLMError),
])
def test_error_mapping(monkeypatch, exc, expected):
    fake(monkeypatch, [exc])
    with pytest.raises(expected) as e:
        translate(make_translator("omniroute:default", "medium"))
    if isinstance(exc, openai.NotFoundError):
        assert e.value.code == "AI_BAD_MODEL" and "OMNIROUTE_MODEL" in e.value.message


def test_status(monkeypatch):
    fake(monkeypatch, [])
    monkeypatch.setattr(openai.OpenAI, "models", SimpleNamespace(list=lambda: [SimpleNamespace(id="a"), SimpleNamespace(id="kr-combo")]), raising=False)
    omniroute._cache = (0.0, {})
    st = omniroute.status(probe=True, force=True)
    assert st["has_key"] and st["models"] == ["a", "kr-combo"] and st["error"] is None
    monkeypatch.setenv("OMNIROUTE_MODEL", "nope")
    omniroute._cache = (0.0, {})
    assert "nope" in omniroute.status(probe=True, force=True)["error"]
    monkeypatch.setenv("OMNIROUTE_API_KEY", "")
    assert omniroute.status(probe=True, force=True)["has_key"] is False


def test_info_endpoint(client):
    assert "omniroute" in client.get("/api/translate/info").json()
    assert client.get("/api/translate/omniroute").status_code == 200
