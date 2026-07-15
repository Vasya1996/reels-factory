from reels_factory.captions import build_ass

WORDS = [
    {"start": 0.0, "end": 0.30, "text": "привет"},
    {"start": 0.35, "end": 0.60, "text": "это"},
    {"start": 0.65, "end": 0.90, "text": "тест"},
    {"start": 0.95, "end": 1.20, "text": "рилса"},
]


def test_build_ass_валидный_заголовок(tmp_path):
    out = build_ass(WORDS, tmp_path / "caps.ass")
    content = open(out, encoding="utf-8").read()
    assert "[Script Info]" in content
    assert "[V4+ Styles]" in content
    assert "[Events]" in content
    assert "Style: Cap," in content
    assert "Dialogue:" in content


def test_build_ass_караоке_теги(tmp_path):
    path = tmp_path / "caps.ass"
    build_ass(WORDS, path)
    content = path.read_text(encoding="utf-8")
    assert "\\kf" in content   # подсветка текущего слова
    assert "\\k" in content    # тег паузы перед словом (gap > 0.02с)


def test_build_ass_текст_капсом(tmp_path):
    path = tmp_path / "caps.ass"
    build_ass(WORDS, path)
    content = path.read_text(encoding="utf-8")
    assert "ПРИВЕТ" in content
    assert "привет" not in content
