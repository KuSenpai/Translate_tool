"""Automatic chapter titles: "<chapter number>. <arc name> (<n>)".

The novel is split into long story arcs that interleave. Every arc has a name and a running counter: the
n-th chapter of that arc gets "(n)". Arcs are found by the *Korean* heading of the chapter ("1920. 다크 문"
→ arc "다크 문"); chapters without a Korean title continue the arc of the previous chapter.

Data (per story, or per project when it is not in a story): `arcs.json`
    arcs:   [{id, name, ko: [normalised Korean titles], big, base, notes}]
    assign: {"<chapter number>": {"arc": id, "by": "ko-title|previous|manual"}}
    template: "{number}. {name} ({n})"

The counter is derived, not stored: n(chapter) = arc.base + (assigned chapters of the arc below this chapter) + 1,
so re-applying a title never counts twice and chapters can be assigned in any order. `base` is how many chapters
of the arc came before the first assigned one (set it from the last published title, e.g. "Dark Moon (95)").
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Optional

from ..errors import AppError
from ..storage.project_state import _read_json, _write_json, store

DEFAULT_TEMPLATE = "{number}. {name} ({n})"
# The big arcs the author keeps coming back to (Vietnamese name as used on Wattpad → Korean title in the raw).
BIG_ARCS = [
    ("Atlantis của Thần", ["신의 아틀란티스"]),
    ("Quang Minh Thăng Thiên Đồ", ["광명승천도"]),
    ("Eternal Eden", ["이터널 에덴"]),
    ("Dark Moon", ["다크 문"]),
    ("Cứu Tinh Học Viện", ["아카데미의 구원자"]),
    ("Kiếm sĩ Hoa Mai tái sinh vào gia tộc Bá Tước", ["백작가에 환생한 매화검수"]),
]
_PREFIX = re.compile(r"^\s*(?:EP\.?\s*\d+\s+)?\d+\s*[.:\-–—]\s*", re.IGNORECASE)


class ArcError(AppError):
    code = "ARC_ERROR"


def norm_key(title: str) -> str:
    """Comparable form of a Korean arc title: no chapter-number prefix, no spaces/punctuation, lower case."""
    t = _PREFIX.sub("", title or "")
    return re.sub(r"[\s\W_]+", "", t, flags=re.UNICODE).lower()


# --------------------------------------------------------------------------- storage
def _file(pid: str) -> Path:
    story = store.story_of(pid)
    return (store.story_dir(story) if story else store.dir(pid)) / "arcs.json"


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def load(pid: str) -> dict:
    data = _read_json(_file(pid), None)
    fresh = not data
    if fresh:
        data = {"arcs": [{"id": _new_id(), "name": n, "ko": [norm_key(k) for k in ko], "ko_raw": ko, "big": True,
                          "base": 0, "notes": ""} for n, ko in BIG_ARCS], "assign": {}, "template": DEFAULT_TEMPLATE}
    data.setdefault("assign", {})
    data.setdefault("template", DEFAULT_TEMPLATE)
    if fresh:                      # ids must stay stable between calls
        save(pid, data)
    return data


def save(pid: str, data: dict) -> dict:
    f = _file(pid)
    f.parent.mkdir(parents=True, exist_ok=True)
    _write_json(f, data)
    return data


def _arc(data: dict, arc_id: Optional[str]) -> Optional[dict]:
    return next((a for a in data["arcs"] if a["id"] == arc_id), None)


_STOP_WORDS = {"cua", "trong", "vao", "o", "the", "of"}      # connectors the author spells differently from time to time


def name_key(name: str) -> str:
    """Comparable form of an arc's Vietnamese name: no accents/punctuation/connectors ("của", "trong", "vào"), lower case."""
    import unicodedata
    t = unicodedata.normalize("NFD", (name or "").replace("đ", "d").replace("Đ", "D"))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return "".join(w for w in re.split(r"[\W_]+", t) if w and w not in _STOP_WORDS)


def find_by_name(data: dict, name: str) -> Optional[dict]:
    key = name_key(name)
    return next((a for a in data["arcs"] if key and name_key(a["name"]) == key), None)


def find_arc(data: dict, ko_title: str) -> Optional[dict]:
    key = norm_key(ko_title)
    return next((a for a in data["arcs"] if key and key in a.get("ko", [])), None) if key else None


# --------------------------------------------------------------------------- counters & titles
def _count(data: dict, arc_id: str, below: Optional[int] = None) -> int:
    return sum(1 for k, v in data["assign"].items() if v["arc"] == arc_id and (below is None or int(k) < below))


def n_for(data: dict, arc: dict, number: int) -> int:
    return int(arc.get("base", 0)) + _count(data, arc["id"], below=number) + 1


def make_title(data: dict, arc: dict, number: int) -> str:
    try:
        return data["template"].format(number=number, name=arc["name"], n=n_for(data, arc, number)).strip()
    except (KeyError, IndexError, ValueError):
        return DEFAULT_TEMPLATE.format(number=number, name=arc["name"], n=n_for(data, arc, number))


def assigned_title(pid: str, number: int) -> Optional[str]:
    """Title of a chapter whose arc is already recorded (used when a chapter record is created)."""
    data = load(pid)
    a = data["assign"].get(str(number))
    arc = _arc(data, a["arc"]) if a else None
    return make_title(data, arc, number) if arc else None


def view(pid: str) -> dict:
    data = load(pid)
    arcs = []
    for a in data["arcs"]:
        nums = [int(k) for k, v in data["assign"].items() if v["arc"] == a["id"]]
        arcs.append({**a, "count": len(nums), "last_chapter": max(nums) if nums else None,
                     "last_n": int(a.get("base", 0)) + len(nums)})
    return {"arcs": arcs, "template": data["template"], "assigned": len(data["assign"])}


def update(pid: str, arcs: list[dict], template: Optional[str] = None) -> dict:
    """Replace the arc list (name, Korean titles, big flag, notes) and let `last_n` re-base the counter."""
    data = load(pid)
    old = {a["id"]: a for a in data["arcs"]}
    out, seen = [], set()
    for a in arcs:
        name = (a.get("name") or "").strip()
        if not name:
            raise ArcError("Tên arc không được để trống.")
        ko_raw = [k.strip() for k in (a.get("ko") or []) if k and k.strip()]
        aid = a.get("id") if a.get("id") in old else _new_id()
        if aid in seen:
            raise ArcError(f"Arc trùng: {name}")
        seen.add(aid)
        keys = [norm_key(k) for k in ko_raw if norm_key(k)]
        for other in out:
            clash = set(keys) & set(other["ko"])
            if clash:
                raise ArcError(f"Tên tiếng Hàn “{', '.join(sorted(clash))}” bị trùng giữa “{name}” và “{other['name']}”.")
        arc = {"id": aid, "name": name, "ko": keys, "ko_raw": ko_raw, "big": bool(a.get("big")),
               "base": int(old.get(aid, {}).get("base", 0)), "notes": (a.get("notes") or "").strip()}
        out.append(arc)
        data["arcs"] = out
        if a.get("last_n") is not None:       # "this arc is at (last_n) now" → re-base
            arc["base"] = int(a["last_n"]) - _count(data, aid)
    data["arcs"] = out
    data["assign"] = {k: v for k, v in data["assign"].items() if v["arc"] in seen}
    if template is not None:
        if "{number}" not in template and "{name}" not in template:
            raise ArcError("Mẫu tiêu đề phải chứa {number} hoặc {name}.")
        data["template"] = template.strip() or DEFAULT_TEMPLATE
    save(pid, data)
    return view(pid)


# --------------------------------------------------------------------------- chapter sources
def chapter_ko_title(pid: str, number: int) -> str:
    from .chapter_editor import service
    _, result = service._parsed(pid)
    e = result.chapters.get(number)
    return (e.ko[-1].title if e and e.ko else "") or ""


def _previous_arc(data: dict, number: int) -> Optional[dict]:
    prev = [int(k) for k in data["assign"] if int(k) < number]
    return _arc(data, data["assign"][str(max(prev))]["arc"]) if prev else None


def suggest(pid: str, number: int, *, arc_id: Optional[str] = None, new_name: str = "") -> dict:
    data = load(pid)
    ko_title = chapter_ko_title(pid, number)
    arc, source = None, ""
    if arc_id:
        arc, source = _arc(data, arc_id), "manual"
    if arc is None and (a := data["assign"].get(str(number))):
        arc, source = _arc(data, a["arc"]), "assigned"
    if arc is None and ko_title:
        arc, source = find_arc(data, ko_title), "ko-title"
    pending = None
    if arc is None and ko_title and norm_key(ko_title):
        source = "new"
        pending = {"id": None, "name": (new_name or _clean_ko(ko_title)).strip(), "ko_raw": [_clean_ko(ko_title)],
                   "big": False, "base": 0}
        arc = pending
    if arc is None:
        arc, source = _previous_arc(data, number), "previous"
    out = {"number": number, "ko_title": ko_title, "source": source if arc else "none",
           "arcs": [{"id": a["id"], "name": a["name"], "big": a["big"]} for a in data["arcs"]]}
    if arc is None:
        return {**out, "arc": None, "n": None, "title": None}
    if pending:
        n = 1
        title = data["template"].format(number=number, name=arc["name"], n=n)
    else:
        n, title = n_for(data, arc, number), make_title(data, arc, number)
    return {**out, "arc": {"id": arc["id"], "name": arc["name"], "big": arc["big"]}, "n": n, "title": title}


def _clean_ko(title: str) -> str:
    return _PREFIX.sub("", title or "").strip()


def apply(pid: str, number: int, *, arc_id: Optional[str] = None, new_name: str = "") -> dict:
    """Record the arc of a chapter (creating a small arc when its Korean title is new) and return the title."""
    s = suggest(pid, number, arc_id=arc_id, new_name=new_name)
    if s["arc"] is None:
        raise ArcError("Chưa biết chương này thuộc arc nào — hãy chọn một arc.", code="ARC_UNKNOWN")
    data = load(pid)
    if s["arc"]["id"] is None and (same := find_by_name(data, s["arc"]["name"])):
        arc = same
        if norm_key(s["ko_title"]) not in arc["ko"]:
            arc["ko"].append(norm_key(s["ko_title"])); arc.setdefault("ko_raw", []).append(_clean_ko(s["ko_title"]))
    elif s["arc"]["id"] is None:
        arc = {"id": _new_id(), "name": s["arc"]["name"], "ko": [norm_key(s["ko_title"])], "ko_raw": [_clean_ko(s["ko_title"])],
               "big": False, "base": 0, "notes": ""}
        data["arcs"].append(arc)
    else:
        arc = _arc(data, s["arc"]["id"])
    data["assign"][str(number)] = {"arc": arc["id"], "by": s["source"]}
    save(pid, data)
    return {**s, "arc": {"id": arc["id"], "name": arc["name"], "big": arc["big"]},
            "n": n_for(data, arc, number), "title": make_title(data, arc, number)}


def seed(pid: str) -> dict:
    """Fill arcs/assignments from every Word file of the story: Korean title → arc (small arcs are created and
    named after the Vietnamese title found next to it); no Korean title → the previous chapter's arc. Existing
    assignments are kept."""
    from .chapter_editor import service
    story = store.story_of(pid)
    pids = [d["id"] for d in store.story_projects(story)] if story else [pid]
    rows: dict[int, tuple[str, str]] = {}
    for p in pids:
        try:
            _, result = service._parsed(p)
        except AppError:
            continue
        for n, e in result.chapters.items():
            rows[n] = ((e.ko[-1].title if e.ko else "") or "", (e.vi[-1].title if e.vi else "") or "")
    data = load(pid)
    created = added = by_prev = 0
    prev: Optional[dict] = None
    for n in sorted(rows):
        ko, vi = rows[n]
        arc = find_arc(data, ko) if ko else None
        if arc is None and norm_key(ko):
            arc = find_by_name(data, _clean_ko(vi)) if _clean_ko(vi) else None
            if arc is not None:                     # same arc under another Korean spelling → learn it
                arc["ko"].append(norm_key(ko)); arc.setdefault("ko_raw", []).append(_clean_ko(ko))
            else:
                arc = {"id": _new_id(), "name": _clean_ko(vi) or _clean_ko(ko), "ko": [norm_key(ko)], "ko_raw": [_clean_ko(ko)],
                       "big": False, "base": 0, "notes": ""}
                data["arcs"].append(arc)
                created += 1
        by = "ko-title"
        if arc is None:
            arc, by = (_arc(data, data["assign"][str(n)]["arc"]) if str(n) in data["assign"] else prev), "previous"
        if arc is None:
            continue
        prev = arc
        if str(n) not in data["assign"]:
            data["assign"][str(n)] = {"arc": arc["id"], "by": by}
            added += 1
            by_prev += by == "previous"
    save(pid, data)
    return {**view(pid), "created": created, "added": added, "by_previous": by_prev, "chapters": len(rows)}


NL = chr(10)
NAME_SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False}


def translate_name(pid: str, ko_title: str, model: str) -> str:
    """Ask a translation model for a short Vietnamese title for a new arc (consistent with the glossary)."""
    from ..ai.termbase import _make_client
    from ..editor.glossary import entries_for_text, glossary_prompt
    ko = _clean_ko(ko_title)
    if not ko:
        raise ArcError("Không có tiêu đề tiếng Hàn để dịch.")
    gloss = glossary_prompt(entries_for_text(store.get_glossary(pid), ko))
    client = _make_client(model)
    data, _, _ = client.call(
        system="You name story arcs of a Korean web novel in Vietnamese. Answer with a JSON object {\"name\": \"...\"} only.",
        user=("Arc title (Korean): " + ko + NL * 2 + "Glossary (use these renderings for names/terms):" + NL + (gloss or "(empty)") + NL * 2
              + "Give a short Vietnamese arc title (2-6 words, Title Case, Sino-Vietnamese or the established English name when the "
              "title is a proper noun like a game/place/organisation). No quotes, no chapter number."),
        schema=NAME_SCHEMA, max_tokens=2000)
    return re.sub(r"\s+", " ", str((data or {}).get("name") or "")).strip(" .\"'“”") or ko


def sync_from_titles(pid: str, rows: list[tuple]) -> dict:
    """Published titles are the truth: rows = [(chapter number, arc name, n)] from "2201. Dark Moon (165)".
    Each chapter is assigned to its arc and the arc's counter is re-based on its latest published chapter."""
    from collections import defaultdict
    data = load(pid)
    created = 0
    diffs: dict[str, str] = {}
    by_arc: dict[str, list[tuple]] = defaultdict(list)
    for number, name, n in rows:
        arc = find_by_name(data, name)
        if arc is not None and arc["name"] != name.strip():
            diffs[name.strip()] = arc["name"]
        if arc is None:
            arc = {"id": _new_id(), "name": name.strip(), "ko": [], "ko_raw": [], "big": False, "base": 0, "notes": ""}
            data["arcs"].append(arc)
            created += 1
        data["assign"][str(number)] = {"arc": arc["id"], "by": "wattpad"}
        by_arc[arc["id"]].append((number, n))
    for aid, lst in by_arc.items():
        number, n = max(lst)                       # latest published chapter of this arc
        _arc(data, aid)["base"] = n - 1 - _count(data, aid, below=number)
    save(pid, data)
    return {"chapters": len(rows), "arcs": len(by_arc), "created": created, "name_diffs": diffs}
