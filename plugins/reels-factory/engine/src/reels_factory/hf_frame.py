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
