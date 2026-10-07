"""Grok (xAI): model wiring, structured call, error mapping, corrective retry."""
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.ai import grok
from app.ai.claude_code import LLMUsageLimit
from app.ai.grok import GrokJSON, GrokTranslator
from app.ai.llm_service import LLMAuthError, LLMNotConfigured, LLMRateLimit
from app.ai.novel_translator import MODELS, SCHEMA, LLMRefused, make_translator

GOOD = {"heading": "1920. Trăng Đen", "paragraphs": ["Kim Soo-hyun mỉm cười.", "Dòng hai."], "new_terms": []}


def reply(content, finish="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)], model="grok-x",
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=500, prompt_tokens_details=SimpleNamespace(cached_tokens=200)))


def api_error(cls, status, msg):
    req = httpx.Request("POST", "https://api.x.ai/v1/chat/completions")
    return cls(msg, response=httpx.Response(status, request=req, json={"error": msg}), body=None)


def fake_client(monkeypatch, outcomes, seen=None):
    queue = list(outcomes)

    def create(**kw):
        if seen is not None:
            seen.append(kw)
        out = queue.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("TRANSLATE_PROVIDER", "anthropic")
    monkeypatch.setattr(openai.OpenAI, "__init__", lambda self, **kw: None)
    monkeypatch.setattr(openai.OpenAI, "chat", SimpleNamespace(completions=SimpleNamespace(create=create)), raising=False)


def make(monkeypatch, outcomes, seen=None, model="grok:best"):
    fake_client(monkeypatch, outcomes, seen)
    return make_translator(model, "medium")


def translate(t, paras=("a", "b")):
    return t.translate(heading="1920. 다크 문", paragraphs=list(paras), glossary_text="", prev_tail=[], style="s")


def test_models_registered_and_factory(monkeypatch):
    assert MODELS["grok:best"]["provider"] == "xai" and MODELS["grok:fast"]["tier"] == "fast"
    assert isinstance(make(monkeypatch, []), GrokTranslator)
    monkeypatch.delenv("XAI_API_KEY")
    with pytest.raises(LLMNotConfigured):
        make_translator("grok:best", "medium")


def test_slug_from_env(monkeypatch):
    monkeypatch.delenv("XAI_MODEL", raising=False)
    assert grok.slug_for("best") == grok.MODEL_DEFAULTS["best"]
    monkeypatch.setenv("XAI_MODEL_FAST", "grok-fast-x")
    assert grok.slug_for("fast") == "grok-fast-x"


def test_translate_success(monkeypatch):
    import json
    seen = []
    t = make(monkeypatch, [reply(json.dumps(GOOD))], seen)
    r = translate(t)
    assert r.paragraphs == GOOD["paragraphs"] and r.model.startswith("grok:")
    assert r.usage == {"input_tokens": 800, "output_tokens": 500, "cache_read_input_tokens": 200}
    assert seen[0]["response_format"]["type"] == "json_schema" and seen[0]["model"] == grok.slug_for("best")


def test_corrective_retry_on_paragraph_count(monkeypatch):
    import json
    bad = dict(GOOD, paragraphs=["gộp lại"])
    seen = []
    t = make(monkeypatch, [reply(json.dumps(bad)), reply(json.dumps(GOOD))], seen)
    assert translate(t).paragraphs == GOOD["paragraphs"]
    assert "<fix>" in seen[1]["messages"][1]["content"]


def test_json_object_fallback(monkeypatch):
    import json
    seen = []
    t = make(monkeypatch, [api_error(openai.BadRequestError, 400, "unsupported response_format json_schema"),
                           reply("```json\n" + json.dumps(GOOD) + "\n```")], seen)
    assert translate(t).heading == GOOD["heading"]
    assert seen[1]["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("exc,expected", [
    (api_error(openai.AuthenticationError, 401, "bad key"), LLMAuthError),
    (api_error(openai.RateLimitError, 429, "slow down"), LLMRateLimit),
    (api_error(openai.RateLimitError, 429, "Your team has run out of credits"), LLMUsageLimit),
    (api_error(openai.PermissionDeniedError, 403, "content policy violation"), LLMRefused),
])
def test_error_mapping(monkeypatch, exc, expected):
    t = make(monkeypatch, [exc])
    with pytest.raises(expected):
        translate(t)


def test_content_filter_is_refusal(monkeypatch):
    t = make(monkeypatch, [reply("", finish="content_filter")])
    with pytest.raises(LLMRefused):
        translate(t)


def test_status_without_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    st = grok.status(probe=True)
    assert st["has_key"] is False and st["models"] == []


def test_paragraphs_returned_as_one_string_are_split_not_counted_as_characters(monkeypatch):
    """A gateway fallback model may answer `paragraphs` as one long string: 116 paragraphs must not look like 9990."""
    nl = chr(10)
    as_string = dict(GOOD, paragraphs=nl.join(f"Đoạn số {i} khá dài để đếm ký tự." for i in range(40)))
    seen = []
    t = make(monkeypatch, [reply(json.dumps(as_string))], seen)
    r = translate(t, paras=[f"p{i}" for i in range(40)])
    assert len(r.paragraphs) == 40 and len(seen) == 1                 # no corrective retry
    one_element = dict(GOOD, paragraphs=[nl.join(f"Đoạn {i}." for i in range(5))])
    t = make(monkeypatch, [reply(json.dumps(one_element))], [])
    assert len(translate(t, paras=[f"p{i}" for i in range(5)]).paragraphs) == 5


def test_as_paragraphs_recovers_character_per_item_lists():
    from app.ai.grok import _as_paragraphs
    text = chr(10).join(f"Đoạn thứ {i} của chương." for i in range(30))
    assert _as_paragraphs(list(text)) == text.split(chr(10))                 # the old bug: a string iterated per character
    assert _as_paragraphs(["a", "b"]) == ["a", "b"] and _as_paragraphs(None) == [] and _as_paragraphs(5) == []


def test_loose_json_array_with_unescaped_dialogue_quotes():
    """What Claude sent through the gateway: a string holding an array that is not valid JSON."""
    from app.ai.grok import _as_paragraphs
    bad = '["「Một」", "Hắn nói xong rồi thôi.", ""Thưa Hạ đẳng." Cô cúi chào.", "Dòng 4.\nDòng 4b.", "2 / 2"]'
    got = _as_paragraphs(bad)
    assert got == ["「Một」", "Hắn nói xong rồi thôi.", '"Thưa Hạ đẳng." Cô cúi chào.', "Dòng 4.\nDòng 4b.", "2 / 2"]
    good = '["a", "b", "c"]'
    assert _as_paragraphs(good) == ["a", "b", "c"] and _as_paragraphs([good]) == ["a", "b", "c"]


def test_count_tolerance_avoids_a_pointless_retry(monkeypatch):
    seen = []
    n = 60
    short = dict(GOOD, paragraphs=[f"Đoạn {i}." for i in range(n - 2)])        # two merged paragraphs
    t = make(monkeypatch, [reply(json.dumps(short)), reply(json.dumps(short))], seen)
    t.count_tolerance = 0.05
    assert len(translate(t, paras=[f"p{i}" for i in range(n)]).paragraphs) == n - 2 and len(seen) == 1
    t2 = make(monkeypatch, [reply(json.dumps(short)), reply(json.dumps(dict(GOOD, paragraphs=[f"Đoạn {i}." for i in range(n)])))], [])
    assert len(translate(t2, paras=[f"p{i}" for i in range(n)]).paragraphs) == n          # strict by default: retried
