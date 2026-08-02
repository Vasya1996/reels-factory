# plugins/reels-factory/engine/tests/test_hf_fonts.py
import base64
import io
import re

import pytest
from fontTools.ttLib import TTFont

from reels_factory import hf_fonts

KAZAKH = "әғқңөұүһіӘҒҚҢӨҰҮҺІ"

FAMILY_WEIGHTS = hf_fonts.FAMILY_WEIGHTS

_FACE_RE = re.compile(
    r"@font-face\{font-family:'(?P<fam>[^']+)';font-style:normal;"
    r"font-weight:(?P<wght>\d+);font-display:block;"
    r"src:url\(data:font/woff2;base64,(?P<b64>[^)]+)\) format\('woff2'\);"
    r"unicode-range:(?P<range>[^;]*);\}"
)


def _parse_faces(css: str) -> list[dict]:
    faces = []
    for m in _FACE_RE.finditer(css):
        faces.append({
            "fam": m.group("fam"),
            "wght": m.group("wght"),
            "range": m.group("range"),
            "bytes": base64.b64decode(m.group("b64")),
        })
    assert faces, "не нашлось ни одного @font-face — сломался формат CSS?"
    return faces


def _range_covers(range_spec: str, codepoint: int) -> bool:
    for part in range_spec.split(","):
        part = part.strip().removeprefix("U+")
        if not part:
            continue
        lo, _, hi = part.partition("-")
        if int(lo, 16) <= codepoint <= int(hi or lo, 16):
            return True
    return False


@pytest.fixture(scope="module")
def faces():
    return _parse_faces(hf_fonts.fonts_css())


@pytest.fixture(scope="module")
def cmap_cache():
    cache: dict[bytes, dict] = {}

    def get(font_bytes: bytes) -> dict:
        if font_bytes not in cache:
            cache[font_bytes] = TTFont(io.BytesIO(font_bytes)).getBestCmap()
        return cache[font_bytes]

    return get


def test_every_kazakh_letter_has_a_matching_covering_glyph(faces, cmap_cache):
    """Для каждой буквы и веса должен быть face того же семейства, чей
    unicode-range её покрывает И чей файл реально содержит такой глиф.

    Раньше тест проверял только объявленные диапазоны (FONT_RANGES) — это
    пропустило то, что сами гарнитуры не несут казахских глифов: диапазон
    был объявлен верно, а рисовать было нечем.
    """
    missing = []
    for fam, wght in FAMILY_WEIGHTS:
        candidates = [f for f in faces if f["fam"] == fam and f["wght"] == wght]
        assert candidates, f"нет ни одного @font-face для {fam} {wght}"
        for ch in KAZAKH:
            cp = ord(ch)
            covered = any(
                _range_covers(f["range"], cp) and cp in cmap_cache(f["bytes"])
                for f in candidates
            )
            if not covered:
                missing.append(f"{fam} {wght}: {ch} (U+{cp:04X})")
    assert missing == [], "нет глифа+покрывающего диапазона: " + ", ".join(missing)


def test_unknown_subset_in_filename_raises(tmp_path, monkeypatch):
    """FONT_RANGES.get(subset, '') раньше тихо давал unicode-range:; —
    безграничный @font-face без единого сигнала об ошибке. Теперь это
    должно падать явно.

    Пишем bogus-файл во временный каталог (monkeypatch подменяет FONTS_DIR),
    а не в отслеживаемый git-каталог шрифтов: обрыв процесса до unlink() в
    finally раньше оставлял мусорный файл там, где его подхватывает
    fonts_css() у всех потребителей.
    """
    monkeypatch.setattr(hf_fonts, "FONTS_DIR", tmp_path)
    bogus = tmp_path / "manrope-500-bogussubset.woff2"
    bogus.write_bytes(b"\x00")
    hf_fonts.fonts_css.cache_clear()
    try:
        with pytest.raises(ValueError):
            hf_fonts.fonts_css()
    finally:
        hf_fonts.fonts_css.cache_clear()


def test_cyrillic_ext_files_present():
    """Для каждой пары семейство+вес есть файл с расширенной кириллицей.

    Проверка на уровне веса, а не только семейства: пропуск может быть
    точечным (например, только Unbounded 800 без cyrillic-ext), пока
    остальные веса того же семейства уже покрыты.
    """
    stems = {p.stem for p in hf_fonts.FONTS_DIR.glob("*.woff2")}
    fam_weights = {s.rsplit("-", 2)[0] + "-" + s.rsplit("-", 2)[1] for s in stems}
    for fam_wght in fam_weights:
        assert f"{fam_wght}-cyrillicext" in stems, f"нет cyrillic-ext для {fam_wght}"


def test_fonts_css_embeds_every_file_plus_donor_faces(faces):
    real_files = len(list(hf_fonts.FONTS_DIR.glob("*.woff2")))
    donor_faces = len(FAMILY_WEIGHTS)  # один донорский @font-face на пару семейство+вес
    assert len(faces) == real_files + donor_faces
    assert all(f["bytes"] for f in faces)


# ---------- embed_fonts: врезка шрифтов в композицию агента ----------
#
# fonts_css() до сих пор подключался только в hyperframes_blocks.py — в наши
# собственные блоки. Композицию, которую пишет агент по скиллам HyperFrames,
# рендерит hf_render, и туда шрифты не попадали: кириллица уезжала в подменный
# системный шрифт, а казахские буквы — в пустоту.

def _write(public, name, html):
    public.mkdir(parents=True, exist_ok=True)
    (public / name).write_text(html, encoding="utf-8")
    return public / name


def test_embed_fonts_inserts_faces_before_head_close(tmp_path):
    page = _write(tmp_path / "public", "index.html",
                  "<!doctype html><html><head><title>t</title></head>"
                  "<body>Привет</body></html>")

    assert hf_fonts.embed_fonts(tmp_path / "public") == 1

    html = page.read_text(encoding="utf-8")
    assert "@font-face" in html
    assert html.index("@font-face") < html.index("</head>")


def test_embed_fonts_is_idempotent(tmp_path):
    page = _write(tmp_path / "public", "index.html",
                  "<html><head></head><body></body></html>")

    hf_fonts.embed_fonts(tmp_path / "public")
    once = page.read_text(encoding="utf-8")
    hf_fonts.embed_fonts(tmp_path / "public")
    twice = page.read_text(encoding="utf-8")

    assert once == twice
    assert twice.count("@font-face") == once.count("@font-face")


def test_embed_fonts_covers_every_html_including_nested(tmp_path):
    public = tmp_path / "public"
    _write(public, "index.html", "<html><head></head><body></body></html>")
    _write(public / "cards", "card-01.html", "<html><head></head><body></body></html>")

    assert hf_fonts.embed_fonts(public) == 2
    assert "@font-face" in (public / "cards" / "card-01.html").read_text(encoding="utf-8")


def test_embed_fonts_handles_page_without_head(tmp_path):
    page = _write(tmp_path / "public", "index.html", "<div>Привет, әлем</div>")

    assert hf_fonts.embed_fonts(tmp_path / "public") == 1
    assert "@font-face" in page.read_text(encoding="utf-8")
