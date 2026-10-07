"""Translate through OmniRoute — a local AI gateway (https://github.com/diegosouzapw/OmniRoute) that exposes
one OpenAI-compatible endpoint in front of many providers / accounts / combos, with its own routing and fallbacks.

Fill in `.env`:
    OMNIROUTE_API_KEY=...          key created in the OmniRoute dashboard
    OMNIROUTE_MODEL=...            a model id or combo name exactly as OmniRoute lists it (GET /v1/models)
    OMNIROUTE_BASE_URL=            optional, default http://localhost:20128/v1

The gateway may sit in front of models that do not support strict JSON schemas, so the call degrades:
json_schema → json_object → plain text (the schema is then spelled out in the prompt and the reply is parsed).
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional

from ..logging_setup import get_logger
from .claude_code import LLMUsageLimit
from .grok import GrokJSON, GrokTranslator
from .llm_service import LLMAuthError, LLMError, LLMNotConfigured, LLMRateLimit, LLMTimeout

log = get_logger("OMNIROUTE")

DEFAULT_URL = "http://localhost:20128/v1"
_QUOTA = re.compile(r"quota|credit|insufficient|usage limit|exhausted|billing|all (?:providers|accounts)", re.IGNORECASE)
_SAFETY = re.compile(r"content[ _-]?(?:policy|filter|moderation)|safety|blocked|prohibited|refus", re.IGNORECASE)


def base_url() -> str:
    url = os.getenv("OMNIROUTE_BASE_URL", "").strip().rstrip("/") or DEFAULT_URL
    return url if url.endswith("/v1") else url + "/v1"


def api_key() -> str:
    return os.getenv("OMNIROUTE_API_KEY", "").strip()


def model_slug() -> str:
    return os.getenv("OMNIROUTE_MODEL", "").strip()


_cache: tuple[float, dict] = (0.0, {})


def status(probe: bool = False, force: bool = False) -> dict:
    """{"has_key", "model", "base_url", "models", "checked", "error"}. Only `probe=True` calls the gateway (GET /v1/models)."""
    global _cache
    st = {"has_key": bool(api_key()), "model": model_slug(), "base_url": base_url(), "models": [], "checked": False, "error": None}
    if not probe or not st["has_key"]:
        return st
    if _cache[1] and not force and time.time() - _cache[0] < 120 and _cache[1].get("base_url") == st["base_url"]:
        return _cache[1]
    st["checked"] = True
    try:
        import openai
        client = openai.OpenAI(api_key=api_key(), base_url=st["base_url"], timeout=15, max_retries=0)
        st["models"] = sorted(m.id for m in client.models.list())
        if not st["model"]:
            st["error"] = "Chưa đặt OMNIROUTE_MODEL trong .env — chọn một model / combo trong danh sách bên dưới."
        elif st["models"] and st["model"] not in st["models"]:
            st["error"] = f"OmniRoute không có model / combo “{st['model']}”. Kiểm tra OMNIROUTE_MODEL theo danh sách bên dưới."
    except Exception as e:  # noqa: BLE001 — show any failure instead of crashing the screen
        name = type(e).__name__
        st["error"] = ("API key OmniRoute không hợp lệ (OMNIROUTE_API_KEY)." if "Auth" in name or "Permission" in name
                       else f"Không kết nối được OmniRoute ở {st['base_url']} — OmniRoute có đang chạy không? ({str(e)[:100]})")
    _cache = (time.time(), st)
    return st


class OmniRouteJSON(GrokJSON):
    """Same interface as novel_translator.ClaudeJSON.call(), through OmniRoute's OpenAI-compatible endpoint."""
    label = "OmniRoute"

    def __init__(self, model: str, effort: str = "medium"):
        if not api_key():
            raise LLMNotConfigured("Thiếu OMNIROUTE_API_KEY trong file .env — tạo API key trong dashboard OmniRoute "
                                   f"({base_url().removesuffix('/v1')}) rồi dán vào .env.")
        if not model_slug():
            raise LLMNotConfigured("Thiếu OMNIROUTE_MODEL trong file .env — đặt đúng tên model / combo như OmniRoute liệt kê "
                                   "(dashboard hoặc GET /v1/models).")
        import openai
        self._sdk = openai
        self.tier = "default"
        self.slug = model_slug()
        # the gateway already retries and falls back between its targets: a client retry would only double the wait
        self.client = openai.OpenAI(api_key=api_key(), base_url=base_url(), timeout=900, max_retries=0)

    def _formats(self, schema: dict) -> list:
        return [{"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}},
                {"type": "json_object"}, None]

    def _can_fallback(self, e: Exception) -> bool:        # a gateway reports unsupported options in many different ways
        return True

    def _map(self, e: Exception, refusal_message: str) -> LLMError:
        return _map_error(e, refusal_message)


def _map_error(e: Exception, refusal_message: str) -> LLMError:
    name = type(e).__name__
    msg = str(getattr(e, "message", "") or e)[:300]
    status: Optional[int] = getattr(e, "status_code", None)
    if name == "APITimeoutError":
        return LLMTimeout("OmniRoute không phản hồi kịp (timeout).")
    if name == "APIConnectionError":
        return LLMError(f"Không kết nối được OmniRoute ở {base_url()} — OmniRoute có đang chạy không?", code="AI_NETWORK")
    if status == 401 or name == "AuthenticationError":
        return LLMAuthError("API key OmniRoute không hợp lệ (OMNIROUTE_API_KEY trong .env).")
    if status in (402, 429) and _QUOTA.search(msg):
        return LLMUsageLimit(f"OmniRoute báo hết hạn mức / credit của các nhà cung cấp: {msg}")
    if status == 429 or name == "RateLimitError":
        return LLMRateLimit(f"OmniRoute bị giới hạn tốc độ — sẽ thử lại sau. {msg[:120]}")
    if status == 403 or name == "PermissionDeniedError":
        if _SAFETY.search(msg):
            from .novel_translator import LLMRefused
            return LLMRefused(f"{refusal_message} (bộ lọc của nhà cung cấp): {msg[:120]}")
        return LLMAuthError(f"API key OmniRoute không có quyền dùng model này: {msg}")
    if status == 404 or name == "NotFoundError":
        return LLMError(f"OmniRoute không có model / combo “{model_slug()}”: {msg}. Kiểm tra OMNIROUTE_MODEL trong .env.", code="AI_BAD_MODEL")
    if status and status >= 500:
        return LLMError(f"OmniRoute lỗi {status}: {msg}", code="AI_SERVER")
    if _SAFETY.search(msg):
        from .novel_translator import LLMRefused
        return LLMRefused(f"{refusal_message} (bộ lọc của nhà cung cấp): {msg[:120]}")
    return LLMError(f"OmniRoute lỗi {status or ''}: {msg}")


class OmniRouteTranslator(OmniRouteJSON):
    translate = GrokTranslator.translate       # same chapter flow (one corrective retry on a bad paragraph count)
