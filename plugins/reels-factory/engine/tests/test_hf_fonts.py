# plugins/reels-factory/engine/tests/test_hf_fonts.py
import re
from reels_factory import hf_fonts

KAZAKH = "әғқңөұүһі"


def test_kazakh_letters_covered_by_some_range():
    """Каждая казахская буква попадает хотя бы в один unicode-range."""
    ranges = []
    for spec in hf_fonts.FONT_RANGES.values():
        for part in spec.split(","):
            part = part.strip().removeprefix("U+")
            if not part:
                continue
            lo, _, hi = part.partition("-")
            ranges.append((int(lo, 16), int(hi or lo, 16)))
    uncovered = [c for c in KAZAKH
                 if not any(lo <= ord(c) <= hi for lo, hi in ranges)]
    assert uncovered == [], f"вне диапазонов: {uncovered}"


def test_cyrillic_ext_files_present():
    """Для каждой пары семейство+вес есть файл с казахскими глифами.

    Проверка на уровне веса, а не только семейства: пропуск может быть
    точечным (например, только Unbounded 800 без cyrillic-ext), пока
    остальные веса того же семейства уже покрыты.
    """
    stems = {p.stem for p in hf_fonts.FONTS_DIR.glob("*.woff2")}
    fam_weights = {s.rsplit("-", 2)[0] + "-" + s.rsplit("-", 2)[1] for s in stems}
    for fam_wght in fam_weights:
        assert f"{fam_wght}-cyrillicext" in stems, f"нет cyrillic-ext для {fam_wght}"


def test_fonts_css_embeds_every_file():
    css = hf_fonts.fonts_css()
    assert css.count("@font-face") == len(list(hf_fonts.FONTS_DIR.glob("*.woff2")))
    assert "data:font/woff2;base64," in css
    assert re.search(r"font-family:'(Manrope|Unbounded)'", css)
