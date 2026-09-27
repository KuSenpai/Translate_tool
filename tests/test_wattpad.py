"""Publisher tests against a local fake Wattpad (real Playwright, real browser, headless)."""
import os
import time

import docx
import pytest

from tests.fake_wattpad import FakeWattpad


@pytest.fixture(scope="module")
def fake(tmp_root):
    from app import config
    old_mode, config.WATTPAD_MODE = config.WATTPAD_MODE, "playwright"   # these tests cover the Playwright path
    f = FakeWattpad()
    profile = tmp_root / "wp_profile"
    os.environ.update(WATTPAD_BASE_URL=f.base, WATTPAD_PROFILE_DIR=str(profile), WATTPAD_HEADLESS="true",
                      WATTPAD_BROWSER_CHANNEL="", WATTPAD_PUBLISH_WAIT="4")
    # Simulate the one-time manual login by seeding the persistent profile's cookie.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(profile), headless=True)
        ctx.new_page().goto(f.base + "/dev-login")
        ctx.close()
    yield f
    f.close()
    config.WATTPAD_MODE = old_mode


def wait_job(client, job, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.5)
    raise AssertionError("job did not finish")


def ready_chapter(client, book, number):
    with open(book, "rb") as f:
        pid = client.post("/api/projects/upload", files={"file": ("wp-book.docx", f)}).json()["project"]["id"]
    client.post(f"/api/projects/{pid}/chapters/{number}/load", json={})
    client.post(f"/api/projects/{pid}/chapters/{number}/status", json={"event": "review"})
    return pid


def test_stories(client, fake):
    j = wait_job(client, client.post("/api/wattpad/stories").json())
    assert j["state"] == "done", j
    ids = {s["id"]: s["title"] for s in client.get("/api/wattpad/status").json()["stories"]}
    assert ids == {"111": "Truyện Thử Nghiệm", "222": "Second Story", "333": "Flaky Story"}


def test_publish_requires_confirmation_and_review(client, book, fake):
    with open(book, "rb") as f:
        pid = client.post("/api/projects/upload", files={"file": ("wp-book.docx", f)}).json()["project"]["id"]
    client.post(f"/api/projects/{pid}/chapters/15/load", json={})
    body = {"story_id": "111", "title": "Chương 15", "mode": "publish", "confirm": True}
    r = client.post(f"/api/projects/{pid}/chapters/15/publish", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_TRANSITION"      # not reviewed
    client.post(f"/api/projects/{pid}/chapters/15/status", json={"event": "review"})
    r = client.post(f"/api/projects/{pid}/chapters/15/publish", json={**body, "confirm": False})
    assert r.json()["error"]["code"] == "CONFIRM_REQUIRED"
    assert not fake.parts


def test_publish_success_end_to_end(client, book, fake):
    pid = ready_chapter(client, book, 12)
    before = set(fake.parts)
    job = client.post(f"/api/projects/{pid}/chapters/12/publish",
                      json={"story_id": "111", "story_title": "Truyện Thử Nghiệm", "title": "Chương 12: Gặp gỡ",
                            "mode": "publish", "confirm": True}).json()
    j = wait_job(client, job)
    assert j["state"] == "done", j
    (new_id,) = set(fake.parts) - before
    part = fake.parts[new_id]
    assert part["published"] and part["story"] == "111" and part["title"] == "Chương 12: Gặp gỡ"
    assert "<b>in đậm</b>" in part["html"] and "<i>in nghiêng</i>" in part["html"]
    assert "Hết chương 12." in part["text"] and "김수현" not in part["text"]
    ch = client.get(f"/api/projects/{pid}/chapters/12").json()
    assert ch["status"] == "PUBLISHED"
    h = ch["publish_history"][-1]
    assert h["ok"] and h["part_id"] == new_id and h["docx"].endswith("Chapter_12.docx")
    assert docx.Document(h["docx"]).paragraphs[0].text == "Chương 12: Gặp gỡ"


def test_draft_mode_does_not_publish(client, book, fake):
    pid = ready_chapter(client, book, 11)
    before = set(fake.parts)
    j = wait_job(client, client.post(f"/api/projects/{pid}/chapters/11/publish",
                                     json={"story_id": "222", "title": "Chương 11", "mode": "draft", "confirm": True}).json())
    assert j["state"] == "done", j
    (new_id,) = set(fake.parts) - before
    assert not fake.parts[new_id]["published"] and fake.parts[new_id]["title"] == "Chương 11"
    assert client.get(f"/api/projects/{pid}/chapters/11").json()["status"] == "READY_TO_PUBLISH"


def test_story_not_found(client, book, fake):
    pid = ready_chapter(client, book, 10)
    j = wait_job(client, client.post(f"/api/projects/{pid}/chapters/10/publish",
                                     json={"story_id": "999", "title": "Chương 10", "confirm": True}).json())
    assert j["state"] == "error" and j["error_code"] == "WATTPAD_STORY_NOT_FOUND"
    ch = client.get(f"/api/projects/{pid}/chapters/10").json()
    assert ch["status"] == "READY_TO_PUBLISH" and not ch["publish_history"][-1]["ok"]


def test_failure_then_retry_reuses_part(client, book, fake):
    pid = ready_chapter(client, book, 13)
    body = {"story_id": "333", "title": "Chương 13", "mode": "publish", "confirm": True}
    before = set(fake.parts)
    j = wait_job(client, client.post(f"/api/projects/{pid}/chapters/13/publish", json=body).json())
    assert j["state"] == "error" and j["error_code"] == "WATTPAD_PUBLISH_FAILED", j
    ch = client.get(f"/api/projects/{pid}/chapters/13").json()
    assert ch["status"] == "READY_TO_PUBLISH"
    (part_id,) = set(fake.parts) - before
    assert ch["wattpad"]["part_id"] == part_id and not fake.parts[part_id]["published"]

    j = wait_job(client, client.post(f"/api/projects/{pid}/chapters/13/publish", json=body).json())
    assert j["state"] == "done", j
    assert set(fake.parts) - before == {part_id}          # retry updated the same part, no duplicate
    assert fake.parts[part_id]["published"]
    assert client.get(f"/api/projects/{pid}/chapters/13").json()["status"] == "PUBLISHED"


def test_session_expired(client, book, fake, tmp_root):
    pid = ready_chapter(client, book, 14)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:  # log out: drop cookies from the profile
        ctx = p.chromium.launch_persistent_context(str(tmp_root / "wp_profile"), headless=True)
        ctx.clear_cookies()
        ctx.close()
    j = wait_job(client, client.post(f"/api/projects/{pid}/chapters/14/publish",
                                     json={"story_id": "111", "title": "Chương 14", "confirm": True}).json())
    assert j["state"] == "error" and j["error_code"] == "WATTPAD_SESSION_EXPIRED"
    assert client.get(f"/api/projects/{pid}/chapters/14").json()["status"] == "READY_TO_PUBLISH"
    assert client.get("/api/wattpad/status").json()["logged_in_hint"] is False


def test_login_waits_while_wattpad_unreachable(tmp_root):
    """Wattpad blocked (VPN off) at first: the window must stay open and login must continue once reachable."""
    import socket
    import threading
    from app.publishing.wattpad_publisher import WattpadPublisher
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    holder = {}
    timer = threading.Timer(12, lambda: holder.setdefault("fake", FakeWattpad(port=port, auto_login=True)))
    timer.start()
    msgs = []
    try:
        with WattpadPublisher(msgs.append, base_url=f"http://127.0.0.1:{port}", profile_dir=tmp_root / "wp_vpn",
                              channel="", headless=True) as wp:
            assert wp._login_flow(90) == {"logged_in": True}
    finally:
        timer.cancel()
        if "fake" in holder:
            holder["fake"].close()
    assert any("VPN" in m for m in msgs) and any("Đã vào được Wattpad" in m for m in msgs)


def test_stories_empty_page_and_manual_link(client, fake, tmp_root):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:  # log back in (an earlier test expired the session)
        ctx = p.chromium.launch_persistent_context(str(tmp_root / "wp_profile"), headless=True)
        ctx.new_page().goto(fake.base + "/dev-login")
        ctx.close()
    fake.empty_myworks = True
    try:
        j = wait_job(client, client.post("/api/wattpad/stories").json())
    finally:
        fake.empty_myworks = False
    assert j["state"] == "done" and "dán link" in j["message"]
    assert j["result"]["screenshot"] and os.path.exists(j["result"]["screenshot"])
    r = client.post("/api/wattpad/stories/manual",
                    json={"link": "https://www.wattpad.com/story/383920011-atlantis-cua-than?utm=x"})
    assert r.json() == {"id": "383920011", "title": "Atlantis Cua Than", "manual": True}
    assert client.post("/api/wattpad/stories/manual", json={"link": "https://www.wattpad.com/myworks/123456789"}).json()["id"] == "123456789"
    assert client.post("/api/wattpad/stories/manual", json={"link": "không phải link"}).json()["error"]["code"] == "BAD_STORY_LINK"
    ids = {s["id"] for s in client.get("/api/wattpad/status").json()["stories"]}
    assert {"383920011", "123456789"} <= ids
    # A later automatic refresh keeps manually added stories.
    assert wait_job(client, client.post("/api/wattpad/stories").json())["state"] == "done"
    ids = {s["id"] for s in client.get("/api/wattpad/status").json()["stories"]}
    assert {"111", "222", "333", "383920011"} <= ids


def test_logged_out_is_not_mistaken_for_logged_in(client, fake, tmp_root):
    """Real Wattpad sends logged-out visitors of /myworks to the home page (trending /story/ links).
    That must be reported as an expired session — never as a list of 'stories'."""
    from playwright.sync_api import sync_playwright
    from app.publishing.wattpad_publisher import WattpadPublisher
    profile = tmp_root / "wp_loggedout"
    with WattpadPublisher(base_url=fake.base, profile_dir=profile, channel="", headless=True) as wp:
        assert wp.is_logged_in() is False
        with pytest.raises(Exception) as e:
            wp.list_stories()
        assert getattr(e.value, "code", None) == "WATTPAD_SESSION_EXPIRED"
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(profile), headless=True)
        ctx.new_page().goto(fake.base + "/dev-login")
        ctx.close()
    with WattpadPublisher(base_url=fake.base, profile_dir=profile, channel="", headless=True) as wp:
        assert wp.is_logged_in() is True
        assert {s["id"] for s in wp.list_stories()["stories"]} == {"111", "222", "333"}
