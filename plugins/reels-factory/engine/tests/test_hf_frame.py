"""Спека оформления frame.md: frontmatter нормативен, дефолты держат сборку."""
import pytest

from reels_factory.hf_frame import (
    CAPTION_TONES, DEFAULTS, REQUIRED_CONTRAST_LARGE, contrast_ratio,
    dark_frame, highlight_ink, luminance, read_frame,
)


@pytest.mark.parametrize("color,expected", [
    ("#000000", 0.0),
    ("#ffffff", 1.0),
    ("#808080", 0.22),      # 50% серый по восприятию, а не по числу
])
def test_яркость_считается_их_формулой(color, expected):
    """Та же формула, которой их проверка контраста судит текст."""
    assert round(luminance(color), 2) == expected


@pytest.mark.parametrize("bg,dark", [
    ("#120e1c", True),      # наша тёмная палитра
    ("#0b0b0c", True),
    ("#f5f2ec", False),     # светлый ролик — пользователь вправе его выбрать
    ("#ffd23f", False),     # насыщенный жёлтый светлее, чем кажется числу
    ("#2756ff", True),      # насыщенный синий темнее, чем кажется числу
])
def test_тёмная_палитра_отличается_от_светлой(bg, dark):
    """От этого зависит начертание знака бренда и цвет значка: на светлом
    ролике белый знак пропадёт ровно так же, как чёрный на тёмном."""
    assert dark_frame({"colors": {"bg": bg}}) is dark


def test_без_темы_считаем_палитру_по_умолчанию():
    assert dark_frame(None) is True


@pytest.mark.parametrize("a,b,ratio", [
    ("#ffffff", "#000000", 21.0),   # чистый чёрный/белый — предельный случай
    ("#948494", "#948494", 1.0),    # цвет с самим собой — 1:1
])
def test_контраст_считается_их_формулой(a, b, ratio):
    """`(L₁+0,05)/(L₂+0,05)` — их же расчёт (`contrast-bg.ts:34-40`)."""
    assert round(contrast_ratio(a, b), 2) == ratio


def test_контраст_симметричен():
    """Порядок аргументов не должен решать, кто светлее — их формула берёт
    больший из двух знаменателей сама (`contrast-bg.ts:37-39`)."""
    assert contrast_ratio("#5ee0c0", "#f5f7fb") == contrast_ratio("#f5f7fb", "#5ee0c0")


def test_граница_3_к_1_держит_белый_ровно_до_неё():
    """#949494 против белого — 3,03:1 (держит их порог для крупного текста),
    #959595 — уже 3,00:1 не набирает. Соседние оттенки серого по одному шагу
    канала, не выдуманные числа."""
    assert contrast_ratio("#ffffff", "#949494") >= REQUIRED_CONTRAST_LARGE
    assert contrast_ratio("#ffffff", "#959595") < REQUIRED_CONTRAST_LARGE


def test_подсветка_мятным_акцентом_топит_белый_текст_ниже_порога():
    """`rb0908-ai-employee` (прод, 07.09.2026): `frame.md` — ink #f5f7fb
    (почти белый), accent #5ee0c0 (мятный). Их `check.json` замерил живой
    рендер плашки в rgb(70,166,141) — темнее самого accent из-за
    `color-mix` в `.hl-word-bg`'s градиенте (`caption-highlight.html:90-94`)
    — и дал 2,76:1, ниже их порога 3:1 для крупного текста."""
    ink, accent = "#f5f7fb", "#46a68d"  # rgb(70,166,141)
    assert contrast_ratio(ink, accent) < REQUIRED_CONTRAST_LARGE


def test_подсветка_бирюзой_даёт_тёмный_текст_из_палитры():
    """Акцент agent'а не трогаем — заменяем только буквы на плашке, тёмным
    из этой же темы (`bg`), а не выдуманным чёрным."""
    assert highlight_ink("#f5f7fb", "#46a68d", "#0b0f1a") == "#0b0f1a"


def test_подсветка_красным_акцентом_держит_белый_текст():
    """Насыщенный тёмный акцент (как в прежних роликах) держит порог сам —
    буквы остаются `ink`, а не заменяются без нужды."""
    assert highlight_ink("#ffffff", "#dc3c28", "#0b0b0c") == "#ffffff"


def test_подсветка_на_границе_3_к_1():
    """Ровно на границе (см. `test_граница_3_к_1_держит_белый_ровно_до_неё`)
    — по одну сторону `ink` остаётся, по другую заменяется."""
    assert highlight_ink("#ffffff", "#949494", "#000000") == "#ffffff"
    assert highlight_ink("#ffffff", "#959595", "#000000") == "#000000"


def test_подсветка_если_и_тёмный_из_палитры_не_держит_порог():
    """Патология — оба соседних средних тона (`ink`=белый и `dark`=#969696)
    не дотягивают до 3:1 против `accent`=#a0a0a0 (2,62:1 и 1,13:1) — берёт
    более контрастный полюс (здесь чёрный, 8,03:1), а не роняет сборку без
    ответа (их формула гарантирует ≥4,58:1 у одного из двух в любой точке,
    `contrast-bg.ts:47-74`)."""
    assert highlight_ink("#ffffff", "#a0a0a0", "#969696") == "#000000"


def _write(tmp_path, text):
    (tmp_path / "frame.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_без_спеки_собирается_прежний_вид(tmp_path):
    theme = read_frame(tmp_path)
    assert theme["colors"] == DEFAULTS["colors"]
    assert theme["captionTone"] in CAPTION_TONES


def test_спека_читается_из_frontmatter(tmp_path):
    theme = read_frame(_write(tmp_path, (
        "---\n"
        "version: 1\n"
        "name: тёплый кирпич\n"
        "colors:\n"
        '  bg: "#140d0a"\n'
        '  ink: "#fff7f0"\n'
        '  accent: "#FF5A36"\n'
        "captionTone: corporate\n"
        "---\n\nПроза о намерении.\n")))
    assert theme["colors"] == {"bg": "#140d0a", "ink": "#fff7f0",
                               "accent": "#ff5a36"}
    assert theme["captionTone"] == "corporate"
    assert theme["name"] == "тёплый кирпич"


def test_мусор_в_полях_не_роняет_сборку(tmp_path):
    """Спеку пишет агент; битый hex или чужой тон — дефолт, а не авария."""
    theme = read_frame(_write(tmp_path, (
        "---\ncolors:\n  bg: красный\n  accent: \"#12345\"\n"
        "captionTone: эпичный\n---\n")))
    assert theme["colors"]["bg"] == DEFAULTS["colors"]["bg"]
    assert theme["colors"]["accent"] == DEFAULTS["colors"]["accent"]
    assert theme["captionTone"] == DEFAULTS["captionTone"]


def test_битый_yaml_не_роняет_сборку(tmp_path):
    theme = read_frame(_write(tmp_path, "---\ncolors: [неверно\n---\n"))
    assert theme["colors"] == DEFAULTS["colors"]
