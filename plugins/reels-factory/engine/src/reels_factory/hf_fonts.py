# plugins/reels-factory/engine/src/reels_factory/hf_fonts.py
"""Единственный источник правды по шрифтам в композициях HyperFrames.

Приём: собственный @font-face с data-URI под именем семейства, которого нет
в их карте алиасов (packages/parsers/src/fontAliases.ts). Тогда не срабатывает
ни подмена имён, ни латинский бандл продюсера — оба инжектора пропускают
семейство с уже объявленным @font-face.
"""
import base64
import functools
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parents[2] / "hyperframes" / "_fonts"

FONT_RANGES = {
    "latin": ("U+0000-00FF, U+0131, U+0152-0153, U+2000-206F, U+2074, "
              "U+20AC, U+2122, U+2212, U+2215"),
    "cyrillic": "U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116",
    "cyrillicext": ("U+0460-052F, U+1C80-1C88, U+20B4, U+2DE0-2DFF, "
                    "U+A640-A69F, U+FE2E-FE2F"),
}

#: Строка для проверки отрисовки: русский плюс все казахские буквы.
KAZAKH_PROBE = "Привет, әлем: ғ қ ң ө ұ ү һ і"

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
    """@font-face с data-URI для всех woff2 в _fonts/ (имя family-weight-subset)."""
    faces = []
    for f in sorted(FONTS_DIR.glob("*.woff2")):
        fam, wght, subset = f.stem.rsplit("-", 2)
        b64 = base64.b64encode(f.read_bytes()).decode("ascii")
        faces.append(
            f"@font-face{{font-family:'{fam.capitalize()}';font-style:normal;"
            f"font-weight:{wght};font-display:block;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');"
            f"unicode-range:{FONT_RANGES.get(subset, '')};}}")
    return "\n      ".join(faces)
