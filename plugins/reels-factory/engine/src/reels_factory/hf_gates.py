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

import math
import re
from pathlib import Path

from reels_factory.config import FPS, OUT_H, OUT_W
from reels_factory.hf_layout import (
    FULL_FRAME_ZONES, VIDEO_RECTS, ZONE_RECTS, avatar_gaps, quantize,
)
from reels_factory.hf_rhythm import MAX_STATIC_SPAN, MIN_CARD_GAP


def min_cards(duration: float) -> int:
    """Наименьшее число карточек, при котором план вообще может взять планку.

    Верхней границы больше нет. Она приходила из формулы плотности
    `talking-head-recut` (SKILL.md:206-229) — правила упаковки чужого клипа. На
    маршруте `/general-video`, по которому мы теперь идём, такой формулы нет
    вовсе: он велит «Match density to the requested format and message» и прямо
    отказывается называть число — «not permission to invent claims, scenes, or a
    fixed number of elements» (general-video/SKILL.md:128). Считать потолок
    стало нечем, а прогоны 8 и 9 упирались ровно в него: оба отдали 10 карточек
    при расчётном потолке 10.

    Пол остаётся, но выводится из НАШЕЙ планки приёмки, а не из их формулы:
    D19 не терпит куска длиннее MAX_STATIC_SPAN без смены картинки, а сменить её
    в нашей композиции может только карточка. Значит на `duration` секунд их
    нужно хотя бы столько, сколько таких кусков помещается.
    """
    return max(1, math.ceil(float(duration) / MAX_STATIC_SPAN))


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
        # Прогон 03.08 закончился пятью нарисованными от руки SVG и самодельной
        # записью в реестре: агент решил, что media-use недоступен, и подменил
        # результат своей графикой. Растр отличает найденное от нарисованного.
        problems.append(
            "в композиции нет ни одной подобранной картинки; нарисованный "
            f"вектор не считается — нужен файл {', '.join(IMAGE_SUFFIXES)} "
            "из каталога")
    return {"D16_media_use": "PASS" if not problems
            else "FAIL: " + "; ".join(problems)}


#: Зоны, где карточке разрешён непрозрачный фон. Для `video-overlay` и
#: `lower-third` их контракт это прямо запрещает: «the card's .root MUST NOT
#: paint a full opaque background» (talking-head-recut/SKILL.md:631-637), эти
#: карточки живут поверх видимого кадра.
OPAQUE_ZONES = {"fullscreen", "side-panel", "whiteboard-area"}


def _covers_frame(rects: list[dict]) -> bool:
    """Закрывают ли прямоугольники кадр целиком.

    Разрезаем кадр по границам прямоугольников и смотрим каждую клетку: для
    осевых прямоугольников это точно, а их всего два.
    """
    xs = sorted({0, OUT_W} | {r["left"] for r in rects}
                | {r["left"] + r["width"] for r in rects})
    ys = sorted({0, OUT_H} | {r["top"] for r in rects}
                | {r["top"] + r["height"] for r in rects})
    for x0, x1 in zip(xs, xs[1:]):
        if x1 <= 0 or x0 >= OUT_W:
            continue
        for y0, y1 in zip(ys, ys[1:]):
            if y1 <= 0 or y0 >= OUT_H:
                continue
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if not any(r["left"] <= cx <= r["left"] + r["width"]
                       and r["top"] <= cy <= r["top"] + r["height"]
                       for r in rects):
                return False
    return True


def check_frame_filled(storyboard: dict) -> dict:
    """Ни на одной карточке кадр не пустует.

    Уменьшенное окно ведущей закрывает седьмую часть кадра. Если карточка над
    ним прозрачная, всё остальное — чёрный прямоугольник. Проверяем по
    геометрии: окно ведущей плюс непрозрачная карточка обязаны закрыть кадр.
    """
    problems = []
    for card in storyboard.get("cards") or []:
        render = card.get("render") or {}
        if render.get("kind") == "block":
            continue                      # блок — сцена во весь кадр
        zone = card.get("zone")
        position = card.get("presenter") or "full"
        rects = []
        if position != "none" and position in VIDEO_RECTS:
            rects.append(VIDEO_RECTS[position])
        if zone in OPAQUE_ZONES and zone in ZONE_RECTS:
            rects.append(ZONE_RECTS[zone])
        if not rects or not _covers_frame(rects):
            problems.append(
                f'{card.get("id", "?")}: ведущая {position!r} и зона {zone!r} '
                "не закрывают кадр — остальное будет чёрным")
    return {"D20_frame_filled": "PASS" if not problems
            else "FAIL: " + "; ".join(problems)}


def check_storyboard(storyboard: dict, *, clips: list[dict] | None = None,
                     duration: float = 0.0) -> dict:
    """Гейты раскадровки. PASS либо FAIL с перечислением карточек."""
    cards = storyboard.get("cards") or []
    grid_bad = []

    for card in cards:
        card_id = card.get("id", "?")
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
    # Сверху больше не ограничиваем — см. min_cards.
    density_bad = []
    low = min_cards(duration)
    if duration > 0 and len(cards) < low:
        density_bad.append(
            f"карточек {len(cards)}, при {duration:g} с нужно хотя бы {low}, "
            f"иначе кусок без смены картинки выйдет длиннее {MAX_STATIC_SPAN:g} с; "
            "субтитры карточками не считаются")

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

    # D10 (зона карточки из списка пяти) снят. Список зон — таблица
    # `talking-head-recut/SKILL.md:180-188`, у `/general-video` таблицы зон нет
    # вовсе. Вдобавок гейт проверял значение, которое пишет наш же код:
    # `complete_storyboard` ставит `zone = "fullscreen"` каждой карточке
    # (hf_compose.py:264) до того, как гейты успевают её увидеть.
    result = {"D9_frame_grid": gate(grid_bad),
              "D11_schema": gate(_schema_problems(storyboard)),
              "D12_faceless_cover": gate(cover_bad),
              "D13_density": gate(density_bad),
              "D21_card_gaps": gate(_gap_problems(cards, clips or [], duration))}
    result.update(check_frame_filled(storyboard))
    return result


def _has_clip(clips: list[dict], at: float) -> bool:
    return any(c["start"] <= at + 1e-6 < c["start"] + c["duration"] for c in clips)


def _gap_problems(cards: list[dict], clips: list[dict],
                  duration: float) -> list[str]:
    """Между соседними карточками есть зазор, и ни один кусок не длиннее восьми.

    Приход сцены и её уход детектор считает двумя сменами только когда между
    сценами есть кадр без них: карточки впритык он видит как одну склейку.

    Зазор требуем только там, где есть чем его занять: на интервале без клипа
    ведущей пустое место — это чёрный кадр, и там карточки обязаны идти
    встык (это же требует D12). Предел в восемь секунд меряет и D19, но уже на
    готовом файле — здесь видно до рендера.
    """
    problems = []
    ordered = sorted(
        ((float(c.get("startSec", 0)), float(c.get("endSec", 0)),
          c.get("id", "?")) for c in cards if "startSec" in c and "endSec" in c))
    cursor = 0.0
    for start, end, card_id in ordered:
        if (start - cursor < MIN_CARD_GAP - 0.001
                and _has_clip(clips, cursor)
                and _has_clip(clips, max(start - 0.001, cursor))):
            problems.append(
                f"перед {card_id} зазор {max(start - cursor, 0):.2f} с, нужен "
                f"хотя бы {MIN_CARD_GAP:g} с — иначе смена картинки не считается")
        if end - start > MAX_STATIC_SPAN:
            problems.append(
                f"{card_id} идёт {end - start:.1f} с, предел {MAX_STATIC_SPAN:g}")
        cursor = max(cursor, end)
    if duration - cursor > MAX_STATIC_SPAN:
        problems.append(
            f"после последней карточки {duration - cursor:.1f} с без смены "
            f"картинки, предел {MAX_STATIC_SPAN:g}")
    return problems
