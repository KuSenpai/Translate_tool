"""Parallel chunked translation of a long chapter."""
import threading

import pytest

from app.ai import chunked
from app.ai.chunked import MIN_PARAGRAPHS, split_parts, translate_parallel
from app.ai.novel_translator import ChapterResult


@pytest.fixture(autouse=True)
def no_stagger(monkeypatch):
    monkeypatch.setattr(chunked, "STAGGER", 0)


def test_split_parts_covers_everything_in_order():
    paras = ["x" * (10 + i % 7) for i in range(100)]
    for parts in (1, 2, 3, 4):
        r = split_parts(paras, parts)
        assert len(r) == parts and r[0][0] == 0 and r[-1][1] == 100
        assert all(a[1] == b[0] for a, b in zip(r, r[1:]))
        sizes = [sum(len(p) for p in paras[a:b]) for a, b in r]
        assert max(sizes) - min(sizes) < 40
    assert len(split_parts(["a"] * 20, 4)) <= 2            # tiny chapters are not cut into crumbs


class Fake:
    def __init__(self):
        self.calls, self.threads, self.lock = [], set(), threading.Lock()

    def translate(self, *, heading, paragraphs, glossary_text, prev_tail, style, notes=""):
        with self.lock:
            self.calls.append({"n": len(paragraphs), "tail": prev_tail, "notes": notes, "first": paragraphs[0]})
            self.threads.add(threading.get_ident())
        return ChapterResult(heading=f"H{paragraphs[0]}", paragraphs=[f"vi-{p}" for p in paragraphs],
                             new_terms=[{"source": "공통", "target": "Chung"}, {"source": f"t{paragraphs[0]}", "target": "x"}],
                             usage={"input_tokens": 10, "output_tokens": 5}, model="fake")


def test_parallel_merge_keeps_order_and_sums_usage():
    paras = [f"p{i:03d}" for i in range(90)]
    f = Fake()
    r = translate_parallel(f, heading="H", paragraphs=paras, glossary_text="g", prev_tail=["tail"], style="s", notes="N", parts=3)
    assert r.paragraphs == [f"vi-{p}" for p in paras]                       # same order, same count
    assert r.heading == "Hp000" and r.usage == {"input_tokens": 30, "output_tokens": 15}
    assert len(r.new_terms) == 4 and [t["source"] for t in r.new_terms].count("공통") == 1      # shared term de-duplicated
    first = next(c for c in f.calls if c["first"] == paras[0])
    later = [c for c in f.calls if c["first"] != paras[0]]
    assert first["tail"] == ["tail"] and all(c["tail"] == [] for c in later)           # continuity only for the first part
    assert all("KHÔNG dịch" in c["notes"] and "p0" in c["notes"] for c in later)        # Korean context for the others
    assert sum(c["n"] for c in f.calls) == 90 and len(f.calls) == 3


def test_short_chapter_or_one_part_is_a_single_call():
    f = Fake()
    translate_parallel(f, heading="H", paragraphs=["a"] * (MIN_PARAGRAPHS - 1), glossary_text="", prev_tail=[], style="s", parts=4)
    translate_parallel(f, heading="H", paragraphs=["a"] * 100, glossary_text="", prev_tail=[], style="s", parts=1)
    assert [c["n"] for c in f.calls] == [MIN_PARAGRAPHS - 1, 100]


def test_parts_start_staggered(monkeypatch):
    """Parts must not hit the provider in the same second (xAI allows 2 requests per second per team)."""
    import time
    monkeypatch.setattr(chunked, "STAGGER", 0.3)
    starts = []

    class Slow(Fake):
        def translate(self, **kw):
            starts.append(time.time())
            return super().translate(**kw)

    translate_parallel(Slow(), heading="H", paragraphs=[f"p{i:03d}" for i in range(90)], glossary_text="", prev_tail=[], style="s", parts=3)
    starts.sort()
    assert starts[1] - starts[0] >= 0.25 and starts[2] - starts[1] >= 0.25
