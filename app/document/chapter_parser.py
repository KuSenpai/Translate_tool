"""Detect chapter headings in a Korean/Vietnamese interleaved document.

Expected layout (repeated):  [KO heading] KO body  [VI heading] VI body

Design notes
- A heading must be a *whole, short paragraph* that matches one of HEADING_PATTERNS,
  so numbers inside sentences ("anh ấy 12 tuổi") are never taken as headings.
- A section's language is decided by its body text (Hangul ratio), with the heading
  pattern only as a fallback — translators often reuse the same heading style.
- Anything suspicious (duplicates, missing half, out-of-order numbers, mixed-language
  bodies, inferred boundaries) is reported as a warning and lowers confidence;
  nothing is silently guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from ..errors import ChapterError
from ..logging_setup import get_logger
from .models import Block

log = get_logger("CHAPTER")

Lang = Literal["ko", "vi"]

_SEP = r"(?:\s*[:：.\-–—|]\s*|\s+)"
_TITLE = r"(?:{sep}(.*))?".format(sep=_SEP)
# (regex, language hint, weak). Group 1 = number, group 2 = optional title.
# "Weak" patterns (a bare "1920. Title") can also match numbered lists inside the story, so they are
# only accepted when a neighbouring heading has a close chapter number (see _filter_weak).
HEADING_PATTERNS: list[tuple[re.Pattern, Optional[Lang], bool]] = [
    (re.compile(rf"^제\s*(\d{{1,4}})\s*[화장회편]{_TITLE}$"), "ko", False),
    (re.compile(rf"^(\d{{1,4}})\s*화{_TITLE}$"), "ko", False),
    # "창작물속으로 2587화(2587/2629)": novel title + chapter number (+ position in a pasted batch)
    (re.compile(r"^\S{1,20}?\s*(\d{1,4})\s*화\s*(?:\(\s*\d+\s*/\s*\d+\s*\)?)?()$"), "ko", False),
    (re.compile(rf"^ch(?:ư|u)(?:ơ|o)ng\s*(\d{{1,4}}){_TITLE}$", re.IGNORECASE), "vi", False),
    (re.compile(rf"^t(?:ậ|a)p\s*(\d{{1,4}}){_TITLE}$", re.IGNORECASE), "vi", False),
    (re.compile(rf"^chapter\s*(\d{{1,4}}){_TITLE}$", re.IGNORECASE), None, False),
    (re.compile(rf"^ch(?:ap)?\.\s*(\d{{1,4}}){_TITLE}$", re.IGNORECASE), None, False),
    # "EP.2221 2221. 경성 2033"
    (re.compile(r"^ep(?:isode)?\.?\s*\d{1,4}\s+(\d{1,4})\s*\.\s*(.*)$", re.IGNORECASE), None, False),
    (re.compile(rf"^ep(?:isode)?\.?\s*(\d{{1,4}}){_TITLE}$", re.IGNORECASE), None, False),
    # "1920. 다크 문" / "1920. Trăng Rằm Đen" (not "100.000 chiến binh")
    (re.compile(r"^(\d{1,4})\s*\.\s*(?!\d)(\S.*)$"), None, True),
]
# Web-copy junk that sometimes sticks to the front of a heading ("Ads by Pubfuture 1921. 다크 문").
NOISE_PREFIX = re.compile(r"^(?:(?:ads\s+by\s+\w+|interrupted)\s+)+", re.IGNORECASE)
_DECOR = "[]【】()（）<>《》「」『』*#=~_-–— \t　"
_MAX_HEADING_LEN = 150
_MAX_LOOSE_TITLE_LEN = 60
_SENTENCE_END = re.compile(r"[.!?…\"”’»。]$")

_HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
_LATIN = re.compile(r"[A-Za-zÀ-ỹĐđ]")


def detect_lang(text: str) -> Optional[Lang]:
    h = len(_HANGUL.findall(text))
    l = len(_LATIN.findall(text))
    if h + l == 0:
        return None
    return "ko" if h >= 0.3 * (h + l) else "vi"


@dataclass
class HeadingMatch:
    number: int
    title: str
    lang_hint: Optional[Lang]
    weak: bool = False


def match_heading(block: Block) -> Optional[HeadingMatch]:
    raw = block.text.strip()
    if not raw or len(raw) > _MAX_HEADING_LEN or "\n" in raw:
        return None
    if raw[0] in "「『" and raw[-1] in "」』":   # system messages (「1. 회복 캡슐(S)」) are never headings
        return None
    text = NOISE_PREFIX.sub("", raw.strip(_DECOR)).strip(_DECOR)
    styled = block.type == "heading" or (bool(block.runs) and all(r.b for r in block.runs if r.text.strip()))
    for pattern, hint, weak in HEADING_PATTERNS:
        m = pattern.match(text)
        if not m:
            continue
        title = (m.group(2) or "").strip().strip(_DECOR)
        if title:
            # Title separated only by whitespace ("Chương 12 đã kết thúc.") is the risky
            # case: accept only when it looks like a heading, not like a sentence.
            after_num = text[m.end(1):]
            loose = not re.match(r"^\s*[화장회편]?\s*[:：.\-–—|]", after_num)
            if (loose or weak) and not styled and (len(title) > _MAX_LOOSE_TITLE_LEN or _SENTENCE_END.search(title)):
                return None
            # Even with a separator, a long sentence ("17화. 최종 보스는커녕 …다.") is prose, not a title.
            if not styled and len(title) > _MAX_LOOSE_TITLE_LEN and _SENTENCE_END.search(title):
                return None
        return HeadingMatch(int(m.group(1)), title, hint, weak)
    return None


@dataclass
class Section:
    number: int
    lang: Optional[Lang]
    heading_index: int          # block index of the heading (-1 if inferred)
    start: int                  # first body block
    end: int                    # exclusive
    heading_text: str
    title: str
    inferred: bool = False

    def to_dict(self) -> dict:
        return {"number": self.number, "lang": self.lang, "heading_index": self.heading_index,
                "start": self.start, "end": self.end, "heading_text": self.heading_text,
                "title": self.title, "inferred": self.inferred}


@dataclass
class ChapterEntry:
    number: int
    ko: list[Section] = field(default_factory=list)
    vi: list[Section] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> str:
        if len(self.ko) != 1 or len(self.vi) != 1 or any(s.inferred for s in self.ko + self.vi):
            return "low"
        return "medium" if self.warnings else "high"

    def to_dict(self) -> dict:
        return {"number": self.number, "confidence": self.confidence, "warnings": self.warnings,
                "ko": [s.to_dict() for s in self.ko], "vi": [s.to_dict() for s in self.vi]}


@dataclass
class ParseResult:
    chapters: dict[int, ChapterEntry]
    sections: list[Section]
    warnings: list[str]

    def summary(self) -> list[dict]:
        return [{"number": c.number, "confidence": c.confidence, "has_ko": bool(c.ko), "has_vi": bool(c.vi),
                 "title": (c.vi[0].title if c.vi else (c.ko[0].title if c.ko else "")),
                 "warnings": c.warnings} for c in sorted(self.chapters.values(), key=lambda c: c.number)]


def _trim(blocks: list[Block], start: int, end: int) -> tuple[int, int]:
    while start < end and not blocks[start].text.strip():
        start += 1
    while end > start and not blocks[end - 1].text.strip():
        end -= 1
    return start, end


def _para_langs(blocks: list[Block], start: int, end: int) -> list[tuple[int, Optional[Lang]]]:
    return [(i, detect_lang(blocks[i].text)) for i in range(start, end)]


def _leading_lang(blocks: list[Block], start: int, end: int, sample: int = 3) -> Optional[Lang]:
    """Language of the first few paragraphs right after the heading (a section may have a
    foreign-language tail when the next heading is missing, so the whole body is not used)."""
    langs = [l for _, l in _para_langs(blocks, start, end) if l][:sample]
    if not langs:
        return None
    return max(set(langs), key=langs.count)


def _find_switch(blocks: list[Block], sec: Section, to_lang: Lang) -> Optional[int]:
    """Index where the body cleanly switches from sec.lang to `to_lang` (and stays there)."""
    langs = [(i, l) for i, l in _para_langs(blocks, sec.start, sec.end) if l]
    for k, (i, l) in enumerate(langs):
        if l == to_lang:
            before = [x for _, x in langs[:k]]
            after = [x for _, x in langs[k:]]
            if before and all(x == sec.lang for x in before) and all(x == to_lang for x in after) and len(after) >= 2:
                return i
            return None
    return None


def _filter_weak(cands: list[tuple[int, HeadingMatch]]) -> tuple[list, list]:
    """Keep a weak heading only if an adjacent candidate has a close chapter number and is a few
    paragraphs away (real KO/VI headings come in pairs separated by a chapter body; list items don't)."""
    def supported(k: int) -> bool:
        i, m = cands[k]
        for j in (k - 1, k + 1):
            if 0 <= j < len(cands):
                i2, m2 = cands[j]
                if abs(m2.number - m.number) <= 3 and abs(i2 - i) >= 3:
                    return True
        return False
    kept, rejected = [], []
    for k, c in enumerate(cands):
        (rejected if c[1].weak and not supported(k) else kept).append(c)
    # A numbered list inside a chapter ("1. …", "2. …") can support itself; it is still far *below* the
    # chapter numbers around it. A weak heading may go back a little (a chapter placed late), not more.
    seq, last = [], None
    for c in kept:
        if c[1].weak and last is not None and c[1].number < last - 3:
            rejected.append(c)
            continue
        seq.append(c)
        last = c[1].number if last is None else max(last, c[1].number)
    return seq, sorted(rejected)


_BARE_NUMBER = re.compile(r"^\d{1,4}$")


def _add_bare_headings(blocks: list[Block], headings: list[tuple[int, HeadingMatch]]) -> tuple[list, set[int]]:
    """A paragraph that is only a number ("2151") marks a chapter when it is the *next* chapter number:
    greater than the previous heading by 1–3, not greater than the following heading, and a few
    paragraphs after the previous heading, followed by a body of its own. Other bare numbers ("12", countdowns) stay content."""
    accepted: list[tuple[int, HeadingMatch]] = []
    k = 0
    for i, b in enumerate(blocks):
        t = b.text.strip()
        if not _BARE_NUMBER.match(t):
            continue
        while k < len(headings) and headings[k][0] < i:
            k += 1
        prev = accepted[-1] if accepted and accepted[-1][0] > (headings[k - 1][0] if k else -1) else \
            (headings[k - 1] if k else None)
        nxt = headings[k] if k < len(headings) else None
        n = int(t)
        if prev and prev[1].number < n <= prev[1].number + 3 and i - prev[0] >= 3 \
                and (nxt is None or (nxt[1].number >= n and nxt[0] - i >= 4)):
            accepted.append((i, HeadingMatch(n, "", None)))
    merged = sorted(headings + accepted, key=lambda h: h[0])
    return merged, {i for i, _ in accepted}


MISSING_WARNING_MARK = "số chương trong dãy"


def missing_warning(nums: list[int]) -> tuple[list[int], list[str]]:
    """Chapter numbers absent from the sorted `nums` range, plus the matching warning (as a 0/1-item list)."""
    have = set(nums)
    missing = [x for x in range(nums[0], nums[-1] + 1) if x not in have] if nums else []
    if not missing:
        return [], []
    preview = ", ".join(map(str, missing[:15])) + ("..." if len(missing) > 15 else "")
    return missing, [f"Thiếu {len(missing)} {MISSING_WARNING_MARK} {nums[0]}–{nums[-1]}: {preview}"]


def parse_chapters(blocks: list[Block]) -> ParseResult:
    candidates = [(i, m) for i, b in enumerate(blocks) if (m := match_heading(b))]
    headings, rejected = _filter_weak(candidates)
    headings, bare = _add_bare_headings(blocks, headings)
    warnings: list[str] = []
    if not headings:
        warnings.append("Không tìm thấy heading chương nào (ví dụ '제 12 화', 'Chương 12', 'Chapter 12').")
        return ParseResult({}, [], warnings)
    if any(b.text.strip() for b in blocks[: headings[0][0]]):
        warnings.append(f"Có {headings[0][0]} đoạn trước heading đầu tiên — phần này được bỏ qua.")

    sections: list[Section] = []
    for k, (idx, m) in enumerate(headings):
        nxt = headings[k + 1][0] if k + 1 < len(headings) else len(blocks)
        start, end = _trim(blocks, idx + 1, nxt)
        lang = _leading_lang(blocks, start, end) or m.lang_hint
        sections.append(Section(m.number, lang, idx, start, end, blocks[idx].text.strip(), m.title))

    chapters: dict[int, ChapterEntry] = {}
    unknown: list[Section] = []
    for s in sections:
        entry = chapters.setdefault(s.number, ChapterEntry(s.number))
        if s.lang == "ko":
            entry.ko.append(s)
        elif s.lang == "vi":
            entry.vi.append(s)
        else:
            unknown.append(s)
            entry.warnings.append(f"Heading '{s.heading_text}' (đoạn #{s.heading_index + 1}) không có nội dung / không xác định được ngôn ngữ.")

    for s in sections:
        if s.heading_index in bare:
            chapters[s.number].warnings.append(
                f"Heading chương {s.number} chỉ là con số '{s.heading_text}' (đoạn #{s.heading_index + 1}) — "
                "hãy kiểm tra ranh giới chương.")

    for idx, m in rejected:
        owner = next((sec for sec in sections if sec.start <= idx < sec.end), None)
        note = (f"Dòng '{blocks[idx].text.strip()[:60]}' (đoạn #{idx + 1}) giống heading nhưng bị bỏ qua "
                "vì số chương không khớp thứ tự xung quanh.")
        (chapters[owner.number].warnings if owner else warnings).append(note)

    # Order check: a number smaller than the previous heading suggests a misdetected heading.
    prev: Optional[Section] = None
    for s in sections:
        if prev and s.number < prev.number:
            chapters[s.number].warnings.append(
                f"Heading '{s.heading_text}' (đoạn #{s.heading_index + 1}) xuất hiện sau chương {prev.number} — "
                "thứ tự bất thường, có thể là heading nhận nhầm.")
        prev = s

    for entry in chapters.values():
        n = entry.number
        if len(entry.ko) > 1:
            entry.warnings.append(f"Có {len(entry.ko)} phần tiếng Hàn cho chương {n} (trùng số chương). Hãy chọn đúng phần.")
        if len(entry.vi) > 1:
            entry.warnings.append(f"Có {len(entry.vi)} phần tiếng Việt cho chương {n} (trùng số chương). Hãy chọn đúng phần.")

        # Korean body that turns into Vietnamese: the VI heading is probably missing.
        for ko in list(entry.ko):
            switch = _find_switch(blocks, ko, "vi")
            if switch is None:
                continue
            if not entry.vi:
                inferred = Section(n, "vi", -1, switch, ko.end, "(suy luận)", "", inferred=True)
                ko.end = _trim(blocks, ko.start, switch)[1]
                entry.vi.append(inferred)
                entry.warnings.append(
                    f"Không có heading tiếng Việt cho chương {n}. Ranh giới được SUY LUẬN tại đoạn #{switch + 1} "
                    "(chỗ văn bản chuyển sang tiếng Việt). Hãy kiểm tra kỹ.")
            else:
                entry.warnings.append(
                    f"Phần tiếng Hàn chương {n} có đoạn tiếng Việt từ đoạn #{switch + 1} — ranh giới chương không rõ.")

        for vi in entry.vi:
            ko_paras = [i for i, l in _para_langs(blocks, vi.start, vi.end) if l == "ko"]
            if ko_paras:
                entry.warnings.append(
                    f"Phần tiếng Việt chương {n} còn {len(ko_paras)} đoạn tiếng Hàn (đoạn #{ko_paras[0] + 1}...). "
                    "Có thể chưa dịch hoặc ranh giới chương không rõ.")
            if vi.start >= vi.end:
                entry.warnings.append(f"Phần tiếng Việt chương {n} trống.")
        for ko in entry.ko:
            if ko.start >= ko.end:
                entry.warnings.append(f"Phần tiếng Hàn chương {n} trống.")

        if not entry.ko and entry.vi:
            entry.warnings.append(f"Không tìm thấy bản tiếng Hàn của chương {n}.")
        if entry.ko and not entry.vi:
            entry.warnings.append(f"Không tìm thấy bản dịch tiếng Việt của chương {n}.")
        if len(entry.ko) == 1 and len(entry.vi) == 1 and entry.vi[0].heading_index != -1 \
                and entry.vi[0].heading_index < entry.ko[0].heading_index:
            entry.warnings.append(f"Bản Việt chương {n} nằm TRƯỚC bản Hàn — kiểm tra lại thứ tự.")

    warnings += missing_warning(sorted(chapters))[1]
    log.info("Detected %d chapters (%d headings)", len(chapters), len(sections))
    return ParseResult(chapters, sections, warnings)


@dataclass
class ChapterContent:
    number: int
    ko_title: str
    vi_title: str
    ko_heading: str
    vi_heading: str
    ko_blocks: list[Block]
    vi_blocks: list[Block]
    confidence: str
    warnings: list[str]
    ko_choice: int
    vi_choice: int
    ko_options: int
    vi_options: int


def extract_chapter(blocks: list[Block], result: ParseResult, number: int,
                    ko_choice: int = 0, vi_choice: int = 0) -> ChapterContent:
    entry = result.chapters.get(number)
    if entry is None:
        avail = sorted(result.chapters)
        hint = f" Có các chương: {avail[0]}–{avail[-1]}." if avail else ""
        raise ChapterError(f"Không tìm thấy chương {number} trong file.{hint}", code="CHAPTER_NOT_FOUND")
    for name, choice, opts in (("tiếng Hàn", ko_choice, entry.ko), ("tiếng Việt", vi_choice, entry.vi)):
        if opts and not 0 <= choice < len(opts):
            raise ChapterError(f"Lựa chọn phần {name} #{choice + 1} không hợp lệ (có {len(opts)}).", code="BAD_CHOICE")
    ko = entry.ko[ko_choice] if entry.ko else None
    vi = entry.vi[vi_choice] if entry.vi else None
    log.info("Found Chapter %d (confidence=%s, warnings=%d)", number, entry.confidence, len(entry.warnings))
    return ChapterContent(
        number=number,
        ko_title=ko.title if ko else "",
        vi_title=vi.title if vi else "",
        ko_heading=ko.heading_text if ko else "",
        vi_heading=vi.heading_text if vi else "",
        ko_blocks=[b.model_copy(deep=True) for b in blocks[ko.start:ko.end]] if ko else [],
        vi_blocks=[b.model_copy(deep=True) for b in blocks[vi.start:vi.end]] if vi else [],
        confidence=entry.confidence,
        warnings=list(entry.warnings),
        ko_choice=ko_choice, vi_choice=vi_choice,
        ko_options=len(entry.ko), vi_options=len(entry.vi),
    )
