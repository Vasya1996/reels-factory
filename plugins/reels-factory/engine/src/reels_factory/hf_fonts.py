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
