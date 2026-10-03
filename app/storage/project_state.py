"""File-based persistence: projects, chapter drafts/status, glossary, publish history.

Layout:
    data/projects/<project_id>/project.json
    data/projects/<project_id>/source.docx        (copy of an uploaded file; never the user's original)
    data/projects/<project_id>/chapters/<n>.json
    data/projects/<project_id>/glossary.json

A project is keyed by the book's file name, so re-uploading a newer version of the same
book (e.g. with more chapters) keeps drafts, statuses and the glossary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .. import config
from ..errors import NotFound

_lock = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name.replace("đ", "d").replace("Đ", "D"))
    s = s.encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    if not s:  # e.g. a purely Korean file name
        s = "book-" + hashlib.sha1(name.encode()).hexdigest()[:8]
    return s[:60]


def content_hash(obj: Any) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _read_json(path: Path, default: Any = None) -> Any:
    for attempt in range(10):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except PermissionError:   # Windows: the file is being replaced by another thread right now
            if attempt == 9:
                raise
            time.sleep(0.05)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:   # Windows refuses to replace a file another thread is reading
            if attempt == 19:
                Path(tmp).unlink(missing_ok=True)
                raise
            time.sleep(0.05)


class ProjectStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or config.PROJECTS_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    # --- projects ---------------------------------------------------------
    def dir(self, pid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9\-]{1,64}", pid or ""):
            raise NotFound("Project id không hợp lệ.")
        return self.root / pid

    def get_project(self, pid: str) -> dict:
        data = _read_json(self.dir(pid) / "project.json")
        if data is None:
            raise NotFound(f"Không tìm thấy project '{pid}'. Hãy mở lại file Word.", code="PROJECT_NOT_FOUND")
        return data

    def list_projects(self) -> list[dict]:
        """Library: every opened book with its progress (status counts per chapter)."""
        out = []
        for p in self.root.glob("*/project.json"):
            data = _read_json(p)
            if not data:
                continue
            counts: dict[str, int] = {}
            for st in self.chapter_statuses(data["id"]).values():
                if st.get("status"):
                    counts[st["status"]] = counts.get(st["status"], 0) + 1
            try:
                src = self.source_path(data["id"])
            except (KeyError, TypeError, NotFound):
                src = None
            if src is not None and (data.get("source") or {}).get("kind") == "upload":
                data["source"] = dict(data["source"], path=str(src))
            data = dict(data, status_counts=counts, source_exists=bool(src) and src.exists())
            out.append(data)
        return sorted(out, key=lambda d: d.get("last_opened_at") or d.get("updated_at", ""), reverse=True)

    def upsert_project(self, name: str, *, source_path: Optional[str] = None,
                       uploaded_bytes: Optional[bytes] = None) -> dict:
        pid = slugify(Path(name).stem)
        with _lock:
            d = self.root / pid
            d.mkdir(parents=True, exist_ok=True)
            data = _read_json(d / "project.json") or {"id": pid, "created_at": now_iso(), "wattpad": {}}
            data["name"] = Path(name).name
            if uploaded_bytes is not None:
                (d / "source.docx").write_bytes(uploaded_bytes)
                data["source"] = {"kind": "upload", "path": str(d / "source.docx")}
            elif source_path:
                data["source"] = {"kind": "path", "path": str(Path(source_path).resolve())}
            data["updated_at"] = now_iso()
            _write_json(d / "project.json", data)
            return data

    def update_project(self, pid: str, **fields) -> dict:
        with _lock:
            data = self.get_project(pid)
            data.update(fields)
            data["updated_at"] = now_iso()
            _write_json(self.dir(pid) / "project.json", data)
            return data

    def source_path(self, pid: str) -> Path:
        src = self.get_project(pid)["source"]
        if src.get("kind") == "upload":
            # the uploaded copy lives in the project folder; don't trust the stored absolute path
            # (it breaks when the tool folder is moved or renamed)
            return self.dir(pid) / "source.docx"
        return Path(src["path"])

    # --- chapters -----------------------------------------------------------
    def _chapter_path(self, pid: str, number: int) -> Path:
        return self.dir(pid) / "chapters" / f"{int(number)}.json"

    def get_chapter(self, pid: str, number: int) -> Optional[dict]:
        return _read_json(self._chapter_path(pid, number))

    def save_chapter(self, pid: str, number: int, data: dict) -> dict:
        with _lock:
            data["updated_at"] = now_iso()
            _write_json(self._chapter_path(pid, number), data)
            return data

    def chapter_statuses(self, pid: str) -> dict[int, dict]:
        out = {}
        for p in (self.dir(pid) / "chapters").glob("*.json"):
            data = _read_json(p) or {}
            out[int(p.stem)] = {"status": data.get("status"), "updated_at": data.get("updated_at")}
        return out

    # --- stories: several files (projects) of the same novel share one termbase -------
    @property
    def stories_root(self) -> Path:
        return self.root.parent / "stories"

    def story_dir(self, story: str) -> Path:
        if not re.fullmatch(r"[a-z0-9\-]{1,64}", story or ""):
            raise NotFound("Tên truyện không hợp lệ.")
        return self.stories_root / story

    def story_of(self, pid: str) -> Optional[str]:
        return self.get_project(pid).get("story") or None

    def story_projects(self, story: str) -> list[dict]:
        out = [d for d in (_read_json(p) for p in self.root.glob("*/project.json")) if d and d.get("story") == story]
        return sorted(out, key=lambda d: (d.get("chapter_range") or [10 ** 9])[0])

    def list_stories(self) -> list[dict]:
        out = []
        for f in self.stories_root.glob("*/story.json"):
            s = _read_json(f) or {}
            s["projects"] = [{"id": d["id"], "name": d["name"], "chapter_range": d.get("chapter_range")}
                             for d in self.story_projects(f.parent.name)]
            out.append(s)
        return out

    def set_story(self, pid: str, story_name: str) -> dict:
        """Attach a project to a story; its own glossary and notes are merged into the shared ones."""
        story = slugify(story_name)
        with _lock:
            d = self.story_dir(story)
            d.mkdir(parents=True, exist_ok=True)
            meta = _read_json(d / "story.json") or {"id": story, "name": story_name.strip(), "created_at": now_iso(),
                                                    "notes": ""}
            project = self.get_project(pid)
            own = _read_json(self.dir(pid) / "glossary.json", []) or []
            shared = _read_json(d / "glossary.json", []) or []
            known = {g["source"] for g in shared}
            shared += [g for g in own if g["source"] not in known]
            _write_json(d / "glossary.json", shared)
            if project.get("story_notes") and project["story_notes"] not in meta.get("notes", ""):
                meta["notes"] = (meta.get("notes", "") + "\n\n" + project["story_notes"]).strip()
            _write_json(d / "story.json", meta)
            return self.update_project(pid, story=story)

    def story_meta(self, story: str) -> dict:
        return _read_json(self.story_dir(story) / "story.json", {}) or {}

    def update_story(self, story: str, **fields) -> dict:
        with _lock:
            meta = self.story_meta(story)
            meta.update(fields)
            self.story_dir(story).mkdir(parents=True, exist_ok=True)
            _write_json(self.story_dir(story) / "story.json", meta)
            return meta

    # --- glossary & notes (shared by the story when the project belongs to one) --------
    def _glossary_file(self, pid: str) -> Path:
        story = self.story_of(pid)
        return self.story_dir(story) / "glossary.json" if story else self.dir(pid) / "glossary.json"

    def get_glossary(self, pid: str) -> list[dict]:
        return _read_json(self._glossary_file(pid), []) or []

    def save_glossary(self, pid: str, entries: list[dict]) -> list[dict]:
        with _lock:
            f = self._glossary_file(pid)
            f.parent.mkdir(parents=True, exist_ok=True)
            _write_json(f, entries)
            return entries

    def get_notes(self, pid: str) -> str:
        story = self.story_of(pid)
        return self.story_meta(story).get("notes", "") if story else self.get_project(pid).get("story_notes", "")

    def set_notes(self, pid: str, notes: str) -> str:
        story = self.story_of(pid)
        if story:
            self.update_story(story, notes=notes)
        else:
            self.update_project(pid, story_notes=notes)
        return notes


store = ProjectStore()
