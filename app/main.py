"""App entry point:  python -m app.main"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .errors import AppError
from .logging_setup import get_logger, setup_logging

setup_logging()
config.ensure_dirs()
log = get_logger("APP")

from .api import ext as ext_router, router  # noqa: E402  (after logging is configured)

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Novel Translator", docs_url="/api/docs")
app.include_router(router)
app.include_router(ext_router)


@app.exception_handler(AppError)
async def _app_error(_: Request, exc: AppError):
    log.warning("%s: %s", exc.code, exc.message)
    return JSONResponse(status_code=exc.status,
                        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}})


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    errors = [{"loc": list(e.get("loc", [])), "msg": str(e.get("msg", ""))} for e in exc.errors()[:5]]
    msg = "; ".join(f"{'.'.join(map(str, e['loc'][1:]))}: {e['msg']}" for e in errors)
    return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION", "message": f"Dữ liệu không hợp lệ: {msg}",
                                                            "details": {"errors": errors}}})


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception):
    log.exception("Unexpected error: %s", exc)
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL", "message": f"Lỗi không mong muốn: {exc}"}})


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


def run() -> None:
    import uvicorn
    log.info("Starting on http://%s:%d", config.HOST, config.PORT)
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    run()
