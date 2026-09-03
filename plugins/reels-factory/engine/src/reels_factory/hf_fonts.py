# plugins/reels-factory/engine/src/reels_factory/hf_fonts.py
"""Единственный источник правды по шрифтам в композициях HyperFrames.

Приём: собственный @font-face с data-URI под именем семейства, которого нет
в их карте алиасов (packages/parsers/src/fontAliases.ts). Тогда не срабатывает
ни подмена имён, ни латинский бандл продюсера — оба инжектора пропускают
семейство с уже объявленным @font-face.
"""
import base64
import functools
import re
import shutil
import subprocess
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parents[2] / "hyperframes" / "_fonts"

FONT_RANGES = {
    "latin": ("U+0000-00FF, U+0131, U+0152-0153, U+2000-206F, U+2074, "
              "U+20AC, U+2122, U+2212, U+2215"),
    "cyrillic": "U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116",
    "cyrillicext": ("U+0460-052F, U+1C80-1C88, U+20B4, U+2DE0-2DFF, "
                    "U+A640-A69F, U+FE2E-FE2F"),
}

# Ни Manrope, ни Unbounded (все веса, все скачанные сабсеты) не несут полный
# казахский набор в обоих регистрах — проверено fontTools по getBestCmap(),
# см. отчёт задачи. Строчные: Manrope есть ө ү һ і, нет ә ғ қ ң ұ; Unbounded
# есть только і, нет ә ғ қ ң ө ұ ү һ. Заглавные: ни Manrope, ни Unbounded не
# рисуют Ә Ғ Қ Ң Ұ вовсе; Ө Ү Һ І есть только у Manrope (в cyrillicext) — у
# Unbounded нет и их. Донор — Noto Sans (fontTools подтверждает все 9 букв,
# оба регистра), два статических инстанса (400/700), обрезанные
# fonttools.subset ровно до недостающих кодпоинтов, лежат в _fonts/_donor и
# не подхватываются глобом *.woff2. Диапазон донора для каждого семейства —
# ровно недостающие буквы, чтобы не перехватывать то, что основная гарнитура
# уже рисует верно.
DONOR_DIR = FONTS_DIR / "_donor"

DONOR_RANGES = {
    "manrope": ("U+04D9, U+0493, U+049B, U+04A3, U+04B1, "  # ә ғ қ ң ұ
                "U+04D8, U+0492, U+049A, U+04A2, U+04B0"),  # Ә Ғ Қ Ң Ұ
    "unbounded": ("U+04D9, U+0493, U+049B, U+04A3, U+04E9, U+04B1, U+04AF, "
                  "U+04BB, "  # ә ғ қ ң ө ұ ү һ
                  "U+04D8, U+0492, U+049A, U+04A2, U+04E8, U+04B0, U+04AE, "
                  "U+04BA"),  # Ә Ғ Қ Ң Ө Ұ Ү Һ
}


#: (family, weight) пары, реально присутствующие в композициях. Объясняет,
#: почему _donor_file() матчит вес донора именно так: без этого списка
#: непонятно, какие веса вообще встречаются и как они бьются на 400/700.
FAMILY_WEIGHTS = [
    ("Manrope", "500"), ("Manrope", "600"), ("Manrope", "700"),
    ("Unbounded", "600"), ("Unbounded", "700"), ("Unbounded", "800"),
]


def _donor_file(weight: str) -> Path:
    """Статический инстанс донора, ближе по насыщенности к весу гарнитуры."""
    return DONOR_DIR / ("notosans-700.woff2" if int(weight) > 550
                         else "notosans-400.woff2")

#: Строка для проверки отрисовки: русский плюс все казахские буквы в обоих
#: регистрах.
KAZAKH_PROBE = "Привет, әлем: ғ қ ң ө ұ ү һ і ӘҒҚҢӨҰҮҺІ"

#: Стили субтитров из их каталога, пригодные без замены шрифта: семейство
#: несёт кириллицу И вес отсутствует в латинском бандле продюсера.
ALLOWED_CAPTION_STYLES = (
    "caption-highlight",       # Montserrat 800
    "caption-neon-accent",     # Montserrat 800
    "caption-weight-shift",    # Montserrat 300
)

#: Темы embedded-captions на штриховых шрифтах Hershey: неизвестный символ
#: даёт пустой контур, русское слово отрисуется пустотой без ошибки.
BLOCKED_CAPTION_THEMES = frozenset({
    "aurora", "brush", "chalkboard", "graffiti", "neonsign", "spectrum",
})


@functools.lru_cache(maxsize=1)
def fonts_css() -> str:
    """@font-face с data-URI для всех woff2 в _fonts/ (имя family-weight-subset).

    Плюс по одному донорскому @font-face на каждую пару семейство+вес из
    DONOR_RANGES — см. комментарий там про недостающие казахские буквы.
    """
    faces = []
    fam_weights = set()
    for f in sorted(FONTS_DIR.glob("*.woff2")):
        fam, wght, subset = f.stem.rsplit("-", 2)
        if subset not in FONT_RANGES:
            raise ValueError(
                f"неизвестный сабсет {subset!r} в имени файла {f.name}; "
                f"известные: {sorted(FONT_RANGES)}")
        b64 = base64.b64encode(f.read_bytes()).decode("ascii")
        faces.append(
            f"@font-face{{font-family:'{fam.capitalize()}';font-style:normal;"
            f"font-weight:{wght};font-display:block;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');"
            f"unicode-range:{FONT_RANGES[subset]};}}")
        fam_weights.add((fam, wght))

    for fam, wght in sorted(fam_weights):
        donor_range = DONOR_RANGES.get(fam)
        if donor_range is None:
            continue
        b64 = base64.b64encode(_donor_file(wght).read_bytes()).decode("ascii")
        faces.append(
            f"@font-face{{font-family:'{fam.capitalize()}';font-style:normal;"
            f"font-weight:{wght};font-display:block;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');"
            f"unicode-range:{donor_range};}}")
    return "\n      ".join(faces)


# Их врезчик: скрипт скила embedded-captions. Он умнее нашего прежнего
# embed_fonts — врезает только те семейства, что реально встретились в
# font-family файла, пропускает уже объявленные и канонические, и делает это
# идемпотентно (scripts/inject-fonts.cjs:109-144). Наш врезал всё подряд, то
# есть каждый HTML утяжелялся полным набором начертаний.
CAPTIONS_SKILL = Path.home() / ".claude" / "skills" / "embedded-captions"
_INJECTOR = CAPTIONS_SKILL / "scripts" / "inject-fonts.cjs"
#: Их библиотека шрифтов. Скрипт ищет её строго по SKILL_ROOT/modes/standard/
#: fonts/fonts.css (inject-fonts.cjs:26-27), поэтому раскладку повторяем.
_LIBRARY_REL = Path("modes") / "standard" / "fonts" / "fonts.css"


def _stage_injector(work_dir: Path) -> tuple[Path, Path]:
    """Разложить их скрипт и объединённую библиотеку шрифтов в рабочей папке.

    Скрипт копируем при каждом запуске из установленного скила, а не держим
    свою копию: так он всегда их текущей версии. Библиотеку склеиваем — их
    латинские гарнитуры плюс наши кириллические с казахским донором, потому что
    их сборщик (`build-fonts-css.cjs:56-82`) знает только имена вида
    `<slug>-latin-<вес>-normal.woff2` и не умеет `unicode-range`, а без него
    донорские буквы не подставить.
    """
    root = Path(work_dir) / ".hf-fonts"
    script = root / "scripts" / "inject-fonts.cjs"
    library = root / _LIBRARY_REL
    script.parent.mkdir(parents=True, exist_ok=True)
    library.parent.mkdir(parents=True, exist_ok=True)
    if not _INJECTOR.exists():
        raise RuntimeError(
            f"не найден {_INJECTOR}; выполни "
            "npx hyperframes skills update embedded-captions")
    shutil.copyfile(_INJECTOR, script)
    theirs = (CAPTIONS_SKILL / _LIBRARY_REL)
    base = theirs.read_text(encoding="utf-8") if theirs.exists() else ""
    library.write_text(base + "\n" + fonts_css() + "\n", encoding="utf-8")
    return script, library


def inject_fonts(public_dir, *, work_dir=None) -> list[str]:
    """Врезать в композицию агента ровно те начертания, что она использует.

    Композицию по скилам HyperFrames пишет агент, и наших шрифтов там нет:
    кириллица уезжает в подменный системный шрифт, а казахские буквы не
    отрисовываются вовсе. Врезаем до гейтов и рендера, чтобы проверки мерили
    тот же текст, который увидит зритель.

    Возвращает список обработанных файлов.
    """
    public = Path(public_dir)
    pages = [str(p) for p in sorted(public.rglob("*.html"))]
    if not pages:
        return []
    script, _ = _stage_injector(Path(work_dir) if work_dir else public.parent)
    result = subprocess.run(
        ["node", str(script), str(public), *pages],
        capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(
            f"inject-fonts упал ({result.returncode}): "
            f"{(result.stderr or result.stdout)[:500]}")
    for page in pages:
        _faces_into_template(Path(page))
    return pages


#: Врезка их скрипта: один `<style>` с этим id в `<head>` страницы
#: (inject-fonts.cjs). Ищем его же, чтобы перенести, а не врезать заново.
_FACES_STYLE = re.compile(r'<style id="hf-embedded-fonts">.*?</style>\s*', re.S)
_TEMPLATE_STYLE = re.compile(r"(<template[^>]*>.*?<style[^>]*>)", re.S)


def _faces_into_template(page: Path) -> None:
    """Перенести врезанные начертания внутрь `<template>`, если корень там.

    Позиции их полки примитивов держат разметку и стиль в `<template>` — «the
    runtime clones only this template» (`registry/components/count-up/
    count-up.html:30`). Их врезчик кладёт `@font-face` в `<head>`, то есть
    снаружи, и их же линтер отвечает `font_family_without_font_face` на каждую
    такую позицию: объявления и использование он сводит в пределах одного
    корня. Под `--strict` это ошибка, то есть упавшая сборка — проверено
    живым `check` на копии `count-up`.

    Клон шаблона несёт стиль с собой, поэтому в кадре ничего не меняется:
    начертания те же, просто объявлены там, где они и применяются.
    """
    html = page.read_text(encoding="utf-8")
    faces = _FACES_STYLE.search(html)
    if not faces or "<template" not in html or faces.start() > html.index(
            "<template"):
        return
    moved = html[:faces.start()] + html[faces.end():]
    place = _TEMPLATE_STYLE.search(moved)
    if not place:
        return
    body = faces.group(0)
    page.write_text(moved[:place.end()] + body[body.index(">") + 1:
                                               body.rindex("</style>")]
                    + moved[place.end():], encoding="utf-8")
