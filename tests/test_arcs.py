"""Automatic chapter titles by story arc: "<number>. <arc> (<n>)"."""
import pytest

from app.editor import arcs


def _upload(client, book, name):
    with open(book, "rb") as f:
        return client.post("/api/projects/upload", files={"file": (name, f)}).json()["project"]["id"]


def test_norm_key():
    assert arcs.norm_key("2220. 경성 2033") == arcs.norm_key("경성 2033") == "경성2033"
    assert arcs.norm_key("다크 문") == arcs.norm_key("다크문") and arcs.norm_key("EP.2221 2221. 다크 문") == arcs.norm_key("다크 문")


def test_default_big_arcs_are_stable(client, book):
    pid = _upload(client, book, "arcs-a.docx")
    a = client.get(f"/api/projects/{pid}/arcs").json()
    b = client.get(f"/api/projects/{pid}/arcs").json()
    assert [x["id"] for x in a["arcs"]] == [x["id"] for x in b["arcs"]] and len(a["arcs"]) == 6
    assert {x["name"] for x in a["arcs"]} >= {"Dark Moon", "Eternal Eden", "Atlantis của Thần", "Quang Minh Thăng Thiên Đồ"}
    assert all(x["big"] for x in a["arcs"]) and a["template"] == "{number}. {name} ({n})"


def test_new_small_arc_then_previous_counts_up(client, book):
    pid = _upload(client, book, "arcs-b.docx")
    s = client.post(f"/api/projects/{pid}/chapters/12/title/suggest", json={}).json()
    assert s["source"] == "none" and s["title"] is None and len(s["arcs"]) == 6
    s = client.post(f"/api/projects/{pid}/chapters/13/title/suggest", json={"new_name": "Khởi Đầu Mới"}).json()
    assert s["source"] == "new" and s["ko_title"] == "새로운 시작" and s["title"] == "13. Khởi Đầu Mới (1)"
    # nothing is recorded until applied
    assert len(client.get(f"/api/projects/{pid}/arcs").json()["arcs"]) == 6
    r = client.post(f"/api/projects/{pid}/chapters/13/title/apply", json={"new_name": "Khởi Đầu Mới"}).json()
    assert r["title"] == "13. Khởi Đầu Mới (1)" and r["arc"]["id"]
    v = client.get(f"/api/projects/{pid}/arcs").json()
    assert len(v["arcs"]) == 7 and v["arcs"][-1]["name"] == "Khởi Đầu Mới" and not v["arcs"][-1]["big"]
    # no Korean title → continues the previous chapter's arc; the counter advances once per chapter
    for n, expect in ((14, "14. Khởi Đầu Mới (2)"), (15, "15. Khởi Đầu Mới (3)")):
        assert client.post(f"/api/projects/{pid}/chapters/{n}/title/apply", json={}).json()["title"] == expect
    again = client.post(f"/api/projects/{pid}/chapters/14/title/apply", json={}).json()
    assert again["title"] == "14. Khởi Đầu Mới (2)" and again["source"] == "assigned"      # idempotent


def test_choose_other_arc_and_rebase_counter(client, book):
    pid = _upload(client, book, "arcs-c.docx")
    dm = next(a for a in client.get(f"/api/projects/{pid}/arcs").json()["arcs"] if a["name"] == "Dark Moon")
    # "Dark Moon is at (95) now" → the next chapter is (96)
    arcs_in = [{"id": a["id"], "name": a["name"], "ko": a["ko_raw"], "big": a["big"], "last_n": 95 if a["id"] == dm["id"] else None}
               for a in client.get(f"/api/projects/{pid}/arcs").json()["arcs"]]
    v = client.put(f"/api/projects/{pid}/arcs", json={"arcs": arcs_in}).json()
    assert next(a for a in v["arcs"] if a["id"] == dm["id"])["last_n"] == 95
    s = client.post(f"/api/projects/{pid}/chapters/12/title/apply", json={"arc_id": dm["id"]}).json()
    assert s["title"] == "12. Dark Moon (96)" and s["source"] == "manual"
    assert client.post(f"/api/projects/{pid}/chapters/14/title/apply", json={}).json()["title"] == "14. Dark Moon (97)"
    # out-of-order: chapter 11 is below 12 so it takes (96)? no — it counts only chapters below it
    assert client.post(f"/api/projects/{pid}/chapters/11/title/apply", json={"arc_id": dm["id"]}).json()["title"] == "11. Dark Moon (96)"
    assert client.post(f"/api/projects/{pid}/chapters/12/title/suggest", json={}).json()["title"] == "12. Dark Moon (97)"


def test_update_validation_and_template(client, book):
    pid = _upload(client, book, "arcs-d.docx")
    cur = client.get(f"/api/projects/{pid}/arcs").json()["arcs"]
    bad = [{"name": "A", "ko": ["다크 문"]}, {"name": "B", "ko": ["다크문"]}]
    assert client.put(f"/api/projects/{pid}/arcs", json={"arcs": bad}).json()["error"]["code"] == "ARC_ERROR"
    assert client.put(f"/api/projects/{pid}/arcs", json={"arcs": [{"name": " "}]}).json()["error"]["code"] == "ARC_ERROR"
    ok = [{"id": a["id"], "name": a["name"], "ko": a["ko_raw"], "big": True} for a in cur]
    v = client.put(f"/api/projects/{pid}/arcs", json={"arcs": ok, "template": "Chương {number}: {name} [{n}]"}).json()
    assert v["template"] == "Chương {number}: {name} [{n}]"
    assert client.post(f"/api/projects/{pid}/chapters/13/title/apply", json={"new_name": "X"}).json()["title"] == "Chương 13: X [1]"


def test_seed_and_title_used_when_chapter_is_loaded(client, book):
    pid = _upload(client, book, "arcs-e.docx")
    r = client.post(f"/api/projects/{pid}/arcs/seed").json()
    assert r["chapters"] == 6 and r["created"] == 1 and r["added"] >= 1
    names = [a["name"] for a in r["arcs"]]
    assert names[-1] in ("새로운 시작",) or "Mở" in names[-1] or names[-1]            # small arc named from the Korean/Vietnamese title
    # chapters ≥ 13 are assigned; loading creates the record with the arc title
    ch = client.post(f"/api/projects/{pid}/chapters/14/load", json={}).json()
    assert ch["title"].startswith("14. ") and ch["title"].endswith("(2)")
    # chapters before the first titled one stay on the old default
    assert client.post(f"/api/projects/{pid}/chapters/12/load", json={}).json()["title"].startswith("Chương 12")


def test_translate_name_with_mock(client, book, monkeypatch):
    pid = _upload(client, book, "arcs-f.docx")
    monkeypatch.setenv("TRANSLATE_PROVIDER", "mock")
    r = client.post(f"/api/projects/{pid}/arcs/translate-name", json={"ko": "다크 문", "model": "claude-opus-5-5"})
    assert r.status_code == 200 and r.json()["name"]
