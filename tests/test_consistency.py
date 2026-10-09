from app.ai.consistency import example_pairs, with_examples

PREV = [
    {"number": 5, "ko_paragraphs": ["“형, 어디 가?”", "수현이 웃었다.", "“날씨가 좋네.”"],
     "vi_paragraphs": ["“Anh, anh đi đâu thế?”", "Soo-hyun cười.", "“Trời đẹp nhỉ.”"]},
    {"number": 4, "ko_paragraphs": ["“형, 밥 먹었어?”", "extra"], "vi_paragraphs": ["“Anh ăn cơm chưa?”"]},   # misaligned -> skipped
]


def test_examples_follow_address_words_and_names():
    pairs = example_pairs(PREV, "“형, 수현아!” 그가 불렀다.", ["수현"])
    assert [p[0] for p in pairs] == [5] and pairs[0][2] == "“Anh, anh đi đâu thế?”"      # dialogue + shared 형; narration, no-match line, misaligned chapter dropped
    assert example_pairs(PREV, "아무 상관 없는 문장", ["수현"]) == []


def test_with_examples_appends_to_notes():
    notes, n = with_examples("Ghi chú truyện", PREV, "“형!”", [])
    assert n == 1 and notes.startswith("Ghi chú truyện\n\n") and "[Ch 5] “형, 어디 가?” → “Anh, anh đi đâu thế?”" in notes
    assert with_examples("x", PREV, "무관", []) == ("x", 0)
