"""Application error types. Every error carries a stable `code` the UI can show."""
from __future__ import annotations


class AppError(Exception):
    status = 400
    code = "APP_ERROR"

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}


class NotFound(AppError):
    status = 404
    code = "NOT_FOUND"


class DocxError(AppError):
    status = 422
    code = "DOCX_ERROR"


class ChapterError(AppError):
    status = 404
    code = "CHAPTER_ERROR"


class StateError(AppError):
    status = 409
    code = "INVALID_STATE"
