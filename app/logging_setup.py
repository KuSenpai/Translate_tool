"""Logging with `[TAG] message` lines and a redaction filter for secrets."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from . import config

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),                       # OpenAI / Anthropic style keys
    re.compile(r"(?i)(api[_-]?key|token|password|passwd|secret|cookie|authorization)(\s*[=:]\s*)([^\s,;]+)"),
]


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        red = _SECRET_PATTERNS[0].sub("sk-***", msg)
        red = _SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)}{m.group(2)}***", red)
        if red != msg:
            record.msg, record.args = red, ()
        return True


def setup_logging() -> None:
    config.ensure_dirs()
    root = logging.getLogger("novel")
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    for h in (logging.StreamHandler(),
              RotatingFileHandler(config.LOG_DIR / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")):
        h.setFormatter(fmt)
        h.addFilter(RedactFilter())
        root.addHandler(h)
    root.propagate = False


def get_logger(tag: str) -> logging.LoggerAdapter:
    """Logger whose messages are prefixed with `[TAG]`."""

    class _Adapter(logging.LoggerAdapter):
        def process(self, msg, kwargs):
            return f"[{tag}] {msg}", kwargs

    return _Adapter(logging.getLogger(f"novel.{tag.lower()}"), {})
