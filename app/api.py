"""HTTP API. Thin layer: validation + delegation to services."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import config
from .ai.correction_service import ai_status, suggest_correction
from .document.models import Block
from .editor.chapter_editor import service
from .editor.glossary import GlossaryEntry
from .editor.validation import validate_translation
from .errors import NotFound
from .logging_setup import get_logger
from .publishing import publish_service
from .publishing.jobs import jobs
from .storage.project_state import store

router = APIRouter(prefix="/api")
log = get_logger("API")

MAX_UPLOAD = 100 * 1024 * 1024


class OpenPath(BaseModel):
    path: str


class LoadReq(BaseModel):
    ko_choice: int = 0
    vi_choice: int = 0


class DraftReq(BaseModel):
    blocks: list[Block]
    title: Optional[str] = None


class StatusReq(BaseModel):
    event: str = Field(pattern="^(review|ready|unready)$")
    confirm: bool = False


# --- projects -----------------------------------------------------------------
@router.get("/projects")
def list_projects():
    return store.list_projects()


@router.post("/projects/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        from .errors import DocxError
        raise DocxError("File quá lớn (>100MB).", code="DOCX_TOO_LARGE")
    project = service.upload(file.filename or "book.docx", data)
    return service.index(project["id"])


@router.post("/projects/open")
def open_path(req: OpenPath):
    project = service.open_path(req.path)
    return service.index(project["id"])


@router.get("/projects/{pid}")
def project_index(pid: str):
    return service.index(pid)


# --- chapters -----------------------------------------------------------------
@router.post("/projects/{pid}/chapters/{number}/load")
def load_chapter(pid: str, number: int, req: LoadReq | None = None):
    req = req or LoadReq()
    return service.load(pid, number, req.ko_choice, req.vi_choice)


@router.get("/projects/{pid}/chapters/{number}")
def get_chapter(pid: str, number: int):
    return service.get(pid, number)


@router.put("/projects/{pid}/chapters/{number}/draft")
def save_draft(pid: str, number: int, req: DraftReq):
    return service.save_draft(pid, number, req.blocks, req.title)


@router.post("/projects/{pid}/chapters/{number}/reset")
def reset_chapter(pid: str, number: int):
    return service.reset(pid, number)


@router.post("/projects/{pid}/chapters/{number}/status")
def set_status(pid: str, number: int, req: StatusReq):
    return service.set_status(pid, number, req.event, req.confirm)


@router.post("/projects/{pid}/chapters/{number}/export")
def export_chapter(pid: str, number: int):
    path = service.export(pid, number)
    return {"path": str(path), "filename": path.name, "download": f"/api/projects/{pid}/chapters/{number}/docx"}


@router.get("/projects/{pid}/chapters/{number}/docx")
def download_docx(pid: str, number: int):
    rec = store.get_chapter(pid, number)
    if not rec or not rec.get("exports"):
        raise NotFound("Chưa export chương này.")
    path = rec["exports"][-1]["path"]
    return FileResponse(path, filename=f"Chapter_{number}.docx",
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


class ValidateReq(BaseModel):
    blocks: list[Block]


@router.post("/projects/{pid}/chapters/{number}/validate")
def validate(pid: str, number: int, req: ValidateReq):
    rec = service.get(pid, number)
    return validate_translation(req.blocks, [Block.model_validate(b) for b in rec.get("ko_blocks", [])],
                                store.get_glossary(pid))


# --- AI -----------------------------------------------------------------------
class SuggestReq(BaseModel):
    selected: str = Field(min_length=1, max_length=4000)
    paragraph_index: int = -1
    context_before: list[str] = Field(default_factory=list, max_length=5)
    context_after: list[str] = Field(default_factory=list, max_length=5)
    instruction: str = Field("", max_length=500)


@router.get("/ai/status")
def ai_status_route():
    return ai_status()


@router.post("/projects/{pid}/chapters/{number}/suggest")
def suggest(pid: str, number: int, req: SuggestReq):
    rec = store.get_chapter(pid, number)
    if rec is None:
        raise NotFound(f"Chương {number} chưa được load.")
    return suggest_correction(chapter=rec, glossary=store.get_glossary(pid), selected=req.selected,
                              context_before=req.context_before, context_after=req.context_after,
                              instruction=req.instruction)


# --- Wattpad ------------------------------------------------------------------
class PublishReq(BaseModel):
    story_id: str = Field(min_length=1, max_length=40, pattern=r"^\d+$")
    story_title: str = ""
    title: str = Field(min_length=1, max_length=200)
    mode: str = Field("publish", pattern="^(publish|draft)$")
    confirm: bool = False


@router.get("/wattpad/status")
def wattpad_status():
    return publish_service.status()


@router.get("/wattpad/myworks.png")
def wattpad_myworks_snapshot():
    path = config.LOG_DIR / "wattpad" / "myworks-latest.png"
    if not path.exists():
        raise NotFound("Chưa có ảnh chụp My Works.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/wattpad/login")
def wattpad_login():
    return publish_service.publisher.login()


@router.post("/wattpad/stories")
def wattpad_stories():
    return publish_service.publisher.stories()


class ManualStoryReq(BaseModel):
    link: str = Field(min_length=1, max_length=500)
    title: str = Field("", max_length=200)


@router.post("/wattpad/stories/manual")
def wattpad_add_story(req: ManualStoryReq):
    return publish_service.add_manual_story(req.link, req.title)


@router.post("/projects/{pid}/chapters/{number}/publish")
def publish_chapter(pid: str, number: int, req: PublishReq):
    return publish_service.publisher.publish(pid, number, story_id=req.story_id, story_title=req.story_title,
                                             title=req.title, mode=req.mode, confirm=req.confirm)


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    return jobs.get(job_id)


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: str):
    publish_service.publisher.bridge.cancel(job_id)
    return jobs.get(job_id)


# --- browser extension bridge (see app/publishing/extension_bridge.py) ------------
def require_extension(request: Request) -> None:
    origin = request.headers.get("origin", "")
    if request.headers.get("x-nt-extension") != "1" or origin.startswith(("http://", "https://")):
        from .publishing.extension_bridge import ExtensionAuthError
        raise ExtensionAuthError("Chỉ extension Novel Translator mới được gọi API này.")


ext = APIRouter(prefix="/api/ext", dependencies=[Depends(require_extension)])


class ExtEvent(BaseModel):
    stage: Optional[str] = Field(None, max_length=40)
    part_id: Optional[str] = Field(None, pattern=r"^\d{1,15}$")
    message: Optional[str] = Field(None, max_length=1000)
    final: bool = False
    ok: bool = False
    published: bool = False
    error_code: Optional[str] = Field(None, max_length=60)
    diag: Optional[dict] = None


class ExtStories(BaseModel):
    stories: list[dict] = Field(default_factory=list, max_length=500)
    page_url: str = ""


@ext.get("/config")
def ext_config():
    return publish_service.publisher.bridge.ext_config()


@ext.get("/task")
def ext_task():
    return {"task": publish_service.publisher.bridge.current_task()}


@ext.post("/task/{task_id}/event")
def ext_event(task_id: str, ev: ExtEvent):
    return publish_service.publisher.bridge.event(task_id, ev.model_dump(exclude_none=True))


@ext.post("/stories")
def ext_stories(req: ExtStories):
    publish_service.publisher.bridge.touch()
    return publish_service.save_stories_from_extension(req.stories, req.page_url)


@ext.post("/diag")
def ext_diag(diag: dict):
    return {"path": publish_service.publisher.bridge.save_diag(diag)}


# --- glossary -----------------------------------------------------------------
@router.get("/projects/{pid}/glossary")
def get_glossary(pid: str):
    return store.get_glossary(pid)


@router.put("/projects/{pid}/glossary")
def put_glossary(pid: str, entries: list[GlossaryEntry]):
    log.info("Glossary saved: %d entries", len(entries))
    return store.save_glossary(pid, [e.model_dump() for e in entries])
