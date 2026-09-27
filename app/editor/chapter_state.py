"""Chapter lifecycle: LOADED → EDITING → REVIEWED → READY_TO_PUBLISH → PUBLISHED."""
from __future__ import annotations

from enum import Enum

from ..errors import StateError
from ..storage.project_state import now_iso


class Status(str, Enum):
    LOADED = "LOADED"
    EDITING = "EDITING"
    REVIEWED = "REVIEWED"
    READY_TO_PUBLISH = "READY_TO_PUBLISH"
    PUBLISHED = "PUBLISHED"


# event -> (allowed source states, target state)
_TRANSITIONS: dict[str, tuple[set[Status], Status]] = {
    "edit": (set(Status), Status.EDITING),
    "review": ({Status.LOADED, Status.EDITING, Status.REVIEWED}, Status.REVIEWED),
    "ready": ({Status.REVIEWED, Status.READY_TO_PUBLISH}, Status.READY_TO_PUBLISH),
    "unready": ({Status.READY_TO_PUBLISH}, Status.REVIEWED),
    "published": ({Status.READY_TO_PUBLISH}, Status.PUBLISHED),
}

_HINT = {
    "review": "Chỉ có thể đánh dấu đã review khi chương đang LOADED/EDITING.",
    "ready": "Cần Preview và đánh dấu 'Đã review' trước khi sẵn sàng đăng.",
    "published": "Chỉ chương ở trạng thái READY_TO_PUBLISH mới được đăng.",
}


def transition(chapter: dict, event: str) -> dict:
    """Apply `event` to the chapter record in place; raises StateError if not allowed."""
    allowed, target = _TRANSITIONS[event]
    current = Status(chapter.get("status", Status.LOADED))
    if current not in allowed:
        raise StateError(f"Không thể chuyển từ {current.value} ({event}). {_HINT.get(event, '')}".strip(),
                         code="INVALID_TRANSITION", details={"status": current.value, "event": event})
    if current != target:
        chapter["status"] = target.value
        chapter.setdefault("status_history", []).append({"from": current.value, "to": target.value,
                                                         "event": event, "at": now_iso()})
    return chapter
