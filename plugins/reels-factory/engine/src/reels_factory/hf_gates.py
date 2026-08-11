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
    PRESENTER_POSITIONS, avatar_gaps, fills_frame, in_avatar_gap,
)
from reels_factory.hf_montage import (
    AVATAR_ON_SCREEN_MAX, SERIES_SHOTS, insert_of, on_screen_seconds,
    shot_queries,
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
    # Шапку раскадровки (`schemaVersion`, `composition`, `videoTrack`,
    # `subtitles`) проверять больше нечего: её целиком пишет наш же
    # `complete_storyboard` перед сборкой, а гейт читает файл уже после него.
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
        elif isinstance(insert, dict) and len(shot_queries(scene)) != SERIES_SHOTS:
            problems.append(
                f"{scene_id}: биролл ставится серией — `insert.shots` это "
                f"список из {SERIES_SHOTS} английских запросов стокового "
                "видео, по ним планы серии и ищут")
        beat = scene.get("beat")
        if beat is not None and beat not in BEATS:
            problems.append(f"{scene_id}: бит {beat!r} неизвестен, есть "
                            f"{', '.join(BEATS)}")
        overlay = scene.get("overlay")
        if overlay is not None:
            if (not isinstance(overlay, dict)
                    or not str(overlay.get("block") or "").strip()):
                problems.append(
                    f"{scene_id}: `overlay` — объект с полем `block` (имя "
                    "накладки из списка в задании) и, если есть слоты, `text`")
            elif not isinstance(overlay.get("text") or {}, dict):
                problems.append(f"{scene_id}: `overlay.text` — объект "
                                "«имя слота → строка»")
        icon = scene.get("icon")
        if icon is not None and (
                not isinstance(icon, dict)
                or not str(icon.get("query") or "").strip()):
            problems.append(
                f"{scene_id}: `icon` — объект с полем `query`, английский "
                "запрос значка")
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
    return insert_of(scene) is not None


def check_montage(storyboard: dict, *, clips: list[dict] | None = None,
                  duration: float = 0.0) -> dict:
    """Сколько аватара осталось в кадре после подбора.

    Грамматика серий (два плана, длина серии, лицо между сериями) отсюда снята:
    число планов роняет `check_shots` ещё до подбора, а длину и зазор
    конструктивно держит отбор `pick_series`. Доля аватара — другое дело: она
    меняется уже ПОСЛЕ отбора, когда `settle_inserts` переводит сцену без
    вставки на полнокадровую ведущую, и ловить этот дрейф больше некому.
    """
    scenes = storyboard.get("scenes") or []

    # Сколько аватар виден зрителю. Считается по полю `presenter`: всё, что не
    # `none`, — аватар в кадре, включая уголок `pip-*` и половину `stack`.
    # Секунды, где аватар не заказан вовсе, в счёт не попадают сами: там
    # `presenter` обязан быть `none`, и за это отвечает D12.
    share = on_screen_seconds(scenes) / duration if duration else 1.0
    if share > AVATAR_ON_SCREEN_MAX + 0.005:
        share_gate = (
            f"FAIL: аватар в кадре {share * 100:.0f}% хронометража при потолке "
            f"{AVATAR_ON_SCREEN_MAX * 100:.0f}% — каждая лишняя секунда это "
            "заказанная секунда генерации. Переведи самые длинные сцены с "
            'бироллом в `presenter: "none"` либо назови больше моментов под '
            "биролл")
    else:
        share_gate = f"PASS: аватар в кадре {share * 100:.0f}% хронометража"

    return {"D24_avatar_share": share_gate}


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
        # Запасная схема закрывает кадр наравне со вставкой: она стоит в
        # верхней трети, и нижний уголок ведущей с ней не спорит.
        if scene.get("schemaShown"):
            continue
        if not fills_frame(position, _has_insert(scene)):
            problems.append(
                f'{scene.get("id", "?")}: ведущая {position!r} без вставки не '
                "закрывает кадр — остальное будет чёрным")
    return {"D20_frame_filled": "PASS" if not problems
            else "FAIL: " + "; ".join(problems)}


def _empty_frame_problems(scenes: list[dict]) -> list[str]:
    """Сцена без ведущей, которой в кадр так ничего и не встало.

    `check_frame_filled` судит план: там `presenter: "none"` без вставки — это
    законная фоновая сцена, фон и крупный титр. Здесь судится результат: сцена
    осталась без ведущей ПОСЛЕ подбора, и закрыть кадр обязано хоть что-то —
    вставка, значок, накладка или запасная схема. Фоновая сцена с одним титром
    в середине ролика читается обрывом, и раньше это проезжало молча: сцена,
    потерявшая серию, просто показывала фон.
    """
    problems = []
    for scene in scenes:
        if str(scene.get("presenter") or "none") != "none":
            continue
        if _has_insert(scene):
            continue
        if scene.get("icon") or scene.get("overlay") or scene.get("schemaShown"):
            continue
        problems.append(
            f'{scene.get("id", "?")}: ведущей нет, вставка не встала, и закрыть '
            "кадр нечем. У сцены с бироллом заполняй `fallback` — из него код "
            "соберёт схему; либо назови `icon` или `overlay`")
    return problems


def check_storyboard(storyboard: dict, *, clips: list[dict] | None = None,
                     duration: float = 0.0) -> dict:
    """Гейты раскадровки. PASS либо FAIL с перечислением сцен."""
    scenes = storyboard.get("scenes") or []

    def gate(problems: list[str]) -> str:
        return "PASS" if not problems else "FAIL: " + "; ".join(problems)

    # Сняты как тавтологии — проверяли то, что код гарантирует сам, и провалиться
    # не могли ни при каком плане агента:
    #
    # D9 (сетка кадров) — времена сцен квантует `lay_out_scenes`
    #   (hf_phrases.py:204-205), а перед записью раскадровки ещё раз квантует
    #   `build_composition` (hf_compose.py). Гейт читал этот же файл.
    # D13 (плотность) — пол `ceil(duration / MAX_STATIC_SPAN)` следует из того,
    #   что сцены обязаны выстилать ролик без дыр и ни одна не длиннее
    #   MAX_STATIC_SPAN; и то и другое роняет `lay_out_scenes` раньше гейтов.
    #   Сама `min_scenes` жива — её число идёт агенту в задание.
    # D23 (грамматика серий) — число планов роняет `check_shots` до подбора,
    #   а длину серии и лицо между сериями обеспечивает отбор `pick_series`.
    #   D24 (доля аватара) остаётся: она ловит дрейф ПОСЛЕ отбора, когда
    #   `settle_inserts` переводит сцену без вставки на полнокадровую ведущую.
    #
    # D10 (зона карточки из списка пяти) снят раньше: зон в слоёном кадре нет.
    result = {"D11_schema": gate(_schema_problems(storyboard)),
              "D12_faceless_cover": gate(
                  _faceless_problems(scenes, clips or [], duration)),
              "D21_scene_contrast": gate(_sameness_problems(scenes)),
              "D25_empty_frame": gate(_empty_frame_problems(scenes))}
    result.update(check_frame_filled(storyboard))
    result.update(check_montage(storyboard, clips=clips, duration=duration))
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


def _scene_look(scene: dict) -> str:
    """Чем сцена занимает кадр — словами, по которым её видно.

    Раньше сравнивались только запросы вставки, и две сцены подряд с запасной
    схемой считались одним планом: вставки нет ни у той, ни у другой. Схемы
    разные — разный значок, разный знак бренда, — и зритель видит смену.
    """
    shots = " ".join(shot_queries(scene))
    if shots:
        return shots
    icon = str((scene.get("icon") or {}).get("query") or "").strip()
    if icon:
        return f"значок {icon}"
    plan = scene.get("fallback") or {}
    schema = " ".join(str(plan.get(kind) or "").strip()
                      for kind in ("logo", "icon")).strip()
    if scene.get("needsSchema") and schema:
        return f"схема {schema}"
    block = str((scene.get("overlay") or {}).get("block") or "").strip()
    return f"накладка {block}" if block else ""


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
        if same_presenter and _scene_look(left) == _scene_look(right):
            problems.append(
                f'{left.get("id", "?")} и {right.get("id", "?")} идут подряд с '
                "одинаковой картинкой — зритель увидит один план, а не два. "
                "Смени в одной из них положение ведущей или вставку, либо "
                "объедини их в одну сцену")
    return problems
