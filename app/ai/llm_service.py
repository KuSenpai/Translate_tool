"""Provider-agnostic LLM interface.

    TranslationEditor → CorrectionService → LLMProvider → Anthropic | OpenAI | Local (OpenAI-compatible) | Mock

Select with LLM_PROVIDER in `.env`. API keys are read from the environment only and are
never logged or returned to the UI.
"""
from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from .. import config
from ..errors import AppError
from ..logging_setup import get_logger

log = get_logger("AI")


# --------------------------------------------------------------------------- errors
class LLMError(AppError):
    status = 502
    code = "AI_ERROR"


class LLMNotConfigured(LLMError):
    status = 503
    code = "AI_NOT_CONFIGURED"


class LLMTimeout(LLMError):
    status = 504
    code = "AI_TIMEOUT"


class LLMAuthError(LLMError):
    code = "AI_INVALID_KEY"


class LLMRateLimit(LLMError):
    status = 429
    code = "AI_RATE_LIMIT"


class LLMEmptyResponse(LLMError):
    code = "AI_EMPTY_RESPONSE"


# --------------------------------------------------------------------------- interface
@dataclass
class LLMRequest:
    system: str
    cached_context: str          # large, stable per chapter (glossary + Korean source) — cacheable prefix
    prompt: str                  # small, changes per request
    schema: dict
    max_tokens: int = 16000
    data: dict = field(default_factory=dict)   # structured inputs (used by the mock provider)


class LLMProvider(ABC):
    name: str = "base"

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def complete_json(self, req: LLMRequest) -> dict: ...


def parse_json_text(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise LLMEmptyResponse("AI trả về phản hồi rỗng. Hãy thử lại.")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise LLMEmptyResponse("AI trả về dữ liệu không đúng định dạng JSON. Hãy thử lại.")


# --------------------------------------------------------------------------- Anthropic
class AnthropicProvider(LLMProvider):
    name = "anthropic"
    DEFAULT_MODEL = "claude-opus-5"
    # Server-side refusal fallbacks are supported on these models.
    _FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}

    def __init__(self, model: str, api_key: str):
        super().__init__(model or self.DEFAULT_MODEL)
        import anthropic
        self._sdk = anthropic
        self.client = anthropic.Anthropic(api_key=api_key, timeout=config.LLM_TIMEOUT, max_retries=2)

    def complete_json(self, req: LLMRequest) -> dict:
        a = self._sdk
        output_config: dict = {"format": {"type": "json_schema", "schema": req.schema}}
        if config.LLM_EFFORT:
            output_config["effort"] = config.LLM_EFFORT
        kwargs: dict = {}
        if self.model in self._FALLBACK_MODELS:
            kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=req.max_tokens,
                system=req.system,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": req.cached_context, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": req.prompt},
                ]}],
                output_config=output_config,
                **kwargs,
            )
        except a.APITimeoutError:
            raise LLMTimeout(f"AI không phản hồi sau {config.LLM_TIMEOUT:.0f}s (timeout). Hãy thử lại.")
        except (a.AuthenticationError, a.PermissionDeniedError):
            raise LLMAuthError("API key Anthropic không hợp lệ hoặc không có quyền. Kiểm tra ANTHROPIC_API_KEY trong .env.")
        except a.RateLimitError:
            raise LLMRateLimit("Bị giới hạn tốc độ (rate limit) từ Anthropic. Đợi một lát rồi thử lại.")
        except a.NotFoundError:
            raise LLMError(f"Model '{self.model}' không tồn tại hoặc không khả dụng. Kiểm tra LLM_MODEL.", code="AI_BAD_MODEL")
        except a.APIStatusError as e:
            raise LLMError(f"Anthropic API lỗi {e.status_code}: {e.message}")
        except a.APIConnectionError:
            raise LLMError("Không kết nối được tới Anthropic API (mạng?).", code="AI_NETWORK")

        if resp.stop_reason == "refusal":
            raise LLMError("AI từ chối xử lý đoạn này.", code="AI_REFUSED")
        if resp.stop_reason == "max_tokens":
            raise LLMEmptyResponse("Phản hồi của AI bị cắt ngắn (max_tokens). Hãy chọn đoạn ngắn hơn.")
        text = "".join(b.text for b in resp.content if b.type == "text")
        usage = resp.usage
        log.info("Response model=%s in=%s out=%s cache_read=%s", self.model, usage.input_tokens,
                 usage.output_tokens, getattr(usage, "cache_read_input_tokens", None))
        return parse_json_text(text)


# --------------------------------------------------------------------------- OpenAI / local
class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str, api_key: str, base_url: Optional[str] = None, name: str = "openai"):
        super().__init__(model)
        import openai
        self._sdk = openai
        self.name = name
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=config.LLM_TIMEOUT, max_retries=2)

    def complete_json(self, req: LLMRequest) -> dict:
        o = self._sdk
        fmt = ({"type": "json_schema", "json_schema": {"name": "result", "schema": req.schema, "strict": True}}
               if self.name == "openai" else {"type": "json_object"})
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": req.system + "\nRespond with a single JSON object only."},
                          {"role": "user", "content": req.cached_context + "\n\n" + req.prompt}],
                response_format=fmt,
            )
        except o.APITimeoutError:
            raise LLMTimeout(f"AI không phản hồi sau {config.LLM_TIMEOUT:.0f}s (timeout).")
        except (o.AuthenticationError, o.PermissionDeniedError):
            raise LLMAuthError("API key không hợp lệ. Kiểm tra OPENAI_API_KEY / LOCAL_LLM_API_KEY trong .env.")
        except o.RateLimitError:
            raise LLMRateLimit("Bị giới hạn tốc độ (rate limit). Đợi một lát rồi thử lại.")
        except o.NotFoundError:
            raise LLMError(f"Model '{self.model}' không tồn tại. Kiểm tra LLM_MODEL.", code="AI_BAD_MODEL")
        except o.APIStatusError as e:
            raise LLMError(f"API lỗi {e.status_code}: {e.message}")
        except o.APIConnectionError:
            where = config.LOCAL_LLM_BASE_URL if self.name == "local" else "OpenAI API"
            raise LLMError(f"Không kết nối được tới {where}.", code="AI_NETWORK")
        if not resp.choices:
            raise LLMEmptyResponse("AI trả về phản hồi rỗng.")
        return parse_json_text(resp.choices[0].message.content or "")


# --------------------------------------------------------------------------- mock
class MockProvider(LLMProvider):
    """Offline, deterministic provider for tests/demo: fixes spacing and applies the glossary."""
    name = "mock"

    def complete_json(self, req: LLMRequest) -> dict:
        text = req.data.get("selected", "")
        reasons = []
        fixed = re.sub(r"(?<=\S)  +(?=\S)", " ", text)
        if fixed != text:
            reasons.append("bỏ khoảng trắng kép")
        t2 = re.sub(r"\s+([,.;:!?])", r"\1", fixed)
        if t2 != fixed:
            reasons.append("bỏ khoảng trắng trước dấu câu")
        fixed = t2
        for e in req.data.get("glossary", []):
            wrong = list(e.get("avoid", []))
            if not re.search(r"[가-힣]", e["source"]) and e["source"].lower() != e["target"].lower():
                wrong.append(e["source"])
            for w in wrong:
                new = re.sub(re.escape(w), e["target"], fixed, flags=re.IGNORECASE)
                if new != fixed:
                    reasons.append(f"“{w}” → “{e['target']}” theo glossary")
                    fixed = new
        return {"suggestion": fixed, "changed": fixed != text,
                "reason": ("[MOCK] " + "; ".join(reasons)) if reasons else "[MOCK] Không phát hiện lỗi (provider giả lập)."}


# --------------------------------------------------------------------------- factory
def get_provider() -> tuple[Optional[LLMProvider], str]:
    """Return (provider, reason_if_unavailable). Reads configuration on every call so `.env`
    edits apply after a restart without code changes."""
    p = config.LLM_PROVIDER
    if not p:
        return None, "Chưa cấu hình LLM_PROVIDER trong .env (anthropic | openai | local | mock)."
    if p == "mock":
        return MockProvider("mock"), ""
    if p == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not key:
            return None, "Thiếu ANTHROPIC_API_KEY trong .env."
        return AnthropicProvider(config.LLM_MODEL, key), ""
    if p == "openai":
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            return None, "Thiếu OPENAI_API_KEY trong .env."
        if not config.LLM_MODEL:
            return None, "Thiếu LLM_MODEL trong .env (tên model OpenAI)."
        return OpenAIProvider(config.LLM_MODEL, key), ""
    if p == "local":
        if not config.LLM_MODEL:
            return None, "Thiếu LLM_MODEL trong .env (tên model local, ví dụ qwen2.5:14b)."
        return OpenAIProvider(config.LLM_MODEL, os.getenv("LOCAL_LLM_API_KEY", "local"),
                              base_url=config.LOCAL_LLM_BASE_URL, name="local"), ""
    return None, f"LLM_PROVIDER '{p}' không được hỗ trợ."
