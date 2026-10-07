"""Translate one long chapter as several parts in parallel.

A reasoning model needs minutes for a whole chapter, and the time is almost linear in the output, so N parts at once
take roughly 1/N of the time (plus a fixed start-up cost). Each part gets the same glossary / notes / style; the parts
after the first also see the Korean paragraphs right before them, so names and who-is-speaking stay clear.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from ..logging_setup import get_logger
from .novel_translator import ChapterResult

log = get_logger("CHUNKED")
MIN_PARAGRAPHS = 30       # shorter chapters are not worth splitting
STAGGER = 1.5             # seconds between starting the parts: providers cap requests per second (xAI: 2/s per team)
CONTEXT = 4               # Korean paragraphs of context before each later part


def split_parts(paragraphs: list[str], parts: int) -> list[tuple[int, int]]:
    """Contiguous [start, end) ranges with roughly equal character counts."""
    parts = max(1, min(parts, len(paragraphs) // 12 or 1))
    total = sum(len(p) for p in paragraphs) or 1
    bounds, acc, start = [], 0, 0
    for i, p in enumerate(paragraphs):
        acc += len(p)
        if len(bounds) < parts - 1 and acc >= total * (len(bounds) + 1) / parts:
            bounds.append((start, i + 1))
            start = i + 1
    bounds.append((start, len(paragraphs)))
    return [b for b in bounds if b[1] > b[0]]


def translate_parallel(translator, *, heading: str, paragraphs: list[str], glossary_text: str, prev_tail: list[str],
                       style: str, notes: str = "", parts: int = 1) -> ChapterResult:
    ranges = split_parts(paragraphs, parts) if parts > 1 and len(paragraphs) >= MIN_PARAGRAPHS else [(0, len(paragraphs))]
    if len(ranges) == 1:
        return translator.translate(heading=heading, paragraphs=paragraphs, glossary_text=glossary_text,
                                    prev_tail=prev_tail, style=style, notes=notes)
    log.info("Translating %d paragraphs as %d parallel parts: %s", len(paragraphs), len(ranges), ranges)

    def work(k: int) -> ChapterResult:
        time.sleep(STAGGER * k)
        a, b = ranges[k]
        n = notes
        if k > 0:
            ctx = "\n".join(paragraphs[max(0, a - CONTEXT):a])
            n = (notes.strip() + "\n\n" if notes.strip() else "") + (
                f"[PHẦN {k + 1}/{len(ranges)} CỦA CHƯƠNG] Chỉ dịch các đoạn trong <chapter>. Các đoạn Hàn ngay trước phần này, "
                f"CHỈ để hiểu ngữ cảnh (ai đang nói, tên gọi), KHÔNG dịch và KHÔNG đưa vào kết quả:\n{ctx}")
        return translator.translate(heading=heading, paragraphs=paragraphs[a:b], glossary_text=glossary_text,
                                    prev_tail=prev_tail if k == 0 else [], style=style, notes=n)

    with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
        results = list(pool.map(work, range(len(ranges))))

    usage: dict = {}
    terms: dict[str, dict] = {}
    out: list[str] = []
    for r in results:
        out += r.paragraphs
        for k, v in r.usage.items():
            usage[k] = usage.get(k, 0) + v
        for t in r.new_terms:
            terms.setdefault(t["source"], t)
    return ChapterResult(heading=results[0].heading, paragraphs=out, new_terms=list(terms.values()), usage=usage,
                         model=results[0].model)
