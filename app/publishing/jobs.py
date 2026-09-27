"""Background jobs that run the Wattpad worker subprocess. One Wattpad job at a time
(the browser profile can only be opened by one browser)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from typing import Callable, Optional

from .. import config
from ..errors import AppError, NotFound
from ..logging_setup import get_logger
from ..storage.project_state import now_iso

log = get_logger("WATTPAD")


class JobBusy(AppError):
    status = 409
    code = "JOB_BUSY"


class JobManager:
    def __init__(self, worker_cmd: Optional[list[str]] = None):
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._active: Optional[str] = None
        self.worker_cmd = worker_cmd or [sys.executable, "-m", "app.publishing.wattpad_worker"]

    def get(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if job is None:
            raise NotFound("Job không tồn tại.")
        if job.get("_external") and job["state"] == "running" and time.time() > job["_deadline"]:
            self.finish(job_id, {"ok": False, "error_code": "EXTENSION_TIMEOUT",
                                 "message": job.get("_timeout_message") or "Hết thời gian chờ."})
        return {k: v for k, v in job.items() if not k.startswith("_")}

    # --- jobs driven from outside (the browser extension reports progress and the result) -------
    def start_external(self, kind: str, message: str, timeout: int, timeout_message: str,
                       on_done: Optional[Callable[[dict, dict], None]] = None) -> dict:
        with self._lock:
            if self._active and self.jobs[self._active]["state"] == "running":
                raise JobBusy("Đang có một thao tác Wattpad khác chạy. Hãy đợi nó xong hoặc bấm Huỷ.")
            job_id = uuid.uuid4().hex[:12]
            self.jobs[job_id] = {"id": job_id, "kind": kind, "state": "running", "message": message, "log": [],
                                 "result": None, "error_code": None, "started_at": now_iso(), "external": True,
                                 "_external": True, "_deadline": time.time() + timeout,
                                 "_timeout_message": timeout_message, "_on_done": on_done}
            self._active = job_id
        return self.get(job_id)

    def progress(self, job_id: str, message: str) -> None:
        job = self.jobs.get(job_id)
        if job and job["state"] == "running":
            job["message"] = message
            job["log"].append(message)
            job["_deadline"] = max(job["_deadline"], time.time() + 300)  # activity extends the deadline
            log.info("%s: %s", job["kind"], message)

    def finish(self, job_id: str, result: dict) -> None:
        job = self.jobs.get(job_id)
        if not job or job["state"] != "running":
            return
        on_done = job.get("_on_done")
        if on_done:
            try:
                on_done(job, result)
            except Exception as e:
                log.exception("on_done failed: %s", e)
                result = {**result, "ok": False, "error_code": "INTERNAL", "message": f"Lỗi khi lưu kết quả: {e}"}
        job["result"] = result
        job["error_code"] = None if result.get("ok") else result.get("error_code")
        job["message"] = result.get("message") or ("Hoàn tất." if result.get("ok") else "Thất bại.")
        job["state"] = "done" if result.get("ok") else "error"
        (log.info if result.get("ok") else log.warning)("%s finished: ok=%s %s", job["kind"], result.get("ok"),
                                                         job["error_code"] or "")

    def start(self, kind: str, command: dict, timeout: int,
              on_done: Optional[Callable[[dict, dict], None]] = None, env: Optional[dict] = None) -> dict:
        with self._lock:
            if self._active and self.jobs[self._active]["state"] == "running":
                raise JobBusy("Đang có một thao tác Wattpad khác chạy. Hãy đợi nó xong.")
            job_id = uuid.uuid4().hex[:12]
            job = {"id": job_id, "kind": kind, "state": "running", "message": "Đang khởi động trình duyệt…",
                   "log": [], "result": None, "error_code": None, "started_at": now_iso()}
            self.jobs[job_id] = job
            self._active = job_id
        threading.Thread(target=self._run, args=(job, command, timeout, on_done, env), daemon=True).start()
        return self.get(job_id)

    def _run(self, job: dict, command: dict, timeout: int, on_done, env) -> None:
        result: dict = {"ok": False, "error_code": "WATTPAD_ERROR", "message": "Worker kết thúc bất thường."}
        try:
            proc = subprocess.Popen(
                self.worker_cmd, cwd=str(config.BASE_DIR), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})})
            killed = threading.Event()
            timer = threading.Timer(timeout, lambda: (killed.set(), proc.kill()))
            timer.start()
            try:
                proc.stdin.write(json.dumps(command, ensure_ascii=False))
                proc.stdin.close()
                for line in proc.stdout:
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == "progress":
                        job["message"] = msg["message"]
                        job["log"].append(msg["message"])
                        log.info("%s: %s", job["kind"], msg["message"])
                    elif msg.get("type") == "result":
                        result = msg
                stderr = proc.stderr.read()
                proc.wait()
            finally:
                timer.cancel()
            if killed.is_set() and not result.get("ok"):
                result = {"ok": False, "error_code": "WATTPAD_TIMEOUT", "message": f"Quá {timeout}s — đã dừng thao tác."}
            if stderr.strip() and not result.get("ok"):
                log.warning("worker stderr: %s", stderr.strip().splitlines()[-1][:300])
        except Exception as e:
            result = {"ok": False, "error_code": "WATTPAD_ERROR", "message": f"Không chạy được worker: {e}"}

        job["result"] = result
        if on_done:
            try:
                on_done(job, result)
            except Exception as e:
                log.exception("on_done failed: %s", e)
                result = {**result, "ok": False, "error_code": "INTERNAL", "message": f"Lỗi khi lưu kết quả: {e}"}
        job["error_code"] = None if result.get("ok") else result.get("error_code")
        job["message"] = result.get("message") or ("Hoàn tất." if result.get("ok") else "Thất bại.")
        job["state"] = "done" if result.get("ok") else "error"
        (log.info if result.get("ok") else log.warning)("%s finished: ok=%s %s", job["kind"], result.get("ok"),
                                                         job["error_code"] or "")


jobs = JobManager()
