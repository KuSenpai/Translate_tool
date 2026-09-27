"""End-to-end test of the browser-extension publishing path.

Real Chromium with the real `extension/` loaded (manifest patched to also run on the local fake
Wattpad), the real app served over HTTP, and the fake Wattpad site from tests/fake_wattpad.py.
"""
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from tests.fake_wattpad import FakeWattpad

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def env(tmp_root):
    from app import config
    from app.main import app
    fake = FakeWattpad()
    saved = config.WATTPAD_BASE_URL, config.WATTPAD_MODE
    config.WATTPAD_BASE_URL, config.WATTPAD_MODE = fake.base, "extension"

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    app_url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(app_url + "/api/ai/status", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.1)

    # Chromium here cannot load unpacked extensions from the command line (it hangs even with an empty
    # manifest), so the real extension/content.js is injected into every page and chrome.runtime is
    # replaced by a bridge that does exactly what extension/background.js does: call /api/ext/* on the
    # app with the X-NT-Extension header.
    routes = {"config": ("GET", "/api/ext/config"), "task": ("GET", "/api/ext/task"),
              "stories": ("POST", "/api/ext/stories"), "diag": ("POST", "/api/ext/diag")}

    def bridge(raw: str) -> str:
        msg = json.loads(raw)
        method, path = routes.get(msg["type"], ("POST", f"/api/ext/task/{msg.get('id')}/event"))
        try:
            r = httpx.request(method, app_url + path, headers={"X-NT-Extension": "1"},
                              json=msg.get("data") if method == "POST" else None, timeout=10)
            body = r.json()
            return json.dumps({"ok": True, "data": body} if r.status_code < 400 else
                              {"ok": False, "error": body.get("error", {}).get("message", str(r.status_code))})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    shim = """window.chrome = { runtime: {
        sendMessage: (msg, cb) => { window.__ntBridge(JSON.stringify(msg)).then((r) => cb && cb(JSON.parse(r))); },
        onMessage: { addListener() {} }, lastError: null } };"""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(str(tmp_root / "ext_profile"), headless=True)
    ctx.expose_function("__ntBridge", bridge)
    ctx.add_init_script(shim)
    ctx.add_init_script(path=str(ROOT / "extension" / "content.js"))
    page = ctx.new_page()
    page.goto(fake.base + "/dev-login")          # the user is logged in to Wattpad in their browser
    yield {"fake": fake, "app": app_url, "page": page}
    ctx.close()
    pw.stop()
    server.should_exit = True
    fake.close()
    config.WATTPAD_BASE_URL, config.WATTPAD_MODE = saved


def wait_job(client, job_id, page, timeout=90):
    # page.wait_for_timeout (not time.sleep) keeps Playwright dispatching the page -> Python bridge calls
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["state"] != "running":
            return j
        page.wait_for_timeout(500)
    raise AssertionError("job did not finish: " + json.dumps(j, ensure_ascii=False))


def ready(client, book, number, name):
    with open(book, "rb") as f:
        pid = client.post("/api/projects/upload", files={"file": (name, f)}).json()["project"]["id"]
    client.post(f"/api/projects/{pid}/chapters/{number}/load", json={})
    client.post(f"/api/projects/{pid}/chapters/{number}/status", json={"event": "review"})
    return pid


def test_ext_api_rejects_web_pages(env):
    r = httpx.get(env["app"] + "/api/ext/task")
    assert r.status_code == 403
    r = httpx.get(env["app"] + "/api/ext/task", headers={"X-NT-Extension": "1", "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_extension_sends_story_list(env, client):
    env["page"].goto(env["fake"].base + "/myworks")
    end = time.time() + 30
    while time.time() < end:
        st = client.get("/api/wattpad/status").json()
        if {"111", "222", "333"} <= {s["id"] for s in st["stories"]}:
            break
        env["page"].wait_for_timeout(500)
    titles = {s["id"]: s["title"] for s in st["stories"]}
    assert titles["111"] == "Truyện Thử Nghiệm" and titles["222"] == "Second Story"
    assert st["mode"] == "extension" and st["extension_connected"]


def test_extension_publish_end_to_end(env, client, book):
    fake, page = env["fake"], env["page"]
    pid = ready(client, book, 12, "ext-book.docx")
    before = set(fake.parts)
    job = client.post(f"/api/projects/{pid}/chapters/12/publish",
                      json={"story_id": "111", "story_title": "Truyện Thử Nghiệm", "title": "Chương 12: Gặp gỡ",
                            "mode": "publish", "confirm": True}).json()
    assert job["open_url"] == fake.base + "/myworks/111"
    page.goto(job["open_url"])                    # what the app's window.open does
    j = wait_job(client, job["id"], page)
    assert j["state"] == "done", j
    (part_id,) = set(fake.parts) - before
    part = fake.parts[part_id]
    assert part["published"] and part["title"] == "Chương 12: Gặp gỡ"
    assert "<b>in đậm</b>" in part["html"] and "Hết chương 12." in part["text"]
    ch = client.get(f"/api/projects/{pid}/chapters/12").json()
    assert ch["status"] == "PUBLISHED"
    assert ch["publish_history"][-1]["part_id"] == part_id and ch["publish_history"][-1]["docx"].endswith("Chapter_12.docx")


def test_extension_draft_mode(env, client, book):
    fake, page = env["fake"], env["page"]
    pid = ready(client, book, 11, "ext-book2.docx")
    before = set(fake.parts)
    job = client.post(f"/api/projects/{pid}/chapters/11/publish",
                      json={"story_id": "222", "title": "Chương 11", "mode": "draft", "confirm": True}).json()
    page.goto(job["open_url"])
    j = wait_job(client, job["id"], page)
    assert j["state"] == "done", j
    (part_id,) = set(fake.parts) - before
    assert not fake.parts[part_id]["published"] and fake.parts[part_id]["title"] == "Chương 11"
    assert client.get(f"/api/projects/{pid}/chapters/11").json()["status"] == "READY_TO_PUBLISH"


def test_cancel_from_app(env, client, book):
    pid = ready(client, book, 10, "ext-book3.docx")
    job = client.post(f"/api/projects/{pid}/chapters/10/publish",
                      json={"story_id": "111", "title": "Chương 10", "confirm": True}).json()
    j = client.post(f"/api/jobs/{job['id']}/cancel").json()          # tab never opened: user cancels
    assert j["state"] == "error" and j["error_code"] == "CANCELLED"
    assert client.get(f"/api/projects/{pid}/chapters/10").json()["status"] == "READY_TO_PUBLISH"
    assert httpx.get(env["app"] + "/api/ext/task", headers={"X-NT-Extension": "1"}).json() == {"task": None}
