"""Story glossary / termbase: source term → preferred Vietnamese rendering (+ variants to avoid)."""
from __future__ import annotations

import re
import uuid
from typing import Optional

from pydantic import BaseModel, Field, field_validator

CATEGORIES = {
    "character": "nhân vật", "place": "địa danh", "skill": "chiêu thức/kỹ năng", "item": "vật phẩm",
    "organization": "tổ chức/môn phái", "title": "danh hiệu/chức vị", "term": "thuật ngữ", "pronoun": "xưng hô",
    "other": "khác",
}
_HANGUL = re.compile(r"[가-힣]")


class GlossaryEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    source: str                               # e.g. 김수현, 형, 선배 (or a wrong Vietnamese variant)
    target: str                               # e.g. Kim Soo-hyun, anh, tiền bối
    note: str = ""                            # e.g. "gọi khi em trai nói với anh"
    avoid: list[str] = Field(default_factory=list)   # variants that must not appear in the translation
    category: Optional[str] = None            # see CATEGORIES
    origin: Optional[str] = None              # manual | data | ai-scan | translation

    @field_validator("source", "target")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("không được để trống")
        return v

    @field_validator("avoid")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return [x.strip() for x in v if x.strip()]


def glossary_prompt(entries: list[dict]) -> str:
    """Compact text form handed to the LLM."""
    lines = []
    for e in entries:
        line = f"- {e['source']} → {e['target']}"
        if e.get("category") in CATEGORIES:
            line += f" [{CATEGORIES[e['category']]}]"
        if e.get("avoid"):
            line += f" (KHÔNG dùng: {', '.join(e['avoid'])})"
        if e.get("note"):
            line += f" — {e['note']}"
        lines.append(line)
    return "\n".join(lines)


def entries_for_text(entries: list[dict], korean_text: str) -> list[dict]:
    """Only the entries that matter for this text: Korean sources that occur in it, plus
    non-Korean entries (pronoun rules, wrong renderings to avoid) which apply everywhere."""
    return [e for e in entries if (e["source"] in korean_text) or not _HANGUL.search(e["source"])]
