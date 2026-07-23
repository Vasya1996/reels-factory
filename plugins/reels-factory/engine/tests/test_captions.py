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


def test_popword_одно_слово_на_событие(tmp_path):
    path = tmp_path / "caps.ass"
    build_ass(WORDS, path, style="popword")
    content = path.read_text(encoding="utf-8")
    assert content.count("Dialogue:") == 4        # по событию на слово
    assert "\\t(0,70,\\fscx106" in content        # пружинка
    assert "\\frz" in content                     # чередующийся наклон
    assert "\\kf" not in content                  # караоке тут нет

def test_popword_акцентное_слово_красится(tmp_path):
    path = tmp_path / "caps.ass"
    build_ass(WORDS, path, style="popword", keywords=["тест"])
    content = path.read_text(encoding="utf-8")
    line = next(l for l in content.splitlines() if "ТЕСТ" in l)
    assert "\\1c&H0000F0FF&" in line
    line2 = next(l for l in content.splitlines() if "ПРИВЕТ" in l)
    assert "\\1c" not in line2

def test_boxed_плашка_и_фейд(tmp_path):
    path = tmp_path / "caps.ass"
    build_ass(WORDS, path, style="boxed")
    content = path.read_text(encoding="utf-8")
    assert ",3," in content.split("Style: Cap,")[1]  # BorderStyle=3 — плашка
    assert "\\fad(80,60)" in content
    assert "\\kf" not in content

def test_неизвестный_стиль_понятная_ошибка(tmp_path):
    try:
        build_ass(WORDS, tmp_path / "x.ass", style="comic")
        assert False
    except ValueError as e:
        assert "comic" in str(e)
