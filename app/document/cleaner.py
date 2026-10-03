"""Clean up "raw" data so it fits the tool's format.

1. Bilingual chapters pasted out of ChatGPT conversations (Korean chapter → prompt → ChatGPT's preamble
   → Vietnamese → ChatGPT's closing remark, "2 / 2" version counters, ads…):
   → standard layout per chapter:  [KO heading] KO body  [VI heading] VI body

2. A raw Korean novel exported from an epub to .txt (table of contents at the top, every chapter heading
   repeated 2–3 times):  → one heading per chapter, optional chapter range, blank-line separated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .chapter_parser import NOISE_PREFIX, detect_lang, match_heading
from .models import Block, Run

# --------------------------------------------------------------------------- junk patterns
# Prompt the user typed to ChatGPT (often glued to the end of the last Korean paragraph).
PROMPT_RE = re.compile(r"\s*(?:tiếp tục\s+)?dịch\s+(?:sang|qua)\s+tiếng\s+việt.*$|\s*tiếp tục dịch\b.*$", re.IGNORECASE | re.S)
# ChatGPT's preamble before the translation.
PREAMBLE_RE = re.compile(r"^(?:dưới đây là|đây là|sau đây là|tiếp theo là)\b.{0,200}\bbản dịch", re.IGNORECASE)
# ChatGPT's closing remarks after the translation.
OUTRO_RE = re.compile(r"^(?:bản dịch\b|hy vọng\b|nếu (?:bạn )?cần\b|mình đã\b|tôi đã dịch\b|lưu ý:?\s*bản dịch)"
                      r"|cho tôi biết[!.]?$|hãy cho (?:tôi|mình) biết", re.IGNORECASE)
COUNTER_RE = re.compile(r"^\d+\s*/\s*\d+$")                      # "2 / 2" (ChatGPT answer versions)
ENCODED_RE = re.compile(r"^[A-Za-z0-9+/]{32,}={0,2}$")              # base64 watermarks from web pages
ADS_RE = re.compile(r"^(?:ads\s+by\s+\w+\s*)+$|^(?:grok|chatgpt|gemini|claude|copilot)(?:\s*[\d.]+)?$", re.IGNORECASE)

# Headings that the general parser does not know.
KO_TITLE_HEADING = re.compile(r"^\S{1,20}?\s*(\d{1,4})\s*화\s*(?:\(\s*\d+\s*/\s*\d+\s*\))?$")      # 창작물속으로 2587화(2587/2629)
VI_NUM_IN_LINE = re.compile(r"(?:ep\.?\s*|ch(?:ư|u)(?:ơ|o)ng\s*|t(?:ậ|a)p\s*|^)(\d{1,4})(?=\s*(?:[./:\-–—)(]|\s|$))", re.IGNORECASE)


def _p(text: str, like: Optional[Block] = None) -> Block:
    if like is not None and like.text == text:
        return like
    return Block.model_construct(type="paragraph", level=None, align=None,
                                 runs=[Run.model_construct(text=text, b=False, i=False, u=False)] if text else [])


def _heading(text: str) -> Block:
    return Block.model_construct(type="heading", level=2, align=None,
                                 runs=[Run.model_construct(text=text, b=False, i=False, u=False)])


def is_prompt_line(text: str) -> bool:
    return bool(PROMPT_RE.search(text)) and detect_lang(PROMPT_RE.sub("", text)) != "vi"


def ko_heading_number(text: str) -> Optional[tuple[int, bool]]:
    """(chapter number, weak) when the line looks like a Korean chapter heading."""
    t = text.strip()
    m = KO_TITLE_HEADING.match(t)
    if m and re.search(r"[가-힣]", t):
        return int(m.group(1)), False
    hm = match_heading(_p(t))
    if hm and hm.lang_hint != "vi" and (re.search(r"[가-힣]", t) or t.lower().startswith("ep")):
        return hm.number, hm.weak
    return None


def _plausible(n: int, weak: bool, current: Optional[int], zone: str) -> bool:
    """Strong headings ("창작물속으로 2746화", "EP.2297 2297. …") are trusted even after a gap in the
    numbering; weak ones ("3. 제목") only when they continue the sequence."""
    if current is None:
        return True
    if weak:
        return current < n <= current + 3
    return n != current or zone == "vi"                 # same number again in the Korean part = repeated line


@dataclass
class CleanReport:
    chapters: int = 0
    with_vi: int = 0
    removed: dict = field(default_factory=lambda: {"prompts": 0, "preambles": 0, "outros": 0, "counters": 0, "ads": 0,
                                                   "instructions": 0})
    synthesized_vi_headings: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"chapters": self.chapters, "with_vi": self.with_vi, "removed": self.removed,
                "synthesized_vi_headings": self.synthesized_vi_headings, "notes": self.notes[:50]}


def clean_bilingual(blocks: list[Block]) -> tuple[list[Block], CleanReport]:
    """ChatGPT-dump bilingual document → standard bilingual layout.

    A chapter is often translated in several rounds (Korean part 1 → prompt → Vietnamese part 1 →
    Korean part 2 → "tiếp tục dịch…" → Vietnamese part 2 …). All Korean parts of a chapter are kept
    together, then one Vietnamese heading, then all Vietnamese parts.
    """
    rep = CleanReport()
    out: list[Block] = []
    ch: Optional[dict] = None          # {"number", "heading", "ko": [...], "vi": [...], "vi_heading"}
    zone = "pre"                       # pre | ko | prompt | vi

    def texts_ahead(i: int, k: int = 3) -> list[str]:
        res = []
        for nb in blocks[i + 1:]:
            s = nb.text.strip()
            if s:
                res.append(s)
                if len(res) >= k:
                    break
        return res

    def trim_vi_end(vi: list[Block]) -> None:
        # ChatGPT's closing remark at the end of each Vietnamese round
        while vi and (OUTRO_RE.search(vi[-1].text.strip()) or not vi[-1].text.strip()):
            if vi[-1].text.strip():
                rep.removed["outros"] += 1
            vi.pop()

    def flush() -> None:
        if ch is None:
            return
        trim_vi_end(ch["vi"])
        out.append(ch["heading"])
        out.extend(ch["ko"])
        if ch["vi"]:
            rep.with_vi += 1
            vh = ch["vi_heading"]
            if not vh:
                vh = f"Chương {ch['number']}"
                rep.synthesized_vi_headings += 1
            out.append(_heading(vh))
            out.extend(ch["vi"])

    for i, b in enumerate(blocks):
        t = b.text.strip()
        if not t:
            continue
        if COUNTER_RE.match(t):
            rep.removed["counters"] += 1
            continue
        if ADS_RE.match(t) or ENCODED_RE.match(t):
            rep.removed["ads"] += 1
            continue
        t_noads = NOISE_PREFIX.sub("", t)          # "Ads by Pubfuture …", "Interrupted …"
        found = ko_heading_number(t_noads)
        number = ch["number"] if ch else None
        if found and detect_lang(t_noads) != "vi" and _plausible(found[0], found[1], number, zone):
            flush()
            ch = {"number": found[0], "heading": _heading(t_noads) if b.type != "heading" or t_noads != t else b,
                  "ko": [], "vi": [], "vi_heading": None}
            zone = "ko"
            rep.chapters += 1
            continue
        if ch is None:
            out.append(b)                            # text before the first chapter
            continue
        lang = detect_lang(t)

        if zone == "vi" and lang == "ko":
            # Korean again inside the Vietnamese part: the next round of the same chapter starts —
            # unless it is a lone untranslated line in the translation.
            ahead = texts_ahead(i, 2)
            if PROMPT_RE.search(t) or VI_TAIL_RE.search(t) or (ahead and (detect_lang(ahead[0]) == "ko"
                                                                     or PROMPT_RE.search(ahead[0]))):
                trim_vi_end(ch["vi"])
                zone = "ko"
        if zone == "ko":
            if PROMPT_RE.search(t):                  # prompt glued to (or after) the Korean text
                kept = PROMPT_RE.sub("", t).strip()
                rep.removed["prompts"] += 1
                if kept and detect_lang(kept) != "vi":
                    ch["ko"].append(_p(kept))
                zone = "prompt"
                continue
            tail = VI_TAIL_RE.search(t) if lang != "vi" else None
            if tail and len(tail.group(0).split()) >= 3:   # "…접니다.” không sử dụng xưng hô mày-tao"
                rep.removed["instructions"] += 1
                ch["ko"].append(_p(t[:tail.start()].strip()))
                zone = "prompt"
                continue
            if lang == "vi":                         # translation starts without a prompt line
                zone = "prompt"
            else:
                ch["ko"].append(b)
                continue
        if zone == "prompt":
            if PREAMBLE_RE.search(t):
                rep.removed["preambles"] += 1
                zone = "vi"
                continue
            if PROMPT_RE.search(t) or (lang == "vi" and (_looks_like_instruction(t)
                                                         or any(PREAMBLE_RE.search(x) for x in texts_ahead(i)))):
                rep.removed["instructions"] += 1
                continue
            zone = "vi"                              # no preamble: this is already the translation
        if zone == "vi":
            if PREAMBLE_RE.search(t):
                rep.removed["preambles"] += 1
                continue
            if PROMPT_RE.search(t) and detect_lang(PROMPT_RE.sub("", t)) != "ko":
                rep.removed["prompts"] += 1          # a stray "tiếp tục dịch…" between rounds
                continue
            vh = vi_heading(t, ch["number"]) if (not ch["vi"] or len(t) <= 60) else None
            if vh and (lang == "vi" or lang is None):
                if not ch["vi_heading"]:
                    ch["vi_heading"] = vh
                continue                             # the heading, or its repeat in a later round
            ch["vi"].append(b)
    flush()
    return out, rep


# Vietnamese text (no Hangul, with Vietnamese diacritics) glued to the end of a Korean paragraph.
VI_TAIL_RE = re.compile(r"\s+(?=[^가-힣]*[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ])"
                        r"[^가-힣]+$", re.IGNORECASE)
_INSTRUCTION_WORDS = re.compile(r"\b(hán việt|latin hóa|latinh hóa|xưng hô|dịch chi tiết|sát nghĩa|từ nhạy cảm|ví dụ như)\b", re.IGNORECASE)


def _looks_like_instruction(t: str) -> bool:
    return bool(_INSTRUCTION_WORDS.search(t)) or t.startswith(",")


def vi_heading(text: str, number: Optional[int]) -> Optional[str]:
    """If this first Vietnamese line is the chapter heading, return it normalized."""
    t = text.strip()
    if number is None or len(t) > 90:
        return None
    nums = [int(m.group(1)) for m in VI_NUM_IN_LINE.finditer(t)]
    if number not in nums:
        return None
    # "EP.2297 2297. Atlantis của Thần" → keep; "Chương 2587/2629" → "Chương 2587"
    # "Vào Tác Phẩm - Chương 2587 (2587/2629)" → "Chương 2587"
    t = re.sub(r"\s*\(\s*\d+\s*/\s*\d+\s*\)\s*$", "", t)
    t = re.sub(rf"(ch(?:ư|u)(?:ơ|o)ng\s*{number})\s*/\s*\d+", r"\1", t, flags=re.IGNORECASE)
    m = re.search(rf"ch(?:ư|u)(?:ơ|o)ng\s*{number}\b(.*)$", t, re.IGNORECASE)
    if m and not re.match(rf"^\s*(?:ep\.?\s*\d+\s+)?{number}\.", t, re.IGNORECASE):
        rest = m.group(1).strip(" :.-–—")
        return f"Chương {number}" + (f": {rest}" if rest else "")
    hm = match_heading(_p(t))
    if hm and hm.number == number:
        return t
    if len(t) <= 40 and re.search(r"(?:ep\.?|ch(?:ư|u)(?:ơ|o)ng|t(?:ậ|a)p)\s*" + str(number), t, re.IGNORECASE):
        return f"Chương {number}"
    return None


# --------------------------------------------------------------------------- raw Korean txt (epub export)
RAW_HEADING = re.compile(r"^(\d{1,4})\.\s*(.{1,60}?)\.?$")


@dataclass
class RawChapter:
    number: int
    heading: str
    lines: list[str]


def read_raw_chapters(path: str | Path) -> tuple[list[str], list[RawChapter]]:
    """Split an epub-exported raw novel into chapters, collapsing repeated headings and the TOC.
    A numbered line ("1. 첫째") inside a chapter is content unless its number follows the sequence."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    front: list[str] = []
    chapters: list[RawChapter] = []
    cur: Optional[RawChapter] = None
    empty_streak = 0                                      # consecutive headings without text = table of contents
    for line in text.splitlines():
        s = line.strip()
        m = RAW_HEADING.match(s) if len(s) <= 70 else None
        if m:
            n = int(m.group(1))
            empty = cur is not None and not any(x.strip() for x in cur.lines)
            if cur is not None and n == cur.number and empty:
                continue                                  # the same heading repeated
            forward = cur is None or cur.number < n <= cur.number + 10
            restart = cur is not None and n < cur.number and empty and empty_streak >= 2   # TOC ended, chapter 1 starts
            if forward or restart:
                empty_streak = empty_streak + 1 if empty else 0
                cur = RawChapter(n, s.rstrip("."), [])
                chapters.append(cur)
                continue
        (cur.lines if cur is not None else front).append(line)
    body = [c for c in chapters if any(x.strip() for x in c.lines)]   # drops the table of contents
    merged: dict[int, RawChapter] = {}
    order: list[int] = []
    for c in body:
        if c.number in merged:
            merged[c.number].lines.extend(c.lines)
        else:
            merged[c.number] = c
            order.append(c.number)
    return front, [merged[n] for n in order]


def write_raw_range(chapters: Iterable[RawChapter], out: str | Path, from_n: Optional[int] = None,
                    to_n: Optional[int] = None) -> tuple[Path, int]:
    out = Path(out)
    parts, count = [], 0
    for c in chapters:
        if (from_n is not None and c.number < from_n) or (to_n is not None and c.number > to_n):
            continue
        lines = [l.strip() for l in c.lines if l.strip()]
        parts.append(c.heading + "\n" + "\n".join(lines))
        count += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    return out, count
