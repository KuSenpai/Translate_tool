"""Termbase: import user data, AI scan of old chapters (mock), consistency check, use in translation."""
import time

from app.ai.termbase import parse_data
from app.editor.glossary import entries_for_text, glossary_prompt

DATA = """# Data truyện
김수현 = Kim Soo-hyun (nhân vật chính)
천마신공 → Thiên Ma Thần Công
선배: tiền bối
이리나\tIrina
Kim Soo-hyun là sát thủ 25 tuổi, xưng "tôi" khi kể chuyện.
Irina gọi Kim Soo-hyun là "anh".
"""


def project(client, book, name):
    with open(book, "rb") as f:
        return client.post("/api/projects/upload", files={"file": (name, f)}).json()["project"]["id"]


def test_parse_data_terms_and_notes():
    entries, notes = parse_data(DATA)
    assert [(e["source"], e["target"]) for e in entries] == [
        ("김수현", "Kim Soo-hyun"), ("천마신공", "Thiên Ma Thần Công"), ("선배", "tiền bối"), ("이리나", "Irina")]
    assert entries[0]["note"] == "nhân vật chính"
    assert any("sát thủ 25 tuổi" in n for n in notes)
    entries, _ = parse_data('[{"source": "다크 문", "target": "Trăng Rằm Đen", "category": "term"}]', "g.json")
    assert entries == [{"source": "다크 문", "target": "Trăng Rằm Đen", "category": "term", "note": ""}]


def test_import_and_consistency(client, book):
    pid = project(client, book, "tb-book.docx")
    r = client.post(f"/api/projects/{pid}/termbase/import-text", json={"text": DATA}).json()
    assert r == {"added": 4, "updated": 0, "notes_lines": 3}
    ov = client.get(f"/api/projects/{pid}/termbase").json()
    assert "sát thủ 25 tuổi" in ov["notes"] and len(ov["glossary"]) == 4
    # Importing again with a different rendering updates it and remembers the old one as "avoid".
    client.post(f"/api/projects/{pid}/termbase/import-text", json={"text": "선배 = sunbae"})
    g = {e["source"]: e for e in client.get(f"/api/projects/{pid}/glossary").json()}
    assert g["선배"]["target"] == "sunbae" and "tiền bối" in g["선배"]["avoid"]

    check = client.post(f"/api/projects/{pid}/termbase/check").json()
    rows = {r["source"]: r for r in check["rows"]}
    # The sample book (6 bilingual chapters, incl. 14 with an inferred boundary): 김수현 appears in each and is always "Kim Soo-hyun".
    assert rows["김수현"]["chapters"] == check["chapters_checked"] == 6 and rows["김수현"]["consistency"] == 100
    # 선배 is translated "tiền bối" in the old chapters → 0% consistent with the new choice, variant counted.
    assert rows["선배"]["consistency"] == 0 and rows["선배"]["variants"] == {"tiền bối": 6}
    assert rows["선배"]["deviating_chapters"] == [10, 11, 12, 13, 14, 15]
    assert rows["천마신공"]["chapters"] == 0


def test_ai_scan_proposals_and_review(client, book):
    pid = project(client, book, "tb-scan.docx")
    est = client.get(f"/api/projects/{pid}/termbase/scan-estimate").json()
    assert est["chapters"] == 6 and est["batches"] >= 1 and est["estimate"]["claude-opus-5-5"] > 0
    st = client.post(f"/api/projects/{pid}/termbase/scan", json={"model": "claude-opus-5-5"}).json()
    assert st["status"] == "running"
    for _ in range(400):
        ov = client.get(f"/api/projects/{pid}/termbase").json()
        if not ov["scan"]["running"]:
            break
        time.sleep(0.1)
    assert ov["scan"]["status"] == "done", ov["scan"]
    props = {p["source"]: p for p in ov["proposals"]}
    assert props["김수현"]["target"] == "Kim Soo-hyun" and props["김수현"]["category"] == "character"
    assert props["김수현"]["chapters"] == [10, 11, 12, 13, 14, 15]
    r = client.post(f"/api/projects/{pid}/termbase/proposals",
                    json={"accept": [{"source": "김수현"}, {"source": "선배", "target": "tiền bối"}], "reject": []}).json()
    assert r["added"] == 2
    ov = client.get(f"/api/projects/{pid}/termbase").json()
    assert {e["source"] for e in ov["glossary"]} == {"김수현", "선배"} and not ov["proposals"]
    assert all(e["origin"] == "ai-scan" for e in ov["glossary"])
    # A second scan skips known terms and does not resurrect decided ones.
    client.post(f"/api/projects/{pid}/termbase/scan", json={"model": "claude-opus-5-5"})
    for _ in range(400):
        ov = client.get(f"/api/projects/{pid}/termbase").json()
        if not ov["scan"]["running"]:
            break
        time.sleep(0.1)
    assert not ov["proposals"]


def test_scan_nothing(client, book):
    pid = project(client, book, "tb-none.docx")
    r = client.post(f"/api/projects/{pid}/termbase/scan", json={"from_number": 900, "to_number": 901})
    assert r.json()["error"]["code"] == "NOTHING_TO_SCAN"


def test_glossary_sent_per_chapter():
    entries = [{"source": "김수현", "target": "Kim Soo-hyun", "category": "character"},
               {"source": "천마신공", "target": "Thiên Ma Thần Công", "avoid": ["Thiên Ma Công"]},
               {"source": "Kim Su-hyeon", "target": "Kim Soo-hyun"}]       # non-Korean rule: always sent
    picked = entries_for_text(entries, "김수현은 웃었다.")
    assert [e["source"] for e in picked] == ["김수현", "Kim Su-hyeon"]
    assert glossary_prompt(picked).splitlines()[0] == "- 김수현 → Kim Soo-hyun [nhân vật]"


def test_translation_uses_termbase(client, book, tmp_path):
    from app.ai.translation_jobs import manager
    pid = project(client, book, "tb-trans.docx")
    client.post(f"/api/projects/{pid}/termbase/import-text", json={"text": DATA})
    job = {"glossary_project": pid, "auto_terms": {"다크 문": "Trăng Rằm Đen"}}
    text, notes = manager._glossary_text(job, "1920. 다크 문\n김수현은 천마신공을 펼쳤다.")
    assert "김수현 → Kim Soo-hyun" in text and "천마신공 → Thiên Ma Thần Công" in text
    assert "다크 문 → Trăng Rằm Đen" in text and "이리나" not in text       # Irina is not in this chapter
    assert "sát thủ 25 tuổi" in notes

    # Terms Claude reported while translating can be sent to the termbase for review.
    meta = client.post("/api/translate/analyze", files={"file": ("t.txt", "1. 제목\n김수현은 웃었다.\n".encode())}).json()
    j = client.post("/api/translate/jobs", json={"sid": meta["sid"], "glossary_project": pid}).json()
    for _ in range(400):
        if not client.get(f"/api/translate/jobs/{j['id']}").json()["running"]:
            break
        time.sleep(0.1)
    pid2 = project(client, book, "tb-trans2.docx")
    j2 = client.post("/api/translate/jobs", json={"sid": meta["sid"], "glossary_project": pid2}).json()
    for _ in range(400):
        if not client.get(f"/api/translate/jobs/{j2['id']}").json()["running"]:
            break
        time.sleep(0.1)
    r = client.post(f"/api/translate/jobs/{j2['id']}/save-terms").json()
    assert r["added"] == 1
    props = client.get(f"/api/projects/{pid2}/termbase").json()["proposals"]
    assert props[0]["source"] == "김수현" and props[0]["origin"] == "translation"
