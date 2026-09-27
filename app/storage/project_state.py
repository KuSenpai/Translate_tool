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
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


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
            src = (data.get("source") or {}).get("path")
            data = dict(data, status_counts=counts, source_exists=bool(src) and Path(src).exists())
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
        return Path(self.get_project(pid)["source"]["path"])

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

    # --- glossary ----------------------------------------------------------
    def get_glossary(self, pid: str) -> list[dict]:
        self.get_project(pid)
        return _read_json(self.dir(pid) / "glossary.json", [])

    def save_glossary(self, pid: str, entries: list[dict]) -> list[dict]:
        with _lock:
            self.get_project(pid)
            _write_json(self.dir(pid) / "glossary.json", entries)
            return entries


store = ProjectStore()
