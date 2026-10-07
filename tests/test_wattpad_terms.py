"""Old Wattpad chapters → termbase corrections + arc counters (the extension is simulated through /api/ext)."""
import time

import pytest

from app.ai import wattpad_terms
from app.ai.wattpad_terms import TITLE_RE, clean_text, part_number

EXT = {"x-nt-extension": "1"}


def _upload(client, book, name):
    with open(book, "rb") as f:
        return client.post("/api/projects/upload", files={"file": (name, f)}).json()["project"]["id"]


def test_title_and_text_helpers():
    m = TITLE_RE.match("2201. Dark Moon (165)")
    assert (m.group(1), m.group(2), m.group(3)) == ("2201", "Dark Moon", "165")
    assert TITLE_RE.match("EP.2221 2221. Atlantis của Thần (340)").group(2) == "Atlantis của Thần"
    assert part_number("2282. Atlantis của Thần (342)") == 2282 and part_number("Untitled Part 7") is None
    raw = "Note: I'm back, ủng hộ tôi qua 0816\n-\n\nĐoạn một.\nĐoạn hai."
    assert clean_text(raw) == "Đoạn một.\nĐoạn hai."


@pytest.fixture()
def ko_file(tmp_path):
    p = tmp_path / "raw.txt"
    pad = "그는 천천히 걸어가며 하늘을 올려다보았다. 바람이 차갑게 불어오고 있었다. " * 2
    p.write_text(f"2201. 다크 문\n김수현은 웃었다. {pad}\n선배가 말했다.\n\n2202. 다크 문\n김수현이 고개를 끄덕였다. {pad}\n", encoding="utf-8")
    return p


def _wait(client, pid, want, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get(f"/api/projects/{pid}/termbase/wattpad-scan").json()
        if s.get("status") in want:
            return s
        time.sleep(0.2)
    raise AssertionError(f"timeout, last state: {s}")


def test_full_flow(client, book, ko_file):
    pid = _upload(client, book, "wp-a.docx")
    client.put(f"/api/projects/{pid}/glossary", json=[{"source": "김수현", "target": "Kim Su-hyeon"}])
    body = {"stories": [{"id": "415652111", "title": "Into creation (2201-2400)"}], "korean_path": str(ko_file),
            "model": "claude-opus-5-5", "from_number": 2201, "to_number": 2202}
    s = client.post(f"/api/projects/{pid}/termbase/wattpad-scan", json=body).json()
    assert s["status"] == "fetching" and s["active"]
    # a second scan cannot start while one is running
    assert client.post(f"/api/projects/{pid}/termbase/wattpad-scan", json=body).json()["error"]["code"] == "SCAN_RUNNING"

    # --- the extension: claims the task, posts parts, reports done
    task = client.get("/api/ext/scan?tab=t1", headers=EXT).json()["task"]
    assert task["stories"][0]["id"] == "415652111" and task["from"] == 2201
    assert client.get("/api/ext/scan?tab=other", headers=EXT).json()["task"] is None      # claimed by t1
    parts = [{"id": 1, "title": "2201. Dark Moon (165)", "text": "Note: ủng hộ tôi\n-\nKim Soo-hyun cười.\nTiền bối nói."},
             {"id": 2, "title": "2202. Dark Moon (166)", "text": "Kim Soo-hyun gật đầu."},
             {"id": 3, "title": "2999. Out of range (1)", "text": "bỏ qua"}]
    assert client.post(f"/api/ext/scan/{task['id']}/chunk", json={"parts": parts}, headers=EXT).json() == {"ok": True, "cancel": False}
    assert client.post(f"/api/ext/scan/{task['id']}/event", json={"story_done": True, "done": True}, headers=EXT).json()["ok"]

    done = _wait(client, pid, ("done", "error"))
    assert done["status"] == "done", done
    assert done["fetched"] == 2 and done["arcs"]["chapters"] == 2

    props = client.get(f"/api/projects/{pid}/termbase").json()["proposals"]
    p = next(x for x in props if x["source"] == "김수현")
    assert p["origin"] == "wattpad-old" and p["target"] == "Kim Soo-hyun" and p["current"] == "Kim Su-hyeon"
    assert "Kim Su-hyeon" in p["variants"]
    # accepting prefers the old rendering and keeps the current one as "avoid"
    client.post(f"/api/projects/{pid}/termbase/proposals", json={"accept": [{"source": "김수현", "target": "Kim Soo-hyun"}], "reject": []})
    g = next(x for x in client.get(f"/api/projects/{pid}/glossary").json() if x["source"] == "김수현")
    assert g["target"] == "Kim Soo-hyun" and "Kim Su-hyeon" in g["avoid"]

    # arc counters come from the published titles: Dark Moon (166) is chapter 2202 → the next one is (167)
    t = client.post(f"/api/projects/{pid}/chapters/2203/title/suggest", json={}).json()
    assert t["title"] == "2203. Dark Moon (167)" and t["source"] == "previous"
    assert wattpad_terms.wattpad_scan.task["parts"] == {}                     # texts are not kept


def test_start_validation(client, book, tmp_path):
    pid = _upload(client, book, "wp-b.docx")
    base = {"stories": [{"id": "1", "title": "t"}], "model": "claude-opus-5-5"}
    r = client.post(f"/api/projects/{pid}/termbase/wattpad-scan", json={**base, "korean_path": str(tmp_path / "nope.txt")})
    assert r.json()["error"]["code"] == "NO_KOREAN"


def test_no_parts_is_an_error(client, book, ko_file):
    pid = _upload(client, book, "wp-c.docx")
    client.post(f"/api/projects/{pid}/termbase/wattpad-scan", json={
        "stories": [{"id": "415652111", "title": "x"}], "korean_path": str(ko_file), "model": "claude-opus-5-5"})
    task = client.get("/api/ext/scan?tab=t9", headers=EXT).json()["task"]
    client.post(f"/api/ext/scan/{task['id']}/event", json={"error": "HTTP 403", "done": True}, headers=EXT)
    s = client.get(f"/api/projects/{pid}/termbase/wattpad-scan").json()
    assert s["status"] == "error" and "HTTP 403" in s["message"]


def test_cancel_while_fetching(client, book, ko_file):
    pid = _upload(client, book, "wp-d.docx")
    client.post(f"/api/projects/{pid}/termbase/wattpad-scan", json={
        "stories": [{"id": "415652111", "title": "x"}], "korean_path": str(ko_file), "model": "claude-opus-5-5"})
    s = client.post(f"/api/projects/{pid}/termbase/wattpad-scan/cancel").json()
    assert s["status"] == "cancelled" and not s["active"]
    assert client.get("/api/ext/scan?tab=t1", headers=EXT).json()["task"] is None


def test_arcs_sync_from_titles(client, book):
    from app.editor import arcs
    pid = _upload(client, book, "wp-e.docx")
    r = arcs.sync_from_titles(pid, [(2201, "Dark Moon", 165), (2202, "dark moon", 166), (2280, "Atlantis của Thần", 340), (2281, "Trò Mới", 1)])
    assert r == {"chapters": 4, "arcs": 3, "created": 1, "name_diffs": {"dark moon": "Dark Moon"}}
    v = arcs.view(pid)
    dm = next(a for a in v["arcs"] if a["name"] == "Dark Moon")
    assert dm["last_n"] == 166 and dm["count"] == 2
    assert arcs.suggest(pid, 2203, arc_id=dm["id"])["title"] == "2203. Dark Moon (167)"
    assert any(a["name"] == "Trò Mới" and not a["big"] for a in v["arcs"])
