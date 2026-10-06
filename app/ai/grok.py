"""Translate with Grok (xAI) through its OpenAI-compatible API.

Needs XAI_API_KEY in `.env` (console.x.ai). Billed per token on the xAI account. Grok is far less strict
than other models with explicit (18+) fiction, which is why it is offered next to Claude / Gemini.

Model slugs come from XAI_MODEL (the "best" tier) and XAI_MODEL_FAST (the cheap tier); the defaults are
the ones in MODEL_DEFAULTS and can be changed without touching the code. `status(probe=True)` lists the
models the key can actually use (GET /v1/models) so a wrong slug is reported before a long job starts.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

from ..logging_setup import get_logger
from .claude_code import LLMUsageLimit
from .llm_service import LLMAuthError, LLMEmptyResponse, LLMError, LLMNotConfigured, LLMRateLimit, LLMTimeout

log = get_logger("GROK")

BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1").strip()
MODEL_DEFAULTS = {"best": "grok-4.7", "fast": "grok-4.3"}
_ENV = {"best": "XAI_MODEL", "fast": "XAI_MODEL_FAST"}
_CREDITS = re.compile(r"credit|spending limit|insufficient (?:funds|balance)|billing|quota|exceeded your", re.IGNORECASE)
_SAFETY = re.compile(r"content[ _-]?(?:policy|filter|moderation)|safety|violat", re.IGNORECASE)
_HANGUL = re.compile(r"[가-힣]")


def api_key() -> str:
    return os.getenv("XAI_API_KEY", "").strip()


def slug_for(tier: str) -> str:
    return os.getenv(_ENV.get(tier, "XAI_MODEL"), "").strip() or MODEL_DEFAULTS.get(tier, MODEL_DEFAULTS["best"])


# --------------------------------------------------------------------------- status
_cache: tuple[float, dict] = (0.0, {})


def status(probe: bool = False, force: bool = False) -> dict:
    """{"has_key", "models", "checked", "error", "picked"}. Only `probe=True` calls the API (list models)."""
    global _cache
    st = {"has_key": bool(api_key()), "models": [], "checked": False, "error": None,
          "picked": {t: slug_for(t) for t in MODEL_DEFAULTS}}
    if not st["has_key"] or not probe:
        return st
    if _cache[1] and not force and time.time() - _cache[0] < 300:
        return _cache[1]
    st["checked"] = True
    try:
        import openai
        client = openai.OpenAI(api_key=api_key(), base_url=BASE_URL, timeout=20, max_retries=1)
        st["models"] = sorted(m.id for m in client.models.list())
        missing = [f"{t}: {s}" for t, s in st["picked"].items() if s not in st["models"]]
        if st["models"] and missing:
            st["error"] = ("Tài khoản xAI không có model " + ", ".join(missing)
                           + ". Đặt XAI_MODEL / XAI_MODEL_FAST trong .env theo danh sách bên dưới.")
    except Exception as e:  # noqa: BLE001 — show any failure (bad key, network) instead of crashing the screen
        name = type(e).__name__
        st["error"] = ("API key xAI không hợp lệ (XAI_API_KEY)." if "Auth" in name or "Permission" in name
                       else f"Không kiểm tra được xAI: {str(e)[:160]}")
    _cache = (time.time(), st)
    return st


# --------------------------------------------------------------------------- the call
class GrokJSON:
    """Same interface as novel_translator.ClaudeJSON.call(), backed by the xAI chat completions API."""

    def __init__(self, model: str, effort: str = "medium"):
        from .novel_translator import MODELS
        key = api_key()
        if not key:
            raise LLMNotConfigured("Thiếu XAI_API_KEY trong file .env — cần API key xAI (console.x.ai) để dùng Grok.")
        import openai
        self._sdk = openai
        self.tier = MODELS.get(model, {}).get("tier", "best")
        self.slug = slug_for(self.tier)
        self.client = openai.OpenAI(api_key=key, base_url=BASE_URL, timeout=900, max_retries=3)

    def call(self, *, system: str, user: str, schema: dict, max_tokens: int = 64000,
             refusal_message: str = "Grok từ chối xử lý nội dung này") -> tuple[dict, dict, str]:
        o = self._sdk
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        formats = [{"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}},
                   {"type": "json_object"}]   # fallback for a model that rejects json_schema
        resp = None
        for k, fmt in enumerate(formats):
            try:
                resp = self.client.chat.completions.create(model=self.slug, messages=messages, response_format=fmt)
                break
            except o.BadRequestError as e:
                if k + 1 < len(formats) and re.search(r"response_format|json_schema|schema|structured", str(e), re.I):
                    log.info("json_schema rejected by %s, retrying with json_object", self.slug)
                    messages[0] = {"role": "system", "content": system + "\nRespond with a single JSON object only, matching: "
                                   + json.dumps(schema)}
                    continue
                raise _map_error(e, refusal_message)
            except o.OpenAIError as e:
                raise _map_error(e, refusal_message)
        u = getattr(resp, "usage", None)
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        usage = {"input_tokens": max((getattr(u, "prompt_tokens", 0) or 0) - cached, 0),
                 "output_tokens": getattr(u, "completion_tokens", 0) or 0, "cache_read_input_tokens": cached}
        if not resp.choices:
            raise LLMEmptyResponse("Grok trả về phản hồi rỗng.", details={"usage": usage})
        choice = resp.choices[0]
        text = (choice.message.content or "").strip()
        if choice.finish_reason == "content_filter":
            from .novel_translator import LLMRefused
            raise LLMRefused(f"{refusal_message} (bộ lọc nội dung của xAI).", details={"usage": usage})
        if choice.finish_reason == "length":
            raise LLMEmptyResponse("Kết quả bị cắt (quá dài cho một lần gọi).", details={"usage": usage})
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.S)
            try:
                data = json.loads(m.group(0)) if m else None
            except json.JSONDecodeError:
                data = None
        if not isinstance(data, dict):
            raise LLMEmptyResponse("Grok trả về dữ liệu không đúng định dạng JSON.", details={"usage": usage})
        log.info("grok ok: model=%s in=%s out=%s cached=%s", self.slug, usage["input_tokens"], usage["output_tokens"], cached)
        return data, usage, getattr(resp, "model", None) or self.slug


def _map_error(e: Exception, refusal_message: str) -> LLMError:
    name = type(e).__name__
    msg = str(getattr(e, "message", "") or e)[:300]
    if name == "APITimeoutError":
        return LLMTimeout("Grok không phản hồi kịp (timeout).")
    if name == "APIConnectionError":
        return LLMError("Không kết nối được tới xAI API (mạng?).", code="AI_NETWORK")
    status = getattr(e, "status_code", None)
    if status == 401 or name == "AuthenticationError":
        return LLMAuthError("API key xAI không hợp lệ (XAI_API_KEY trong .env).")
    if _CREDITS.search(msg) and status in (402, 403, 429):
        return LLMUsageLimit(f"Tài khoản xAI hết credit / chạm hạn mức chi tiêu: {msg}")
    if status == 403 or name == "PermissionDeniedError":
        if _SAFETY.search(msg):
            from .novel_translator import LLMRefused
            return LLMRefused(f"{refusal_message} (bộ lọc xAI): {msg[:120]}")
        return LLMAuthError(f"API key xAI không có quyền dùng model này: {msg}")
    if status == 404 or name == "NotFoundError":
        return LLMError(f"Model Grok không khả dụng với API key này: {msg}. Đặt XAI_MODEL / XAI_MODEL_FAST trong .env.",
                        code="AI_BAD_MODEL")
    if status == 429 or name == "RateLimitError":
        return LLMRateLimit("Bị giới hạn tốc độ (rate limit) từ xAI — sẽ thử lại sau.")
    if status and status >= 500:
        return LLMError(f"xAI API lỗi {status}: {msg}", code="AI_SERVER")
    return LLMError(f"xAI API lỗi {status or ''}: {msg}")


# --------------------------------------------------------------------------- chapter translation
def _problems(data: dict, n: int) -> str:
    paras = data.get("paragraphs") or []
    issues = []
    if len(paras) != n:
        issues.append(f"Bạn trả về {len(paras)} đoạn nhưng đầu vào có {n} đoạn. Phải đúng {n} phần tử, mỗi đoạn gốc một phần tử, "
                      "không gộp/tách/bỏ đoạn.")
    joined = " ".join(str(p) for p in paras)
    if joined and len(_HANGUL.findall(joined)) > max(3, len(joined) * 0.005):
        issues.append("Bản dịch còn sót chữ Hàn (Hangul). Dịch hoặc phiên âm hết, không để lại ký tự Hangul.")
    return " ".join(issues)


class GrokTranslator(GrokJSON):
    def translate(self, *, heading: str, paragraphs: list[str], glossary_text: str, prev_tail: list[str],
                  style: str, notes: str = ""):
        from .novel_translator import SCHEMA, SYSTEM_PROMPT, ChapterResult, build_user_message
        system = SYSTEM_PROMPT.format(style=style)
        base = build_user_message(heading, paragraphs, glossary_text, prev_tail, notes)
        total: dict = {}
        best: Optional[tuple] = None
        fix = ""
        for _ in range(2):   # Grok sometimes merges paragraphs or leaves Hangul: one corrective retry
            data, usage, model = self.call(system=system, user=base + (f"\n\n<fix>\n{fix}\n</fix>" if fix else ""),
                                           schema=SCHEMA, refusal_message="Grok từ chối dịch chương này")
            for k, v in usage.items():
                total[k] = total.get(k, 0) + v
            if not data.get("paragraphs"):
                fix = "Lần trước bạn trả về bản dịch rỗng. Hãy dịch đầy đủ chương."
                continue
            fix = _problems(data, len(paragraphs))
            off = abs(len(data["paragraphs"]) - len(paragraphs))
            if best is None or not fix or off < best[2]:
                best = (data, model, off)
            if not fix:
                break
            log.info("grok retry (%s)", fix[:80])
        if best is None:
            raise LLMEmptyResponse("Grok trả về bản dịch rỗng.", details={"usage": total})
        data, model, _ = best
        return ChapterResult(heading=str(data.get("heading") or "").strip(), paragraphs=[str(p) for p in data["paragraphs"]],
                             new_terms=[t for t in data.get("new_terms", []) if isinstance(t, dict) and t.get("source") and t.get("target")],
                             usage=total, model=f"grok:{model}")
