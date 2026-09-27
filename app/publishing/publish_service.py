"""Server-side orchestration of Wattpad actions: session state, story list, publish + chapter status.

Status rules:
- Publishing requires confirmation and a REVIEWED / READY_TO_PUBLISH chapter (→ READY_TO_PUBLISH).
- Only a verified successful publish moves the chapter to PUBLISHED (after saving the local DOCX).
- A failure keeps READY_TO_PUBLISH and records the error; if a part was already created, its id is
  kept so a retry updates that part instead of creating a duplicate.
"""
from __future__ import annotations

import importlib.util
import json
import re

from .. import config
from ..editor.chapter_editor import ChapterService, service as chapter_service
from ..editor.chapter_state import Status, transition
from ..errors import StateError
from ..logging_setup import get_logger
from ..storage.project_state import _read_json, _write_json, now_iso
from .extension_bridge import ExtensionBridge
from .jobs import JobManager, jobs as default_jobs

log = get_logger("WATTPAD")
STATE_FILE = config.DATA_DIR / "wattpad_state.json"


def _state() -> dict:
    return _read_json(STATE_FILE, {}) or {}


def _save_state(**fields) -> None:
    _write_json(STATE_FILE, {**_state(), **fields})


def status() -> dict:
    extension_mode = config.WATTPAD_MODE == "extension"
    available = extension_mode or importlib.util.find_spec("playwright") is not None
    st = _state()
    return {
        "mode": "extension" if extension_mode else "playwright",
        "base": config.WATTPAD_BASE_URL.rstrip("/"),
        "extension_connected": publisher.bridge.connected(),
        "extension_last_seen": publisher.bridge.last_seen_iso,
        "available": available,
        "error": None if available else "Chưa cài playwright (pip install playwright).",
        "logged_in_hint": bool(st.get("logged_in_at")) and not st.get("session_expired"),
        "logged_in_at": st.get("logged_in_at"),
        "stories": st.get("stories", []),
        "stories_updated_at": st.get("stories_updated_at"),
        "has_snapshot": (config.LOG_DIR / "wattpad" / "myworks-latest.png").exists(),
    }


STORY_ID_RE = re.compile(r"(?:/(?:myworks|story)/|^)(\d{5,12})(?=\D|$)")


def save_stories_from_extension(stories: list[dict], page_url: str) -> dict:
    """Story list scraped by the extension from My Works in the user's own browser."""
    clean = [{"id": str(s["id"]), "title": str(s.get("title") or f"Truyện #{s['id']}")[:200]}
             for s in stories if str(s.get("id", "")).isdigit()]
    manual = [s for s in _state().get("stories", []) if s.get("manual")]
    found = {s["id"] for s in clean}
    _save_state(stories=clean + [s for s in manual if s["id"] not in found], stories_updated_at=now_iso(),
                logged_in_at=now_iso(), session_expired=False, stories_source=page_url[:300])
    log.info("Stories received from extension: %d", len(clean))
    return {"saved": len(clean)}


def add_manual_story(link: str, title: str = "") -> dict:
    """Add a story from a pasted Wattpad link (…/story/123456789-ten, …/myworks/123456789) or a bare id."""
    link = link.strip()
    m = STORY_ID_RE.search(link)
    if not m:
        raise StateError("Không nhận ra ID truyện trong link. Hãy dán link dạng "
                         "https://www.wattpad.com/story/123456789-ten-truyen hoặc chỉ số ID.", code="BAD_STORY_LINK")
    sid = m.group(1)
    if not title.strip():
        slug = re.search(rf"{sid}-([\w-]+)", link)
        title = slug.group(1).replace("-", " ").strip().title() if slug else f"Truyện #{sid}"
    story = {"id": sid, "title": title.strip(), "manual": True}
    _save_state(stories=[s for s in _state().get("stories", []) if s["id"] != sid] + [story])
    log.info("Story added manually: %s", sid)
    return story


class PublishService:
    def __init__(self, chapters: ChapterService = chapter_service, job_manager: JobManager = default_jobs):
        self.chapters = chapters
        self.jobs = job_manager
        self.bridge = ExtensionBridge(job_manager)

    def login(self) -> dict:
        def done(job, result):
            if result.get("ok"):
                _save_state(logged_in_at=now_iso(), session_expired=False)
        return self.jobs.start("login", {"action": "login", "timeout": config.WATTPAD_LOGIN_TIMEOUT},
                               timeout=config.WATTPAD_LOGIN_TIMEOUT + 60, on_done=done)

    def stories(self) -> dict:
        def done(job, result):
            if result.get("ok"):
                manual = [s for s in _state().get("stories", []) if s.get("manual")]
                found = {s["id"] for s in result["stories"]}
                _save_state(stories=result["stories"] + [s for s in manual if s["id"] not in found],
                            stories_updated_at=now_iso(), has_snapshot=bool(result.get("snapshot") or result.get("screenshot")),
                            logged_in_at=_state().get("logged_in_at") or now_iso(), session_expired=False)
                if result["stories"]:
                    result["message"] = f"Đã tải {len(result['stories'])} truyện."
                else:
                    result["message"] = ("Không tự tìm thấy truyện nào trên trang My Works. Hãy dán link truyện "
                                         "(copy từ thanh địa chỉ khi mở truyện trên Wattpad) vào ô “Thêm truyện bằng link”."
                                         + (f" Ảnh chụp trang: {result['screenshot']}" if result.get("screenshot") else ""))
            elif result.get("error_code") == "WATTPAD_SESSION_EXPIRED":
                _save_state(session_expired=True)
        return self.jobs.start("stories", {"action": "stories"}, timeout=120, on_done=done)

    def publish(self, pid: str, number: int, *, story_id: str, story_title: str, title: str,
                mode: str, confirm: bool) -> dict:
        store = self.chapters.store
        rec = self.chapters._require(pid, number)
        if not confirm:
            raise StateError("Cần tick “I confirm this is the final version” trước khi đăng.", code="CONFIRM_REQUIRED")
        if not title.strip():
            raise StateError("Tiêu đề chương trống.", code="EMPTY_TITLE")
        if not story_id:
            raise StateError("Chưa chọn truyện trên Wattpad.", code="NO_STORY")
        if rec["status"] == Status.REVIEWED.value:
            transition(rec, "ready")
        elif rec["status"] != Status.READY_TO_PUBLISH.value:
            raise StateError(f"Chương đang ở trạng thái {rec['status']}. Cần Preview và đánh dấu 'Đã review' trước khi đăng.",
                             code="INVALID_TRANSITION")
        store.save_chapter(pid, number, rec)
        store.update_project(pid, wattpad={"story_id": story_id, "story_title": story_title})

        wp = rec.get("wattpad") or {}
        part_id = wp.get("part_id") if wp.get("story_id") == story_id else None
        content_hash = json.dumps(rec["draft"], sort_keys=True)
        log.info("Starting publish: project=%s chapter=%d story=%s mode=%s reuse_part=%s",
                 pid, number, story_id, mode, bool(part_id))

        def done(job, result):
            r = self.chapters._require(pid, number)
            entry = {"at": now_iso(), "ok": bool(result.get("ok")), "mode": mode, "story_id": story_id,
                     "story_title": story_title, "title": title, "part_id": result.get("part_id"),
                     "part_url": result.get("part_url"), "error_code": result.get("error_code"),
                     "error": None if result.get("ok") else result.get("message")}
            if result.get("part_id"):
                r["wattpad"] = {"story_id": story_id, "part_id": result["part_id"], "part_url": result.get("part_url")}
            if result.get("ok") and mode == "publish" and result.get("published"):
                if json.dumps(r["draft"], sort_keys=True) != content_hash:
                    log.warning("Draft changed during publish; local DOCX reflects the current draft")
                store.save_chapter(pid, number, r)
                try:
                    path = self.chapters.export(pid, number)
                    entry["docx"] = str(path)
                except Exception as e:  # published remotely: record the export problem, still mark published
                    entry["docx_error"] = str(e)
                r = self.chapters._require(pid, number)
                transition(r, "published")
                result["message"] = "Đã publish lên Wattpad và lưu DOCX." if "docx" in entry else \
                    f"Đã publish lên Wattpad, nhưng lưu DOCX thất bại: {entry['docx_error']}"
            elif result.get("ok"):
                result["message"] = "Đã lưu nháp lên Wattpad (chưa publish)."
            elif result.get("error_code") == "WATTPAD_SESSION_EXPIRED":
                _save_state(session_expired=True)
            r.setdefault("publish_history", []).append(entry)
            store.save_chapter(pid, number, r)
            log.info("Publish %s: chapter=%d %s", "successful" if entry["ok"] else "failed", number,
                     entry.get("error_code") or "")

        if config.WATTPAD_MODE == "extension":
            return self.bridge.create_publish_task(story_id=story_id, story_title=story_title, title=title.strip(),
                                                   blocks=rec["draft"], mode=mode, part_id=part_id, on_done=done)
        return self.jobs.start("publish", {"action": "publish", "story_id": story_id, "title": title.strip(),
                                           "blocks": rec["draft"], "mode": mode, "part_id": part_id},
                               timeout=240, on_done=done)


publisher = PublishService()
