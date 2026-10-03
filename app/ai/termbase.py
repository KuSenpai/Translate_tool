"""Termbase for a story: keep fixed terms (character names, skills/techniques, places, items, titles…)
consistent across chapters.

Sources of terms
- the user's own data (glossary file or pasted text: "김수현 = Kim Soo-hyun"; other lines become story notes)
- an AI scan of already-translated chapters: Claude reads Korean + existing Vietnamese chapters and
  reports each fixed term with the rendering that was actually used (and any inconsistent variants)
- terms Claude reported while translating new chapters

Checks (free, local): for every entry, in how many chapters the Korean term appears, how many of
those use the chosen Vietnamese rendering, and which chapters deviate.

Everything ends up in the project's glossary (data/projects/<pid>/glossary.json), which the editor,
the AI correction and the AI translation already use.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from ..editor.chapter_editor import service as chapter_service
from ..editor.glossary import CATEGORIES, GlossaryEntry
from ..errors import AppError, NotFound
from ..logging_setup import get_logger
from ..storage.project_state import _read_json, _write_json, now_iso, store
from .llm_service import LLMAuthError, LLMError, LLMNotConfigured, LLMRateLimit, LLMTimeout
from .novel_translator import MODELS, ClaudeJSON, LLMRefused, cost_usd

log = get_logger("TERMS")
_HANGUL = re.compile(r"[가-힣]")
NOTES_MAX = 8000


class TermError(AppError):
    code = "TERMBASE_ERROR"


# --------------------------------------------------------------------------- chapters
def _project_chapters(pid: str) -> list[dict]:
    blocks, result = chapter_service._parsed(pid)
    out = []
    for n in sorted(result.chapters):
        e = result.chapters[n]
        ko = e.ko[-1] if e.ko else None          # a chapter pasted twice: the later copy is the redo
        vi = e.vi[-1] if e.vi else None
        out.append({"number": n, "project": pid,
                    "ko": "\n".join(blocks[j].text for j in range(ko.start, ko.end)) if ko else "",
                    "vi": "\n".join(blocks[j].text for j in range(vi.start, vi.end)) if vi else ""})
    return out


def chapter_texts(pid: str) -> list[dict]:
    """Korean + Vietnamese text of every chapter: of all files of the story when the project belongs to one."""
    story = store.story_of(pid)
    pids = [d["id"] for d in store.story_projects(story)] if story else [pid]
    seen: dict[int, dict] = {}
    for p in pids:
        try:
            chapters = _project_chapters(p)
        except AppError as e:                  # a member file was moved or deleted: skip it
            log.warning("Skipping %s: %s", p, e.message)
            continue
        for c in chapters:
            if c["number"] not in seen or (not seen[c["number"]]["vi"] and c["vi"]):
                seen[c["number"]] = c
    return [seen[n] for n in sorted(seen)]


# --------------------------------------------------------------------------- user data import
_STRONG_SEPS = ["\t", "→", "->", "=>", "=", "|"]
_WEAK_SEPS = [":", ","]  # also used in prose ("김수현: nhân vật chính, 25 tuổi") → only for short, plain targets


def parse_data(text: str, filename: str = "") -> tuple[list[dict], list[str]]:
    """Glossary lines become entries; everything else becomes story notes."""
    text = text.lstrip("﻿")
    if filename.lower().endswith(".json") or text.strip().startswith(("[", "{")):
        try:
            data = json.loads(text)
            items = data.items() if isinstance(data, dict) else [(d.get("source") or d.get("ko") or d.get("korean"),
                                                                  d) for d in data]
            entries = []
            for src, val in items:
                if isinstance(val, dict):
                    tgt = val.get("target") or val.get("vi") or val.get("vietnamese")
                    entries.append({"source": str(src or "").strip(), "target": str(tgt or "").strip(),
                                    "category": val.get("category"), "note": str(val.get("note") or "")})
                else:
                    entries.append({"source": str(src).strip(), "target": str(val).strip()})
            return [e for e in entries if e["source"] and e["target"]], []
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    entries, notes = [], []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-•*").strip()
        if not line:
            if notes and notes[-1] != "":
                notes.append("")
            continue
        entry = None
        for sep in _STRONG_SEPS + _WEAK_SEPS:
            if sep not in line:
                continue
            left, right = (x.strip() for x in line.split(sep, 1))
            # a glossary line: short Korean source (or a tab/arrow separated pair)
            ok = bool(left and right and len(left) <= 40 and (_HANGUL.search(left) or sep in ("\t", "→", "->", "=>")))
            if ok and sep in _WEAK_SEPS and (len(right) > 30 or re.search(r"[,.;!?]", right)):
                ok = False
            if ok:
                note = ""
                m = re.match(r"^(.*?)\s*[(（](.+)[)）]\s*$", right)
                if m and m.group(1):
                    right, note = m.group(1).strip(), m.group(2).strip()
                entry = {"source": left, "target": right, "note": note}
            break
        if entry and len(entry["target"]) <= 80:
            entries.append(entry)
        else:
            notes.append(line)
    return entries, notes


def import_data(pid: str, text: str, filename: str = "", overwrite: bool = True) -> dict:
    entries, notes = parse_data(text, filename)
    glossary = store.get_glossary(pid)
    by_src = {g["source"]: g for g in glossary}
    added = updated = 0
    for e in entries:
        cat = e.get("category") if e.get("category") in CATEGORIES else None
        if e["source"] in by_src:
            g = by_src[e["source"]]
            if overwrite and g["target"] != e["target"]:
                if g["target"] not in g.get("avoid", []):
                    g.setdefault("avoid", []).append(g["target"])
                g["target"], g["origin"] = e["target"], "data"
                updated += 1
            if e.get("note") and not g.get("note"):
                g["note"] = e["note"]
            g["category"] = g.get("category") or cat
            if e["target"] in g.get("avoid", []):
                g["avoid"].remove(e["target"])
        else:
            g = GlossaryEntry(source=e["source"], target=e["target"], note=e.get("note") or "", category=cat,
                              origin="data").model_dump()
            glossary.append(g)
            by_src[g["source"]] = g
            added += 1
    store.save_glossary(pid, glossary)
    if notes:
        cur = store.get_notes(pid)
        joined = "\n".join(notes).strip()
        if joined and joined not in cur:
            store.set_notes(pid, (cur + "\n\n" + joined).strip()[:NOTES_MAX])
    log.info("Imported data into %s: +%d, updated %d, %d note lines", pid, added, updated, len([n for n in notes if n]))
    return {"added": added, "updated": updated, "notes_lines": len([n for n in notes if n])}


def set_notes(pid: str, notes: str) -> str:
    return store.set_notes(pid, notes.strip()[:NOTES_MAX])


# --------------------------------------------------------------------------- consistency check (local, free)
def check_consistency(pid: str) -> dict:
    chapters = [c for c in chapter_texts(pid) if c["ko"] and c["vi"]]
    vi_low = [c["vi"].lower() for c in chapters]
    rows = []
    for g in store.get_glossary(pid):
        src, tgt = g["source"], g["target"].lower()
        korean = bool(_HANGUL.search(src))
        if korean:
            hits = [i for i, c in enumerate(chapters) if src in c["ko"]]
        else:  # a Vietnamese "wrong rendering" entry: where does it still appear?
            hits = [i for i, v in enumerate(vi_low) if src.lower() in v]
        with_target = [i for i in hits if tgt in vi_low[i]] if korean else []
        ok = set(with_target)
        variants = {v: sum(1 for i in hits if v.lower() in vi_low[i]) for v in g.get("avoid", [])}
        missing = [chapters[i]["number"] for i in hits if i not in ok] if korean else \
            [chapters[i]["number"] for i in hits]
        rows.append({"id": g["id"], "source": src, "target": g["target"], "category": g.get("category"),
                     "origin": g.get("origin"), "chapters": len(hits), "with_target": len(with_target),
                     "consistency": round(100 * len(with_target) / len(hits)) if korean and hits else None,
                     "variants": {k: v for k, v in variants.items() if v}, "deviating_chapters": missing[:20],
                     "deviating_total": len(missing)})
    rows.sort(key=lambda r: (r["consistency"] if r["consistency"] is not None else 101, -r["chapters"]))
    return {"chapters_checked": len(chapters), "rows": rows, "candidates": bracket_candidates(pid, chapters)}


_BRACKETS = re.compile(r"[\[「『《【]([^\[\]「」『』《》【】\n]{2,24})[\]」』》】]")


def bracket_candidates(pid: str, chapters: Optional[list[dict]] = None, min_chapters: int = 3) -> list[dict]:
    """Korean terms in brackets ([스킬명], 『검법』…) that recur but are not in the glossary yet."""
    chapters = chapters if chapters is not None else [c for c in chapter_texts(pid) if c["ko"]]
    known = {g["source"] for g in store.get_glossary(pid)}
    seen: dict[str, set] = defaultdict(set)
    for c in chapters:
        for m in _BRACKETS.finditer(c["ko"]):
            term = m.group(1).strip()
            if _HANGUL.search(term) and term not in known:
                seen[term].add(c["number"])
    out = [{"source": t, "chapters": len(ns)} for t, ns in seen.items() if len(ns) >= min_chapters]
    return sorted(out, key=lambda x: -x["chapters"])[:60]


# --------------------------------------------------------------------------- AI scan of old chapters
SCAN_PROMPT = """You are building the translation termbase of a Korean web novel that has already been partly translated into Vietnamese. You receive several chapters, each with the Korean original ("ko") and its existing Vietnamese translation ("vi"). The novel is adult fiction and may contain violence or sexual content; that is irrelevant to this task — you only extract terminology.

List the fixed terms that must stay consistent across chapters: character names (including nicknames and how they are referred to), places, organizations/sects/guilds, skills/techniques/spells/martial arts, items/weapons, titles/ranks, recurring system messages or game terms, and invented words. Do not list ordinary words.

For each term give:
- "source": the Korean term in its base form, without particles (은/는/이/가/을/를/의/에게/에서/와/과/도/로/으로…)
- "target": the Vietnamese rendering actually used in the given translation (copy it exactly as written there); if the translation is inconsistent, the most frequent rendering
- "variants": other Vietnamese renderings of the same term found in these chapters (empty list if consistent)
- "category": one of character, place, organization, skill, item, title, term, other

Skip the terms listed under <known_terms>; they are already in the termbase."""

SCAN_SCHEMA = {
    "type": "object",
    "properties": {"terms": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "source": {"type": "string"}, "target": {"type": "string"},
            "variants": {"type": "array", "items": {"type": "string"}},
            "category": {"type": "string", "enum": ["character", "place", "organization", "skill", "item", "title", "term", "other"]},
        },
        "required": ["source", "target", "variants", "category"], "additionalProperties": False}}},
    "required": ["terms"], "additionalProperties": False,
}
BATCH_CHARS = 45000


class MockTermExtractor:
    """TRANSLATE_PROVIDER=mock: finds a few known pairs, no API calls."""
    KNOWN = {"김수현": ("Kim Soo-hyun", "character"), "선배": ("tiền bối", "title"), "다크 문": ("Trăng Rằm Đen", "term")}

    def __init__(self, model: str, effort: str = "low"):
        self.model = model

    def call(self, *, system: str, user: str, schema: dict, **_) -> tuple[dict, dict, str]:
        terms = [{"source": k, "target": v, "variants": [], "category": c}
                 for k, (v, c) in self.KNOWN.items() if k in user and k not in user.split("</known_terms>")[0]]
        return {"terms": terms}, {"input_tokens": 1000, "output_tokens": 100}, "mock"


def _make_client(model: str):
    import os
    if os.getenv("TRANSLATE_PROVIDER", "anthropic").strip().lower() == "mock":
        return MockTermExtractor(model)
    if MODELS.get(model, {}).get("provider") == "antigravity":
        from .antigravity import AntigravityJSON
        return AntigravityJSON(model, effort="low")
    if MODELS.get(model, {}).get("subscription"):
        from .claude_code import ClaudeCodeJSON
        return ClaudeCodeJSON(model, effort="low")
    return ClaudeJSON(model, effort="low")


def _batches(chapters: list[dict]) -> list[list[dict]]:
    out, cur, size = [], [], 0
    for c in chapters:
        n = len(c["ko"]) + len(c["vi"])
        if cur and size + n > BATCH_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += n
    if cur:
        out.append(cur)
    return out


def scan_estimate(pid: str, from_number: Optional[int], to_number: Optional[int]) -> dict:
    chs = _scan_chapters(pid, from_number, to_number)
    ko = sum(len(c["ko"]) for c in chs)
    vi = sum(len(c["vi"]) for c in chs)
    nb = len(_batches(chs))
    tin, tout = int(ko * 1.0 + vi * 0.5 + nb * 1500), nb * 2500
    return {"chapters": len(chs), "batches": nb, "estimate": {m: round(cost_usd(m, {"input_tokens": tin, "output_tokens": tout}), 2)
                                                              for m in MODELS}}


def _scan_chapters(pid: str, from_number: Optional[int], to_number: Optional[int]) -> list[dict]:
    return [c for c in chapter_texts(pid) if c["ko"] and c["vi"]
            and (from_number is None or c["number"] >= from_number) and (to_number is None or c["number"] <= to_number)]


class TermScanner:
    def __init__(self):
        self._threads: dict[str, threading.Thread] = {}
        self._stop: dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    def _state_path(self, pid: str) -> Path:
        return store.dir(pid) / "term_scan.json"

    def _proposals_path(self, pid: str) -> Path:
        return store.dir(pid) / "term_proposals.json"

    def state(self, pid: str) -> dict:
        st = _read_json(self._state_path(pid), {}) or {}
        t = self._threads.get(pid)
        st["running"] = bool(t and t.is_alive())
        if st.get("status") == "running" and not st["running"]:
            st["status"], st["message"] = "stopped", "Bị dừng (tool đã khởi động lại)."
        return st

    def proposals(self, pid: str) -> list[dict]:
        return _read_json(self._proposals_path(pid), []) or []

    def start(self, pid: str, from_number: Optional[int], to_number: Optional[int], model: str) -> dict:
        with self._lock:
            if self.state(pid)["running"]:
                raise TermError("Đang quét rồi — đợi xong hoặc bấm Dừng.", code="SCAN_RUNNING")
            if model not in MODELS:
                raise TermError(f"Model không hỗ trợ: {model}", code="BAD_MODEL")
            client = _make_client(model)  # fails early when the API key is missing
            chapters = _scan_chapters(pid, from_number, to_number)
            if not chapters:
                raise TermError("Không có chương song ngữ (có cả bản Hàn và bản Việt) trong khoảng đã chọn.",
                                code="NOTHING_TO_SCAN")
            batches = _batches(chapters)
            st = {"status": "running", "from": chapters[0]["number"], "to": chapters[-1]["number"], "model": model,
                  "chapters": len(chapters), "batches_total": len(batches), "batches_done": 0, "cost_usd": 0.0,
                  "usage": {}, "message": "Đang quét…", "started_at": now_iso(), "errors": []}
            _write_json(self._state_path(pid), st)
            stop = threading.Event()
            self._stop[pid] = stop
            t = threading.Thread(target=self._run, args=(pid, client, batches, stop), daemon=True)
            self._threads[pid] = t
            t.start()
        log.info("Scan started for %s: %d chapters in %d requests (%s)", pid, len(chapters), len(batches), model)
        return self.state(pid)

    def cancel(self, pid: str) -> dict:
        if pid in self._stop:
            self._stop[pid].set()
        return self.state(pid)

    def _run(self, pid: str, client, batches: list[list[dict]], stop: threading.Event) -> None:
        try:
            self._run_inner(pid, client, batches, stop)
        except Exception as e:
            log.exception("Scan crashed: %s", e)
            self._update(pid, status="error", message=f"Lỗi không mong muốn: {e}")

    def _update(self, pid: str, **fields) -> dict:
        with self._lock:
            st = _read_json(self._state_path(pid), {}) or {}
            st.update(fields)
            _write_json(self._state_path(pid), st)
            return st

    def _run_inner(self, pid: str, client, batches: list[list[dict]], stop: threading.Event) -> None:
        found: dict[str, dict] = {}
        for k, batch in enumerate(batches):
            if stop.is_set():
                break
            known = sorted({g["source"] for g in store.get_glossary(pid)} | set(found))
            user = ("<known_terms>\n" + "\n".join(known[:1500]) + "\n</known_terms>\n\n<chapters>\n"
                    + json.dumps([{"number": c["number"], "ko": c["ko"], "vi": c["vi"]} for c in batch], ensure_ascii=False)
                    + "\n</chapters>")
            data, usage, err = None, {}, None
            for attempt in range(3):
                try:
                    data, usage, _ = client.call(system=SCAN_PROMPT, user=user, schema=SCAN_SCHEMA, max_tokens=32000,
                                                 refusal_message="Claude từ chối đọc nhóm chương này")
                    break
                except (LLMRateLimit, LLMTimeout) as e:
                    err = e.message
                    if stop.wait(20 * (attempt + 1)):
                        break
                except (LLMAuthError, LLMNotConfigured) as e:
                    self._update(pid, status="error", message=e.message)
                    return
                except LLMError as e:
                    if e.code == "AI_USAGE_LIMIT":   # subscription window used up: stop, keep what was found
                        self._update(pid, status="stopped", message=f"{e.message} — quét lại sau khi gói được làm mới.")
                        return
                    err, usage = e.message, (e.details or {}).get("usage", {})   # refusal / bad output:
                    break                                                         # skip this batch, keep going
            st = _read_json(self._state_path(pid), {}) or {}
            for key, v in usage.items():
                st.setdefault("usage", {})[key] = st.get("usage", {}).get(key, 0) + v
            st["cost_usd"] = round(st.get("cost_usd", 0) + cost_usd(st["model"], usage), 4) if st.get("model") in MODELS else 0
            st["batches_done"] = k + 1
            nums = [c["number"] for c in batch]
            if data is None:
                st.setdefault("errors", []).append(f"Chương {nums[0]}–{nums[-1]}: {err}")
            else:
                for t in data.get("terms", []):
                    src, tgt = t.get("source", "").strip(), t.get("target", "").strip()
                    if not src or not tgt or not _HANGUL.search(src):
                        continue
                    f = found.setdefault(src, {"source": src, "votes": Counter(), "variants": set(),
                                               "categories": Counter(), "chapters": []})
                    f["votes"][tgt] += len(batch)
                    f["variants"].update(v.strip() for v in t.get("variants", []) if v.strip() and v.strip() != tgt)
                    f["categories"][t.get("category") or "other"] += 1
                    f["chapters"].extend(nums)
            st["message"] = f"Đã quét {k + 1}/{len(batches)} nhóm chương — tìm thấy {len(found)} thuật ngữ mới."
            _write_json(self._state_path(pid), st)
            self._save_proposals(pid, found)
        status = "cancelled" if stop.is_set() else "done"
        self._update(pid, status=status, finished_at=now_iso(),
                     message=f"{'Đã dừng' if stop.is_set() else 'Xong'} — {len(found)} thuật ngữ đề xuất, hãy duyệt bên dưới.")
        log.info("Scan %s for %s: %d terms", status, pid, len(found))

    def _save_proposals(self, pid: str, found: dict[str, dict]) -> None:
        existing = {p["source"]: p for p in self.proposals(pid)}
        for src, f in found.items():
            target, _ = f["votes"].most_common(1)[0]
            variants = sorted((set(f["votes"]) | f["variants"]) - {target})
            prev = existing.get(src)
            if prev and prev.get("status") in ("accepted", "rejected"):
                continue
            existing[src] = {"source": src, "target": target, "variants": variants,
                             "category": f["categories"].most_common(1)[0][0], "chapters": sorted(set(f["chapters"]))[:50],
                             "status": "pending", "origin": "ai-scan"}
        _write_json(self._proposals_path(pid), list(existing.values()))

    # ---- review
    def add_proposals(self, pid: str, terms: list[dict], origin: str) -> int:
        """Terms from elsewhere (e.g. reported while translating) to review before they join the glossary."""
        existing = {p["source"]: p for p in self.proposals(pid)}
        known = {g["source"] for g in store.get_glossary(pid)}
        n = 0
        for t in terms:
            src, tgt = t["source"].strip(), t["target"].strip()
            if src and tgt and src not in known and src not in existing:
                existing[src] = {"source": src, "target": tgt, "variants": [], "category": t.get("category") or "other",
                                 "chapters": [], "status": "pending", "origin": origin}
                n += 1
        _write_json(self._proposals_path(pid), list(existing.values()))
        return n

    def decide(self, pid: str, accept: list[dict], reject: list[str]) -> dict:
        props = {p["source"]: p for p in self.proposals(pid)}
        glossary = store.get_glossary(pid)
        by_src = {g["source"]: g for g in glossary}
        added = 0
        for a in accept:
            p = props.get(a["source"])
            if not p:
                continue
            target = (a.get("target") or p["target"]).strip()
            avoid = [v for v in p.get("variants", []) if v != target]
            if p["source"] in by_src:
                g = by_src[p["source"]]
                g["target"] = target
                g["avoid"] = sorted(set(g.get("avoid", [])) | set(avoid))
            else:
                glossary.append(GlossaryEntry(source=p["source"], target=target, avoid=avoid,
                                              category=a.get("category") or p.get("category"),
                                              origin=p.get("origin") or "ai-scan").model_dump())
                added += 1
            p["status"], p["target"] = "accepted", target
        for src in reject:
            if src in props:
                props[src]["status"] = "rejected"
        store.save_glossary(pid, glossary)
        _write_json(self._proposals_path(pid), list(props.values()))
        return {"added": added}


scanner = TermScanner()


def overview(pid: str) -> dict:
    project = store.get_project(pid)
    story = store.story_of(pid)
    members = [{"id": d["id"], "name": d["name"], "chapter_range": d.get("chapter_range")}
               for d in store.story_projects(story)] if story else []
    return {"project": {"id": pid, "name": project["name"]}, "notes": store.get_notes(pid),
            "story": {"id": story, "name": store.story_meta(story).get("name", story), "projects": members}
            if story else None,
            "glossary": store.get_glossary(pid), "scan": scanner.state(pid),
            "proposals": [p for p in scanner.proposals(pid) if p.get("status") == "pending"],
            "categories": CATEGORIES}
