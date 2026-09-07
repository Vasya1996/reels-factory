"""Спека оформления ролика — их `frame.md`.

Файл живёт в корне прогона, как велит их порядок разрешения
`frame.md → design.md → DESIGN.md`, имя всегда строчными
(hyperframes-creative/references/design-spec.md:16-27). Frontmatter —
нормативный слой: hex дословно, «не выдумывать и не округлять»
(design-spec.md:9-12); проза — намерение, её читает человек и агент,
код — только frontmatter.

Заполняет спеку агент-планировщик: их канон разрешает и пресет, и bespoke
от агента (design-spec.md:33). Код здесь только читает и держит дефолты:
спека может не появиться (агент упал, старый план) — ролик обязан
собраться и без неё, прежним видом.

Гарнитуры в спеке не выбираются: кириллицу и казахский в проекте несут
только Manrope и Unbounded (hf_fonts.py:51-54), и врезаются они нашим
@font-face. Их правило «serif + sans» выполняем по духу, а не по букве:
пара контрастна по нескольким осям — широкий экспрессивный дисплей против
нейтрального текстового (typography.md:178 разрешает ровно это).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

#: Тон титров — их таблица подбора стиля по тону расшифровки
#: (media-use/audio/references/captions/authoring.md:43-49).
CAPTION_TONES = ("hype", "corporate", "tutorial", "storytelling", "social")

#: Дефолтная тема — то, как ролик выглядел до спеки. Нейтральный тёмный фон
#: (не чистый #000 — house-style.md:30), белый текст, красный акцент их же
#: компонента субтитров (caption-highlight.html:91).
DEFAULTS = {
    "colors": {"bg": "#0b0b0c", "ink": "#ffffff", "accent": "#ff1745"},
    "captionTone": "hype",
    "name": "по умолчанию",
}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.S)


def _clean_hex(value, fallback: str) -> str:
    value = str(value or "").strip()
    return value.lower() if _HEX.match(value) else fallback


def luminance(color: str) -> float:
    """Относительная яркость цвета по WCAG, 0 (чёрный) … 1 (белый).

    Та же формула, которой их проверка контраста судит текст
    (`packages/cli/src/commands/contrast-bg.ts:24-45`): сначала канал
    линеаризуется, потом складывается с весами глаза. Считать «тёмный ли фон»
    по одной сумме каналов нельзя — жёлтый и синий одной суммы читаются
    по-разному.
    """
    value = _clean_hex(color, "#000000").lstrip("#")
    channels = []
    for part in (value[0:2], value[2:4], value[4:6]):
        c = int(part, 16) / 255
        channels.append(c / 12.92 if c <= 0.04045
                        else ((c + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


#: Граница «тёмный/светлый фон». 0,18 — середина между чёрным и белым по
#: восприятию (яркость 50% серого), а не по числу: линейная середина 0,5
#: считала бы светлыми почти все насыщенные цвета.
DARK_BG_MAX = 0.18


def dark_frame(theme: dict | None) -> bool:
    """Тёмная ли палитра ролика. По ней выбирается начертание знака бренда,
    цвет значка и цвет карточки: на светлом ролике белый знак пропадёт ровно
    так же, как чёрный на тёмном."""
    colors = (theme or {}).get("colors") or DEFAULTS["colors"]
    return luminance(colors.get("bg") or DEFAULTS["colors"]["bg"]) <= DARK_BG_MAX


def contrast_ratio(first: str, second: str) -> float:
    """Отношение контраста между двумя цветами по WCAG — тем же расчётом,
    которым их аудит контраста судит текст (`(L₁+0,05)/(L₂+0,05)`,
    `packages/cli/src/commands/contrast-bg.ts:34-40`)."""
    lum_first, lum_second = luminance(first), luminance(second)
    lighter, darker = max(lum_first, lum_second), min(lum_first, lum_second)
    return (lighter + 0.05) / (darker + 0.05)


#: Их порог AA для крупного текста (`contrast-bg.ts:43-45`,
#: `contrast-audit.browser.js:452`: `large ? ratio >= 3 : ratio >= 4.5`).
#: Титр рисует 80px/вес 800 (`caption-highlight.html:73-74`) — их же правило
#: «крупного» текста — `fontSize>=24 || (fontSize>=19 && fontWeight>=700)»
#: (`contrast-audit.browser.js:231`) берёт этот случай с большим запасом.
REQUIRED_CONTRAST_LARGE = 3.0


def highlight_ink(ink: str, accent: str, dark: str) -> str:
    """Цвет букв слова на плашке подсветки титра — не цвет `ink` вообще.

    `ink` красит текст титра постоянно (`--hf-caption-primary`,
    `caption-highlight.html:76`), а плашка `accent` встаёт под слово лишь на
    время подсветки (`--hf-caption-accent`, `caption-highlight.html:92-93`).
    Пока агент выбирал акцент из тёмных/насыщенных тонов (красный, синий,
    оранжевый), `ink` — обычно белый — держал их же порог 3:1 сам собой; на
    светлом акценте (бирюза, жёлтый, салатовый) тот же белый на плашке падает
    ниже порога, и это выясняется только их проверкой после сборки
    (`rb0908-ai-employee`, `contrast_aa_failure` 2,6–2,9:1 у `rgb(245,247,251)`
    на `rgb(70,166,141)`).

    Правило: `ink` остаётся, если сам держит 3:1 против `accent` — акцент
    агента не трогаем, меняем только буквы. Не держит — берём `dark`
    (обычно `colors["bg"]`, тёмная база темы, а не выдуманный чёрный): акцент,
    из-за которого светлый `ink` не прошёл, по построению заметно светлее
    тёмной базы палитры, так что `dark` против него почти всегда проходит
    (проверено для `rb0908-ai-employee` — bg #0b0f1a против accent
    rgb(70,166,141) даёт 6,47:1). Патологию — когда даже
    `dark` не держит — их же формула гарантирует прошедшим один из полюсов
    чёрный/белый: контраст с фоном любой яркости у чёрного или у белого не
    ниже 4,58:1 в худшей точке (яркость фона 0,179, `contrast-bg.ts:47-74`,
    `suggestCompliantForegroundColor`), поэтому крайний случай берёт более
    контрастный из них, а не гадает.
    """
    if contrast_ratio(ink, accent) >= REQUIRED_CONTRAST_LARGE:
        return ink
    if contrast_ratio(dark, accent) >= REQUIRED_CONTRAST_LARGE:
        return dark
    return ("#000000"
            if contrast_ratio("#000000", accent) >= contrast_ratio("#ffffff", accent)
            else "#ffffff")


def read_frame(rdir) -> dict:
    """Тема ролика из `frame.md`. Нет файла или он бит — дефолты.

    Возвращает `{"colors": {bg, ink, accent}, "captionTone", "name"}` —
    ровно то, что композиция умеет применить сегодня. Остальное из спеки
    (typography, spacing, components) не теряется — файл лежит рядом с
    композицией, и следующие шаги оформления будут читать его же.
    """
    theme = {"colors": dict(DEFAULTS["colors"]),
             "captionTone": DEFAULTS["captionTone"],
             "name": DEFAULTS["name"]}
    path = Path(rdir) / "frame.md"
    if not path.exists():
        return theme
    match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
    if not match:
        return theme
    try:
        spec = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return theme
    if not isinstance(spec, dict):
        return theme

    colors = spec.get("colors") if isinstance(spec.get("colors"), dict) else {}
    for key in ("bg", "ink", "accent"):
        theme["colors"][key] = _clean_hex(colors.get(key),
                                          DEFAULTS["colors"][key])
    tone = str(spec.get("captionTone") or "").strip().lower()
    if tone in CAPTION_TONES:
        theme["captionTone"] = tone
    if spec.get("name"):
        theme["name"] = str(spec["name"]).strip()
    return theme
