"""Bring "raw" data into the tool:

- clean_rough_file: a bilingual Word file pasted out of ChatGPT → cleaned standard bilingual .docx in
  data/library/<story>/, opened as a project (Library) and attached to the story (shared termbase).
- prepare_raw: a raw Korean novel (.txt exported from an epub) → the chapters that have no translation
  yet in the story, as ready-to-translate .txt files registered in 🤖 Dịch AI.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .. import config
from ..document.chapter_parser import parse_chapters
from ..document.cleaner import clean_bilingual, read_raw_chapters, write_raw_range
from ..document.docx_reader import read_docx
from ..editor.chapter_editor import service as chapter_service
from ..errors import AppError
from ..logging_setup import get_logger
from ..storage.project_state import slugify, store

log = get_logger("DATA")
LIBRARY = config.DATA_DIR / "library"


class DataError(AppError):
    code = "DATA_ERROR"


def _path(p: str) -> Path:
    path = Path(p.strip().strip('"'))
    if not path.exists():
        raise DataError(f"File không tồn tại: {path}", code="DOCX_NOT_FOUND")
    return path


def library_dir(story: Optional[str]) -> Path:
    d = LIBRARY / (slugify(story) if story else "khac")
    d.mkdir(parents=True, exist_ok=True)
    return d


def clean_rough_file(src: str, story: Optional[str] = None) -> dict:
    from ..ai.translation_jobs import _write_bilingual_docx
    path = _path(src)
    if path.suffix.lower() != ".docx":
        raise DataError("Chỉ làm sạch được file .docx.", code="DOCX_BAD_TYPE")
    blocks = read_docx(path)
    clean, rep = clean_bilingual(blocks)
    if not rep.chapters:
        raise DataError("Không nhận ra chương nào trong file — có thể không phải bản dịch dạng Hàn + Việt.", code="NO_CHAPTERS")
    out = library_dir(story) / f"{slugify(path.stem)}_lam-sach.docx"
    _write_bilingual_docx(out, clean)
    project = chapter_service.open_path(str(out))
    if story:
        store.set_story(project["id"], story)
    index = chapter_service.index(project["id"])           # parses + records chapter count / range
    counts: dict[str, int] = {}
    for c in index["chapters"]:
        counts[c["confidence"]] = counts.get(c["confidence"], 0) + 1
    log.info("Cleaned %s → %s (%s)", path.name, out.name, rep.to_dict())
    return {"source": str(path), "output": str(out), "project_id": project["id"], "report": rep.to_dict(),
            "chapters": len(index["chapters"]), "confidence": counts, "warnings": index["warnings"]}


def translated_numbers(story: Optional[str]) -> set[int]:
    """Chapter numbers that already have a Vietnamese version in some file of the story."""
    done: set[int] = set()
    for d in store.story_projects(slugify(story)) if story else []:
        try:
            _, result = chapter_service._parsed(d["id"])
        except AppError:
            continue
        done |= {n for n, e in result.chapters.items() if e.vi}
    return done


def _ranges(nums: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for n in nums:
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def prepare_raw(src: str, story: Optional[str] = None, from_number: Optional[int] = None,
                to_number: Optional[int] = None) -> dict:
    """Split a raw Korean .txt into the chapters still to translate and register them for 🤖 Dịch AI."""
    from ..ai.translation_jobs import analyze_path
    path = _path(src)
    if path.suffix.lower() != ".txt":
        raise DataError("Raw cần là file .txt (tiếng Hàn).", code="DOCX_BAD_TYPE")
    front, chapters = read_raw_chapters(path)
    if not chapters:
        raise DataError("Không tìm thấy chương nào trong file raw.", code="NO_CHAPTERS")
    sample = " ".join(" ".join(c.lines[:20]) for c in chapters[:3])
    if not re.search(r"[가-힣]", sample):
        raise DataError("File này không phải tiếng Hàn (có vẻ là bản dịch tiếng Anh) — không dùng làm raw được.",
                        code="NOT_KOREAN")
    done = translated_numbers(story)
    lo = from_number if from_number is not None else (min(done) if done else chapters[0].number)
    hi = to_number if to_number is not None else chapters[-1].number
    todo = [c for c in chapters if lo <= c.number <= hi and c.number not in done]
    if not todo:
        raise DataError("Không còn chương nào chưa dịch trong khoảng này.", code="NOTHING_TO_DO")
    out_dir = library_dir(story)
    last_done = max(done) if done else None
    tail = [c for c in todo if last_done is None or c.number > last_done]     # continuation after the last translated
    gaps = [c for c in todo if last_done is not None and c.number < last_done]  # holes inside the translated range
    files = []
    # One file per continuous range: "1942. 제목" headings are confirmed by their neighbours' numbers,
    # so a lone chapter or a jump inside one file would not be recognised reliably.
    groups = [(tail, "tiep-theo")] if tail else []
    for a, b in _ranges([c.number for c in gaps]):
        groups.append(([c for c in gaps if a <= c.number <= b], "chuong-thieu"))
    for group, label in groups:
        a, b = group[0].number, group[-1].number
        name = f"raw_{a}-{b}.txt" if a != b else f"raw_{a}.txt"
        if label == "chuong-thieu":
            name = "raw_chuong-thieu_" + name[4:]
        out, count = write_raw_range(group, out_dir / name)
        meta = analyze_path(str(out))
        files.append({"kind": label, "path": str(out), "chapters": count, "sid": meta["sid"],
                      "range": f"{a}–{b}" if a != b else str(a), "chars": meta["chars"],
                      "estimate": meta["estimate"]})
    log.info("Prepared raw from %s: %s", path.name, [(f["kind"], f["chapters"]) for f in files])
    return {"source": str(path), "raw_chapters": len(chapters), "raw_range": [chapters[0].number, chapters[-1].number],
            "translated": len(done), "files": files}
