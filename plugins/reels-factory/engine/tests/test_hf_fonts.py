# plugins/reels-factory/engine/tests/test_hf_fonts.py
import base64
import io
import re
import shutil

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


# ---------- inject_fonts: врезка шрифтов их скриптом ----------
#
# Врезает не наш код, а их `scripts/inject-fonts.cjs` из скила
# embedded-captions: он ставит только те семейства, что реально встретились в
# font-family файла. Наш прежний embed_fonts врезал всё подряд — каждый HTML
# утяжелялся полным набором начертаний.
#
# Библиотеку шрифтов при этом собираем мы: их сборщик знает только имена вида
# `<slug>-latin-<вес>-normal.woff2` и не умеет unicode-range, а без него
# казахские буквы из донорского шрифта не подставить.

pytestmark_node = pytest.mark.skipif(
    shutil.which("node") is None or not hf_fonts._INJECTOR.exists(),
    reason="нужен node и установленный скил embedded-captions")


def _write(public, name, html):
    public.mkdir(parents=True, exist_ok=True)
    (public / name).write_text(html, encoding="utf-8")
    return public / name


def test_библиотека_склеивает_их_шрифты_с_нашими(tmp_path):
    _, library = hf_fonts._stage_injector(tmp_path)
    css = library.read_text(encoding="utf-8")
    assert "Manrope" in css and "unicode-range" in css


@pytestmark_node
def test_врезаются_только_использованные_гарнитуры(tmp_path):
    page = _write(tmp_path / "public", "index.html",
                  "<!doctype html><html><head><style>"
                  ".t{font-family:'Manrope',sans-serif}"
                  "</style></head><body class=t>Привет, әлем</body></html>")

    hf_fonts.inject_fonts(tmp_path / "public", work_dir=tmp_path)

    html = page.read_text(encoding="utf-8")
    assert "@font-face" in html
    assert "Manrope" in html
    # Unbounded в файле не встречается — врезать его незачем
    assert "Unbounded" not in html


@pytestmark_node
def test_врезка_идемпотентна(tmp_path):
    page = _write(tmp_path / "public", "index.html",
                  "<html><head><style>b{font-family:Manrope}</style></head>"
                  "<body><b>Привет</b></body></html>")

    hf_fonts.inject_fonts(tmp_path / "public", work_dir=tmp_path)
    once = page.read_text(encoding="utf-8")
    hf_fonts.inject_fonts(tmp_path / "public", work_dir=tmp_path)

    assert page.read_text(encoding="utf-8") == once


@pytestmark_node
def test_обрабатываются_все_html_включая_вложенные(tmp_path):
    public = tmp_path / "public"
    _write(public, "index.html",
           "<html><head><style>b{font-family:Manrope}</style></head><body></body></html>")
    _write(public / "cards", "card-01.html",
           "<html><head><style>b{font-family:Unbounded}</style></head><body></body></html>")

    assert len(hf_fonts.inject_fonts(public, work_dir=tmp_path)) == 2
    card = (public / "cards" / "card-01.html").read_text(encoding="utf-8")
    assert "@font-face" in card and "Unbounded" in card


@pytestmark_node
def test_врезка_уезжает_внутрь_шаблона_позиции(tmp_path):
    """Позиции их полки держат разметку и стиль в `<template>`: рантайм клонирует
    только его. Врезчик кладёт начертания в `<head>`, то есть снаружи, и их
    линтер отвечает `font_family_without_font_face` — под `--strict` это
    упавшая сборка. Проверено живым `check` на копии `count-up`.
    """
    public = tmp_path / "public"
    _write(public, "count-up--s-02.html",
           "<html><head><title>t</title></head><body><template>"
           '<div id="root" data-composition-id="count-up--s-02" '
           'data-width="1080" data-height="397">'
           "<style>#root{font-family:'Manrope',sans-serif}</style>"
           "<b>Привет</b></div></template></body></html>")

    hf_fonts.inject_fonts(public, work_dir=tmp_path)
    page = (public / "count-up--s-02.html").read_text(encoding="utf-8")
    assert "@font-face" in page
    assert page.index("@font-face") > page.index("<template>"), (
        "начертания остались снаружи шаблона — их линтер их не увидит")
    assert 'id="hf-embedded-fonts"' not in page.split("<template>")[0]


def test_комментарий_с_словом_шаблон_не_подменяет_настоящий_тег(tmp_path):
    """Шапка-комментарий части позиций полки объясняет контракт словами «the
    runtime clones only <template> contents» — то есть несёт буквальную
    подстроку `<template>` РАНЬШЕ настоящего тега (`avatar-cloud.html:38-39`).
    Старый код искал тег как `html.index("<template")` — находил прозу,
    решал, что врезка (стоящая после неё) уже позже корня, и не переносил её
    внутрь `<template>`. Живым `check --strict` это било `avatar-cloud`
    находкой `font_family_without_font_face`, хотя `@font-face` в файле был.
    """
    page = _write(
        tmp_path / "public", "avatar-cloud--s-01.html",
        "<!--\n"
        "  #root fills the host with inset:0. The runtime clones only\n"
        "  <template> contents; styles and markup live inside it.\n"
        "-->\n"
        '<style id="hf-embedded-fonts">@font-face{font-family:\'Manrope\';'
        "font-weight:500;src:url(data:font/woff2;base64,AA==)}</style>\n"
        "<div>\n"
        "  <template>\n"
        '    <div id="root" data-composition-id="avatar-cloud" '
        'data-width="1080" data-height="1920">'
        "<style>#root{font-family:'Manrope',sans-serif}</style>"
        "<b>Привет</b></div>\n"
        "  </template>\n"
        "</div>\n")

    hf_fonts._faces_into_template(page)

    result = page.read_text(encoding="utf-8")
    real_template = result.index("<template>", result.index("<div>"))
    assert result.index("@font-face") > real_template, (
        "начертания остались до настоящего тега — их линтер их не увидит")
    assert 'id="hf-embedded-fonts"' not in result[:real_template]
