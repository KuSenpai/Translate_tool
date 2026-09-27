"""Translation correction suggestions. Never modifies the draft — the UI decides to Apply."""
from __future__ import annotations

from ..document.models import Block
from ..editor.glossary import glossary_prompt
from ..logging_setup import get_logger
from .llm_service import LLMEmptyResponse, LLMNotConfigured, LLMRequest, get_provider

log = get_logger("AI")

SYSTEM_PROMPT = """You are an experienced Korean→Vietnamese literary translation editor. The user is revising the Vietnamese translation of a Korean web novel chapter. You receive the story glossary, the Korean original of the chapter, and one selected passage of the Vietnamese translation with its surrounding context.

Return a corrected version of ONLY the selected passage:
- Compare with the Korean original and fix mistranslations, typos, spelling, grammar, unnatural phrasing, punctuation, pronouns and forms of address (xưng hô), and character names.
- Follow the glossary strictly: names, titles and address terms use the preferred rendering; never use variants marked "KHÔNG dùng".
- Keep the meaning, tone and style. Do not add, drop or summarize content, and do not translate or include the surrounding context.
- Keep the passage's line-break structure: use "\\n" only where the selection has line breaks.
- If the passage is already good, return it unchanged with changed=false.
- Write `reason` in Vietnamese: a short list of each change and why (e.g. "‘cô’ → ‘chị’: nhân vật lớn tuổi hơn, glossary 누나 → chị")."""

SCHEMA = {
    "type": "object",
    "properties": {
        "suggestion": {"type": "string", "description": "Corrected Vietnamese text replacing the selected passage"},
        "reason": {"type": "string", "description": "Vietnamese explanation of the changes"},
        "changed": {"type": "boolean"},
    },
    "required": ["suggestion", "reason", "changed"],
    "additionalProperties": False,
}


def ai_status() -> dict:
    provider, reason = get_provider()
    if provider is None:
        return {"enabled": False, "reason": reason}
    return {"enabled": True, "provider": provider.name, "model": provider.model}


def suggest_correction(*, chapter: dict, glossary: list[dict], selected: str, context_before: list[str],
                       context_after: list[str], instruction: str = "") -> dict:
    provider, reason = get_provider()
    if provider is None:
        raise LLMNotConfigured(f"AI chưa được cấu hình: {reason}")
    ko_text = "\n\n".join(Block.model_validate(b).text for b in chapter.get("ko_blocks", []))
    cached = (f"<glossary>\n{glossary_prompt(glossary) or '(trống)'}\n</glossary>\n\n"
              f"<korean_chapter number=\"{chapter['number']}\">\n{ko_text or '(không có bản Hàn)'}\n</korean_chapter>")
    prompt = ("<context_before>\n" + "\n\n".join(context_before) + "\n</context_before>\n\n"
              f"<selected>\n{selected}\n</selected>\n\n"
              "<context_after>\n" + "\n\n".join(context_after) + "\n</context_after>")
    if instruction:
        prompt += f"\n\n<user_instruction>\n{instruction}\n</user_instruction>"
    log.info("Correction requested: chapter=%s provider=%s chars=%d", chapter["number"], provider.name, len(selected))
    result = provider.complete_json(LLMRequest(
        system=SYSTEM_PROMPT, cached_context=cached, prompt=prompt, schema=SCHEMA,
        data={"selected": selected, "glossary": glossary},
    ))
    suggestion = result.get("suggestion")
    if not isinstance(suggestion, str) or not suggestion.strip():
        raise LLMEmptyResponse("AI không trả về gợi ý. Hãy thử lại.")
    return {
        "original": selected,
        "suggestion": suggestion,
        "reason": str(result.get("reason") or "").strip() or "(không có giải thích)",
        "changed": suggestion.strip() != selected.strip(),
        "provider": provider.name,
        "model": provider.model,
    }
