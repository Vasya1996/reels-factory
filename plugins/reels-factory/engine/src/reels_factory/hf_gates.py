"""Проверка раскадровки, которую вернул агент-сборщик.

Здесь только то, чего не знает их `hyperframes check`: он судит отрисованную
композицию (переполнение кадра, перекрытые надписи, контраст — коды
`canvas_overflow`, `text_box_overflow`, `text_occluded` в
`packages/cli/src/commands/layout-audit.browser.js:472-1018`), а раскадровку не
читает вовсе — по их же словам, `storyboard.json` не парсит ни одна команда
(talking-head-recut/SKILL.md:604-606).

Значит наше здесь: схема, сетка кадров, плотность карточек и закрытые
интервалы без ведущей. Лицо и подвижность ведущей меряются на живой композиции
в `hf_probe.py` — раскадровка о них врать умеет, DOM нет.
"""
from __future__ import annotations

import re
from pathlib import Path

from reels_factory.config import FPS
from reels_factory.hf_layout import (
    ALLOWED_ZONES, FULL_FRAME_ZONES, avatar_gaps, quantize,
)

#: Базовый темп по длительности ролика — таблица «Step 1 — base pace by
#: duration» из talking-head-recut/SKILL.md:206-214. Ключ — верхняя граница
#: длительности в секундах.
BASE_PACE = ((60, 6.0, 8.0), (180, 8.0, 12.0), (600, 12.0, 20.0),
             (1800, 20.0, 35.0), (float("inf"), 30.0, 60.0))

#: Множители плотности речи — «Step 2 — density multiplier», там же:216-222.
#: Крайние значения задают всю вилку допустимого числа карточек.
DENSITY_MIN, DENSITY_MAX = 0.7, 1.5

#: Пол числа карточек, зафиксированный скилом: «minimum 5 cards» (там же:203).
MIN_CARDS = 5


def density_bounds(duration: float) -> tuple[int, int]:
    """Сколько карточек допускает их формула плотности при такой длительности.

    Формула (SKILL.md:224-229): secPerCard = basePace × densityMultiplier,
    cardCount = max(5, round(videoDurationSec / secPerCard)). Плотность речи
    выбирает агент, поэтому проверяем не число, а вилку: от самой медленной
    подачи до самой частой.
    """
    duration = float(duration)
    # самая медленная подача даёт самые длинные карточки, значит их меньше всего
    longest, shortest = next(
        (upper * DENSITY_MAX, lower * DENSITY_MIN)
        for edge, lower, upper in BASE_PACE if duration < edge
    )
    return (max(MIN_CARDS, round(duration / longest)),
            max(MIN_CARDS, round(duration / shortest)))


def _schema_problems(storyboard: dict) -> list[str]:
    """Расхождения с их схемой v3 (SKILL.md:130-165, 610-616)."""
    problems = []
    if storyboard.get("schemaVersion") != 3:
        problems.append(
            f'schemaVersion={storyboard.get("schemaVersion")!r}, ожидается 3')
    for field in ("composition", "videoTrack", "subtitles", "cards"):
        if field not in storyboard:
            problems.append(f"нет поля {field}")
    composition = storyboard.get("composition") or {}
    if not isinstance(composition, dict) or "durationSeconds" not in composition:
        problems.append("composition.durationSeconds не задан")
    video = storyboard.get("videoTrack") or {}
    if not isinstance(video, dict) or not video.get("bounds"):
        problems.append("videoTrack.bounds не задан — геометрия ведущей живёт там")

    for card in storyboard.get("cards") or []:
        card_id = card.get("id", "?")
        for field in ("intent", "contentHints", "accentIndex"):
            if field not in card:
                problems.append(f"{card_id}: нет поля {field}")
        # Поля прошлого контракта: мы просили их сверх схемы, и они противоречат
        # videoTrack.bounds — соблюсти оба разом нельзя, значит остаётся их.
        for ours in ("contentRect", "videoRect"):
            if ours in card:
                problems.append(f"{card_id}: поле {ours} их схемой не предусмотрено")
    return problems


#: Растровые вставки. Векторные иконки сюда не входят намеренно: нарисованный
#: значок — это не картинка под смысл фразы.
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")

_ASSET_REF = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+)["']"""
                        r"""|url\(\s*["']?([^"')]+)["']?\s*\)""", re.I)


def check_media(rdir) -> dict:
    """Вставки взяты из каталога картинок, а не нарисованы текстом.

    Прошлый прогон вернул ролик, где графики не было вовсе: ведущая, субтитры и
    текстовый оверлей. Проверяем два независимых следа — что `media-use` вообще
    ходил (он ведёт свой реестр, `media-use/references/resolve.md`), и что
    подобранный файл действительно подключён в композицию.
    """
    rdir = Path(rdir)
    public = rdir / "public"
    index = public / "index.html"
    if not index.exists():
        return {"D16_media_use": f"FAIL: нет композиции {index}"}

    # Смотрим все страницы композиции, а не только корневую: блок каталога —
    # отдельный файл, и картинка вполне может жить внутри него.
    used = []
    for page in sorted(public.rglob("*.html")):
        for src, url in _ASSET_REF.findall(page.read_text(encoding="utf-8")):
            ref = (src or url).split("?")[0].split("#")[0]
            if ref.startswith(("http://", "https://", "data:")):
                continue
            if not ref.lower().endswith(IMAGE_SUFFIXES):
                continue
            if (page.parent / ref).exists() or (public / ref).exists():
                used.append(ref)

    ledgers = [p for p in rdir.rglob(".media/manifest.jsonl")]
    problems = []
    if not ledgers:
        problems.append("нет реестра media-use (.media/manifest.jsonl) — "
                        "картинки не подбирались")
    if not used:
        problems.append("в композиции нет ни одной локальной картинки")
    return {"D16_media_use": "PASS" if not problems
            else "FAIL: " + "; ".join(problems)}


def check_storyboard(storyboard: dict, *, clips: list[dict] | None = None,
                     duration: float = 0.0) -> dict:
    """Гейты раскадровки. PASS либо FAIL с перечислением карточек."""
    cards = storyboard.get("cards") or []
    grid_bad, zone_bad = [], []

    for card in cards:
        card_id = card.get("id", "?")
        if card.get("zone") not in ALLOWED_ZONES:
            zone_bad.append(f'{card_id}: зона {card.get("zone")!r} не разрешена')
        for field in ("startSec", "endSec"):
            if field not in card:
                grid_bad.append(f"{card_id}: нет поля {field}")
                continue
            value = float(card[field])
            if abs(value - quantize(value)) > 0.0005:
                grid_bad.append(f"{card_id}: {field}={value} вне сетки кадров")

    # Плотность. Прошлый прогон вернул 34 «карточки» средней длиной 1,7 с — это
    # были группы субтитров, настоящей графики ноль. Пустая раскадровка при этом
    # проходила все проверки: цикл по пустому списку не спотыкается ни разу.
    density_bad = []
    low, high = density_bounds(duration)
    if duration > 0 and not low <= len(cards) <= high:
        density_bad.append(
            f"карточек {len(cards)}, а формула плотности при {duration:g} с "
            f"допускает от {low} до {high}; субтитры карточками не считаются")

    # Интервал без ведущей закрывается ЦЕПОЧКОЙ полноэкранных карточек, а не
    # одной: разбить показ на титул и список — нормальное монтажное решение.
    # Допуск в кадр — на зазоры, которые агент оставляет между карточками.
    frame = 1.0 / FPS
    spans = sorted(
        (float(c.get("startSec", 0)), float(c.get("endSec", 0)))
        for c in cards if c.get("zone") in FULL_FRAME_ZONES
    )
    cover_bad = []
    for start, end in avatar_gaps(clips or [], duration):
        cursor = start
        for span_start, span_end in spans:
            if span_start <= cursor + frame + 0.001:
                cursor = max(cursor, span_end)
        if cursor < end - frame - 0.001:
            cover_bad.append(
                f"интервал {start:g}–{end:g} без ведущей не закрыт полноэкранной "
                "карточкой — будет чёрный экран")

    def gate(problems: list[str]) -> str:
        return "PASS" if not problems else "FAIL: " + "; ".join(problems)

    return {"D9_frame_grid": gate(grid_bad), "D10_zone": gate(zone_bad),
            "D11_schema": gate(_schema_problems(storyboard)),
            "D12_faceless_cover": gate(cover_bad),
            "D13_density": gate(density_bad)}
