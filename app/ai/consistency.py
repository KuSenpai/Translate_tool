"""Evidence from earlier chapters for the translator: how the same characters addressed each other (xưng hô) and how
recurring terms were rendered. Rules in a glossary can't capture "A gọi B là anh, B gọi A là em"; real aligned
examples (Korean line → the Vietnamese line already published) can, and the model copies them.

Picks dialogue lines of the previous chapters that share a character name / glossary term / Korean address word
with the chapter being translated. Needs the Korean and Vietnamese paragraphs to line up 1:1 (chapters that don't are skipped).
"""
from __future__ import annotations

# Korean address / kinship / title words; names come from the glossary (term_sources).
ADDRESS = ("형", "오빠", "누나", "언니", "동생", "선배", "후배", "아저씨", "아줌마", "아가씨", "도련님", "주인님", "마스터",
           "님", "씨", "당신", "그대", "자네", "아버지", "어머니", "아빠", "엄마", "할아버지", "할머니", "삼촌", "이모", "폐하", "전하")
_QUOTES = "“\"「『"


def example_pairs(previous: list[dict], korean: str, term_sources: list[str], limit: int = 14, max_chars: int = 220) -> list[tuple]:
    """[(chapter, ko, vi)] in chapter order. `previous`: [{number, ko_paragraphs, vi_paragraphs}] newest first."""
    keys = {t for t in term_sources if t in korean} | {a for a in ADDRESS if a in korean}
    scored = []
    for c in previous:
        if len(c["ko_paragraphs"]) != len(c["vi_paragraphs"]):
            continue
        for ko, vi in zip(c["ko_paragraphs"], c["vi_paragraphs"]):
            if len(ko) <= max_chars and any(q in ko for q in _QUOTES) and (score := sum(k in ko for k in keys)):
                scored.append((score, c["number"], ko, vi))
    scored.sort(key=lambda x: (-x[0], -x[1]))            # ponytail: plain overlap score, no embeddings; upgrade if it picks poor lines
    return sorted(((n, ko, vi) for _, n, ko, vi in scored[:limit]), key=lambda x: x[0])


def with_examples(notes: str, previous: list[dict], korean: str, term_sources: list[str]) -> tuple[str, int]:
    """`notes` plus the examples block (the translator's notes slot goes into the prompt as <story_notes>)."""
    pairs = example_pairs(previous, korean, term_sources)
    if not pairs:
        return notes, 0
    block = ("CÁCH ĐÃ DỊCH Ở CÁC CHƯƠNG TRƯỚC (Hàn → Việt). Giữ NGUYÊN cách xưng hô giữa các nhân vật và cách dịch thuật ngữ "
             "như các ví dụ này; chỉ đổi khi cốt truyện thật sự đổi quan hệ:\n"
             + "\n".join(f"[Ch {n}] {ko} → {vi}" for n, ko, vi in pairs))
    return (notes.strip() + "\n\n" if notes.strip() else "") + block, len(pairs)
