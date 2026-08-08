"""Проверка раскадровки, которую вернул агент-сборщик.

Здесь только то, чего не знает их `hyperframes check`: он судит отрисованную
композицию (переполнение кадра, перекрытые надписи, контраст — коды
`canvas_overflow`, `text_box_overflow`, `text_occluded` в
`packages/cli/src/commands/layout-audit.browser.js:472-1018`), а раскадровку не
читает вовсе — по их же словам, `storyboard.json` не парсит ни одна команда
(talking-head-recut/SKILL.md:604-606).

Значит наше здесь: схема, сетка кадров, плотность сцен, закрытые интервалы без
ведущей и различимость соседних сцен. Лицо и подвижность ведущей меряются на
живой композиции в `hf_probe.py` — раскадровка о них врать умеет, DOM нет.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from reels_factory.hf_compose import BEATS
from reels_factory.hf_layout import (
    PRESENTER_POSITIONS, avatar_gaps, fills_frame, in_avatar_gap, quantize,
)
from reels_factory.hf_rhythm import MAX_STATIC_SPAN


def min_scenes(duration: float) -> int:
    """Пол числа сцен — только против дыр, не против ритма.

    Ни верхней границы, ни «правильного» числа нет: их маршрут велит «Match
    density to the requested format and message» и прямо запрещает число
    назначать — «not permission to invent claims, scenes, or a fixed number of
    elements» (general-video/SKILL.md:128). Плотность выбирает агент под смысл.

    Прежняя формула выводила пол из планки D18 (смена не реже раза в
    MAX_SECONDS_PER_CHANGE) в предположении, что смену картинки даёт только
    граница сцен. Это дало 21 сцену на 41,5 с — метроном по двум секундам,
    ровно то, с чем боремся. Предположение неверно: смену дают и переход, и
    смена положения ведущей, и наезд — D18 меряет их все по готовому файлу.

    Остаётся один пол — из D19: кусок без смены не длиннее MAX_STATIC_SPAN,
    значит сцен не меньше, чем таких кусков помещается в ролик.
    """
    return max(1, math.ceil(float(duration) / MAX_STATIC_SPAN))


def _schema_problems(storyboard: dict) -> list[str]:
    """Расхождения с их схемой v3 (SKILL.md:130-165, 610-616).

    Схема их, но список сцен у нас называется `scenes`, а не `cards`: карточкой
    была непрозрачная сцена во весь кадр, и этого объекта в кадре больше нет.
    Схему это не ломает — их же дока говорит про `storyboard.json`, что «no CLI
    command consumes it» (talking-head-recut/SKILL.md:125): файл существует,
    чтобы решения были явными, а разбирает его только наш код.
    """
    problems = []
    if storyboard.get("schemaVersion") != 3:
        problems.append(
            f'schemaVersion={storyboard.get("schemaVersion")!r}, ожидается 3')
    for field in ("composition", "videoTrack", "subtitles", "scenes"):
        if field not in storyboard:
            problems.append(f"нет поля {field}")
    composition = storyboard.get("composition") or {}
    if not isinstance(composition, dict) or "durationSeconds" not in composition:
        problems.append("composition.durationSeconds не задан")
    video = storyboard.get("videoTrack") or {}
    if not isinstance(video, dict) or not video.get("bounds"):
        problems.append("videoTrack.bounds не задан — геометрия ведущей живёт там")

    for scene in storyboard.get("scenes") or []:
        scene_id = scene.get("id", "?")
        if "intent" not in scene:
            problems.append(f"{scene_id}: нет поля intent")
        position = scene.get("presenter")
        if position not in PRESENTER_POSITIONS:
            problems.append(
                f"{scene_id}: положение ведущей {position!r} неизвестно, есть "
                f"{', '.join(PRESENTER_POSITIONS)}")
        insert = scene.get("insert")
        if insert is not None and not isinstance(insert, dict):
            problems.append(f"{scene_id}: `insert` должен быть объектом или null")
        elif isinstance(insert, dict) and not str(insert.get("query") or "").strip():
            problems.append(
                f"{scene_id}: у вставки нет поля `query` — это английский запрос стокового видео, по нему её и ищут")
        beat = scene.get("beat")
        if beat is not None and beat not in BEATS:
            problems.append(f"{scene_id}: бит {beat!r} неизвестен, есть "
                            f"{', '.join(BEATS)}")
        # Поля прошлого контракта: мы просили их сверх схемы, и они противоречат
        # videoTrack.bounds — соблюсти оба разом нельзя, значит остаётся их.
        for ours in ("contentRect", "videoRect", "zone"):
            if ours in scene:
                problems.append(f"{scene_id}: поле {ours} их схемой не предусмотрено")
    return problems


#: Файлы, которые считаются настоящей вставкой: видео-бироллы и растровые
#: фотографии. Векторные иконки сюда не входят намеренно: нарисованный
#: значок — это не картинка под смысл фразы.
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")
MEDIA_SUFFIXES = IMAGE_SUFFIXES + (".mp4", ".webm", ".mov")

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
            if not ref.lower().endswith(MEDIA_SUFFIXES):
                continue
            # клипы ведущей — не вставка: они лежат в clips/ и есть всегда
            if ref.startswith("clips/"):
                continue
            if (page.parent / ref).exists() or (public / ref).exists():
                used.append(ref)

    ledgers = [p for p in rdir.rglob(".media/manifest.jsonl")]
    problems = []
    if not ledgers:
        problems.append("нет реестра media-use (.media/manifest.jsonl) — "
                        "вставки не подбирались")
    if not used:
        # Прогон 03.08 закончился пятью нарисованными от руки SVG и самодельной
        # записью в реестре: агент решил, что media-use недоступен, и подменил
        # результат своей графикой. Файл из подбора отличает найденное от
        # нарисованного.
        problems.append(
            "в композиции нет ни одной подобранной вставки; нарисованный "
            f"вектор не считается — нужен файл {', '.join(MEDIA_SUFFIXES)} "
            "из подбора")
    return {"D16_media_use": "PASS" if not problems
            else "FAIL: " + "; ".join(problems)}


_MARKUP_NOISE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_TEXT_FRAG = re.compile(r">([^<>]+)<")
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def _text_marks(html: str) -> set[str]:
    """Видимые текстовые куски разметки. Цифры и значки («01», «✓») не в счёт —
    это оформление сцены, а не заглушка."""
    clean = _MARKUP_NOISE.sub("", html)
    found = set()
    for fragment in _TEXT_FRAG.findall(clean):
        text = " ".join(fragment.split())
        if text and _HAS_LETTER.search(text):
            found.add(text)
    return found


def check_placeholders(rdir) -> dict:
    """Заглушка блока не едет в кадр.

    Их линтер такого не ловит вовсе: среди его кодов нет ни одного про
    незаполненные плейсхолдеры. Правило дешёвое: заглушка — это текст, дословно
    совпадающий с текстом того же блока в исходном файле. Совпал — слот либо
    не заполнили, либо не убрали. Судим копии `<блок>--<сцена>.html` против
    их источников.
    """
    compositions = Path(rdir) / "public" / "compositions"
    problems = []
    for copy in sorted(compositions.glob("*--*.html")
                       if compositions.exists() else []):
        block = copy.name.split("--")[0]
        source = compositions / f"{block}.html"
        if not source.exists():
            continue
        left = (_text_marks(copy.read_text(encoding="utf-8"))
                & _text_marks(source.read_text(encoding="utf-8")))
        if left:
            problems.append(f'{copy.name}: в кадр едет заглушка: '
                            + "; ".join(f"«{text}»" for text in sorted(left)[:3]))
    return {"D22_placeholders": "PASS" if not problems
            else "FAIL: " + "; ".join(problems)}


def _has_insert(scene: dict) -> bool:
    insert = scene.get("insert")
    return isinstance(insert, dict) and bool(str(insert.get("query") or "").strip())


def check_frame_filled(storyboard: dict) -> dict:
    """Ни на одной сцене кадр не пустует.

    Считалось это по геометрии окна ведущей плюс непрозрачной карточки. Кадр из
    слоёв закрывают другие два прямоугольника: ведущая и вставка. Ведущая во
    весь кадр закрывает его сама; в углу или в половине — остальное обязана
    закрыть вставка, иначе там чёрный прямоугольник. Ровно это и было видно на
    прогоне 13: пустые две трети кадра.

    Геометрию пересчитывать не надо: таблица `INSERT_RECTS` построена как
    дополнение к раскладке ведущей, и `fills_frame` отвечает по ней.
    """
    problems = []
    for scene in storyboard.get("scenes") or []:
        position = str(scene.get("presenter") or "full")
        if not fills_frame(position, _has_insert(scene)):
            problems.append(
                f'{scene.get("id", "?")}: ведущая {position!r} без вставки не '
                "закрывает кадр — остальное будет чёрным")
    return {"D20_frame_filled": "PASS" if not problems
            else "FAIL: " + "; ".join(problems)}


def check_storyboard(storyboard: dict, *, clips: list[dict] | None = None,
                     duration: float = 0.0) -> dict:
    """Гейты раскадровки. PASS либо FAIL с перечислением сцен."""
    scenes = storyboard.get("scenes") or []
    grid_bad = []

    for scene in scenes:
        scene_id = scene.get("id", "?")
        for field in ("startSec", "endSec"):
            if field not in scene:
                grid_bad.append(f"{scene_id}: нет поля {field}")
                continue
            value = float(scene[field])
            if abs(value - quantize(value)) > 0.0005:
                grid_bad.append(f"{scene_id}: {field}={value} вне сетки кадров")

    # Плотность. Пол только против дыр (см. min_scenes), верхней границы нет:
    # плотность выбирает агент под смысл.
    density_bad = []
    low = min_scenes(duration)
    if duration > 0 and len(scenes) < low:
        density_bad.append(
            f"сцен {len(scenes)}, при {duration:g} с нужно хотя бы {low}: иначе "
            f"найдётся кусок длиннее {MAX_STATIC_SPAN:g} с без смены картинки")

    def gate(problems: list[str]) -> str:
        return "PASS" if not problems else "FAIL: " + "; ".join(problems)

    # D10 (зона карточки из списка пяти) снят. Список зон — таблица
    # `talking-head-recut/SKILL.md:180-188`, у `/general-video` таблицы зон нет
    # вовсе, а самих зон после перехода на слои не осталось.
    result = {"D9_frame_grid": gate(grid_bad),
              "D11_schema": gate(_schema_problems(storyboard)),
              "D12_faceless_cover": gate(
                  _faceless_problems(scenes, clips or [], duration)),
              "D13_density": gate(density_bad),
              "D21_scene_contrast": gate(_sameness_problems(scenes))}
    result.update(check_frame_filled(storyboard))
    return result


def _faceless_problems(scenes: list[dict], clips: list[dict],
                       duration: float) -> list[str]:
    """Кусок, на который аватар не заказан, не притворяется, что ведущая есть.

    Раньше гейт требовал ещё и вставку: без неё кадр был чёрным. С фирменным
    фоном из frame.md сцена без вставки — законная фоновая сцена, поэтому
    осталось одно требование: ведущей на этом куске нет физически, и план
    обязан честно ставить `none` — иначе названное положение применится к
    пустому окну.
    """
    problems = []
    gaps = avatar_gaps(clips, duration)
    if not gaps:
        return problems
    for scene in scenes:
        start = float(scene.get("startSec", 0))
        end = float(scene.get("endSec", 0))
        if not in_avatar_gap(start, end, gaps):
            continue
        if scene.get("presenter") != "none":
            problems.append(
                f'{scene.get("id", "?")} ({start:g}–{end:g} с) попадает на кусок, '
                "где ведущей нет вовсе: положение обязано быть `none` — окно "
                "всё равно будет пустым")
    return problems


def _sameness_problems(scenes: list[dict]) -> list[str]:
    """Соседние сцены отличаются картинкой.

    Прежний D21 требовал зазор между карточками: приход сцены и её уход детектор
    считал двумя сменами только тогда, когда между ними был кадр без карточки.
    В слоёном кадре зазора нет и быть не может — сцены выстилают ролик. Смену
    даёт сама граница, но только если по её сторонам разная картинка: две сцены
    подряд с ведущей во весь кадр и без вставки — это один план, а не два, и
    детектор их не разделит.
    """
    problems = []
    ordered = sorted(scenes, key=lambda scene: float(scene.get("startSec", 0)))
    for left, right in zip(ordered, ordered[1:]):
        same_presenter = (left.get("presenter") or "full") == (
            right.get("presenter") or "full")
        left_look = ((left.get("insert") or {}).get("query") or "").strip()
        right_look = ((right.get("insert") or {}).get("query") or "").strip()
        if same_presenter and left_look == right_look:
            problems.append(
                f'{left.get("id", "?")} и {right.get("id", "?")} идут подряд с '
                "одинаковой картинкой — зритель увидит один план, а не два. "
                "Смени в одной из них положение ведущей или вставку, либо "
                "объедини их в одну сцену")
    return problems
