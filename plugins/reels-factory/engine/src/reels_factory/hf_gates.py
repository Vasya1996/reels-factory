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
    SERIES_SHOTS, filling_element, frame_filler, insert_of, same_look,
    scene_look, schema_scene, shot_queries,
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


def _form_problems(scene_id: str, field: str, plan) -> list[str]:
    """Форма схемы заполнена так, как её блок умеет показать.

    Проверяем не вкус, а то, что иначе молча уедет в кадр мусором: величина без
    цифры печатается нулём (их счётчик выводит `Math.round(значение) + суффикс`,
    `mk-progress-stat.html:168`), строка без правой половины рисует пустую
    линию, значок не из списка оставляет карточку без рисунка. Выбор формы —
    решение агента, и гейт в него не лезет.
    """
    from reels_factory.hf_schema import FORMS, ICONS, LIMITS, MINIMUM

    if plan is None:
        return []
    if not isinstance(plan, dict):
        return [f"{scene_id}: `{field}` — объект с полем `form`"]
    form = plan.get("form")
    if form is None:
        return []
    if form not in FORMS:
        return [f"{scene_id}: форма {form!r} неизвестна, есть "
                f"{', '.join(FORMS)}"]

    problems = []
    where = f"{scene_id}.{field}"
    if not str(plan.get("why") or "").strip():
        problems.append(f"{where}: нет разбора `why` — одной строкой, тип "
                        "высказывания и почему эта форма")

    if form == "metric":
        value = str(plan.get("value") or "").strip()
        if not re.match(r"\d", value):
            problems.append(
                f"{where}: величина {value!r} начинается не с цифры — их "
                "счётчик печатает округлённое число и хвост при нём")
        base = plan.get("base")
        if base not in (None, "") and not str(base).strip().isdigit():
            problems.append(f"{where}: база {base!r} — целое число или null")
    elif form == "items":
        items = plan.get("items")
        if not isinstance(items, list) or not items:
            problems.append(f"{where}: `items` — список карточек")
            items = []
        if items and len(items) < MINIMUM["items"]:
            problems.append(
                f"{where}: карточек {len(items)} — в вертикали это не сцена, а "
                f'плашка в пустом кадре; их нужно {MINIMUM["items"]}–'
                f'{LIMITS["items"]}')
        if len(items) > LIMITS["items"]:
            problems.append(f"{where}: карточек {len(items)}, а помещается "
                            f'{LIMITS["items"]} — дальше уходит под титр')
        for item in items:
            if not isinstance(item, dict):
                problems.append(f"{where}: карточка — объект `label` и `icon`")
                continue
            if not str(item.get("label") or "").strip():
                problems.append(f"{where}: карточка без подписи")
            if item.get("icon") not in ICONS:
                problems.append(
                    f'{where}: значок {item.get("icon")!r} не нарисован, '
                    f"есть {', '.join(ICONS)}")
    elif form == "pairs":
        rows = plan.get("rows")
        if not isinstance(rows, list) or not rows:
            problems.append(f"{where}: `rows` — список пар «свойство → "
                            "значение»")
            rows = []
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("value")
                                                    or "").strip():
                problems.append(
                    f"{where}: строка без значения — их список рисует пару, и "
                    "половина пары оставляет в кадре пустую линию")
                break
    elif form == "steps":
        nodes = [n for n in (plan.get("nodes") or []) if str(n or "").strip()]
        if not MINIMUM["steps"] <= len(nodes) <= LIMITS["steps"]:
            problems.append(
                f"{where}: узлов {len(nodes)}, а цепочка держит от "
                f'{MINIMUM["steps"]} до {LIMITS["steps"]}')
    elif form == "brand":
        brands = [b for b in (plan.get("brands") or []) if str(b or "").strip()]
        if not brands:
            problems.append(f"{where}: `brands` — имена брендов")
    return problems


#: Типы `data-composition-variables` их же полки и что мы принимаем за каждый.
#: Список из карточки позиции (`reels.variables`), а значение — из плана: два
#: разных типа под одним именем их рантайм не разводит вовсе, а `enum` без
#: списка `options` принимает любую строку.
_VARIABLE_TYPES = {
    "number": (int, float),
    "string": (str,),
    "boolean": (bool,),
    "color": (str,),
    "enum": (str,),
}


def _element_problems(scene: dict, element: dict, cards: dict,
                      skipped: dict) -> list[str]:
    """Одна позиция из `elements` — та же проверка, что делает их `add`.

    Их `hyperframes add` неизвестное имя не ставит вовсе, а установка идёт уже
    после того, как ведущую сняли и оплатили: имя, названное по памяти, роняет
    попытку сборки с деньгами на руках. Здесь тот же вопрос задан плану — до
    заказа.

    Проверяется то, что известно из карточки, — имя, имена и типы переменных,
    число слов под слоты, — и одно, что известно из самой сцены: положение
    ведущей. Позиция вида `effect` живёт в свободной зоне кадра, а при
    полнокадровой ведущей и при `stack` такой зоны нет вовсе
    (`hf_compose.effect_zone`): сборка снимала такой элемент молча, уже после
    оплаты, и агент узнавал о потере по логу (отчёт B4, `count-up` на `punch`).
    Здесь он узнаёт причину до заказа.

    Уместность позиции по-прежнему не проверяется — это решение агента, и гейт
    в него не лезет, как не лезет в выбор формы схемы.
    """
    from reels_factory.hf_compose import effect_zone

    scene_id = scene.get("id", "?")
    name = str(element.get("name") or "").strip()
    where = f"{scene_id}.elements[{name}]"
    if name in skipped:
        return [f"{scene_id}: позицию {name!r} ставить нельзя — "
                f"{skipped[name]}"]
    if cards and name not in cards:
        return [f"{scene_id}: позиции {name!r} в каталоге нет — имена "
                "перечислены в `catalog.index.md` рядом с заданием"]
    card = cards.get(name) or {}
    problems = []
    position = str(scene.get("presenter") or "none")
    if card.get("kind") == "effect" and effect_zone(position) is None:
        problems.append(
            f"{where}: позиция вида `effect` встаёт в свободную зону кадра, а "
            f"ведущая {position!r} её не оставляет — дай сцене уголок "
            "(`pip-*`) или `none`, либо назови позицию другого вида")
    declared = card.get("variables") or {}
    named = element.get("variables")
    if named is not None and not isinstance(named, dict):
        problems.append(f"{where}: `variables` — объект «имя → значение»")
        named = {}
    for key, value in (named or {}).items():
        rule = declared.get(key)
        if rule is None:
            problems.append(
                f"{where}: переменной {key!r} у позиции нет, есть "
                + (", ".join(f"`{one}`" for one in sorted(declared))
                   or "ни одной"))
            continue
        kinds = _VARIABLE_TYPES.get(str(rule.get("type") or ""))
        # Булево в Python — тоже int, и без этой оговорки `true` прошло бы за
        # число, а число за булево.
        if kinds and (not isinstance(value, kinds)
                      or (isinstance(value, bool) and bool not in kinds)):
            problems.append(
                f"{where}: переменная {key!r} объявлена типом "
                f'{rule.get("type")}, а в плане {type(value).__name__}')
    words = element.get("words")
    if words is not None and not isinstance(words, list):
        problems.append(f"{where}: `words` — список строк по числу слотов")
    elif words:
        slots = card.get("text_slots") or []
        if len(words) > len(slots):
            problems.append(
                f"{where}: слов {len(words)}, а слотов у позиции "
                f"{len(slots)} — лишние в кадр не попадут")
    return problems


def elements_problems(scenes: list[dict]) -> list[str]:
    """Позиции каталога, названные планом, каталогу не противоречат.

    Список отдаётся наружу, а не сразу вердикт: по нему судят двое — D11 здесь,
    после сборки, и `D36_elements` до заказа ведущей (hf_render.py). Судят они
    одно и то же одним кодом — разойтись двум местам нечем.
    """
    from reels_factory.hf_catalog import catalog_cards, skipped_blocks
    from reels_factory.hf_montage import scene_elements

    try:
        cards = dict(catalog_cards())
        skipped = dict(skipped_blocks())
    except (OSError, ValueError):
        # Каталога нет — обвинять план в том, что не поднялся наш же реестр,
        # незачем; сборка снимет такой элемент сама (`element_problem`).
        cards, skipped = {}, {}
    problems = []
    for scene in scenes:
        scene_id = scene.get("id", "?")
        found = scene.get("elements")
        if found is not None and not isinstance(found, list):
            problems.append(f"{scene_id}: `elements` — список объектов "
                            "`{name, words?, variables?}`")
            continue
        for element in scene_elements(scene):
            problems += _element_problems(scene, element, cards, skipped)
    return problems


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
        for field in ("schema", "fallback"):
            problems += _form_problems(scene_id, field, scene.get(field))
        problems += elements_problems([scene])
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


#: Заголовок страницы в кадре не виден: это имя вкладки, а не текст сцены. У их
#: компонентов он есть всегда («Grid Card Assemble»), и без этой строчки гейт
#: заглушек ловил его в каждой копии.
_MARKUP_NOISE = re.compile(r"<(script|style|title)\b.*?</\1>", re.S | re.I)
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


def _decor_texts() -> dict:
    """Надписи, которые в блоке нарисованы, а не подставлены.

    Гейт судит по совпадению с исходником, и такой текст выглядит как
    незаполненный слот, хотя это часть оформления: у камкордерного HUD «REC» —
    сама суть блока, её никто не заполняет и убирать нечего.

    Список живёт в карточке блока (`reels.decor_texts`), а не литералом здесь:
    знает про рисованный текст тот, кто заводил карточку, и каждая новая
    позиция каталога иначе требовала бы правки этого файла. Каталога может не
    быть — тогда белого списка нет, и гейт судит строже, а не мягче.
    """
    from reels_factory.hf_catalog import decor_texts

    try:
        return dict(decor_texts())
    except (OSError, ValueError):
        return {}


def check_placeholders(rdir) -> dict:
    """Заглушка блока не едет в кадр.

    Их линтер такого не ловит вовсе: среди его кодов нет ни одного про
    незаполненные плейсхолдеры. Правило дешёвое: заглушка — это текст, дословно
    совпадающий с текстом того же блока в исходном файле. Совпал — слот либо
    не заполнили, либо не убрали. Судим копии `<блок>--<сцена>.html` против
    их источников.
    """
    compositions = Path(rdir) / "public" / "compositions"
    decor = _decor_texts()
    problems = []
    for copy in sorted(compositions.glob("*--*.html")
                       if compositions.exists() else []):
        block = copy.name.split("--")[0]
        source = compositions / f"{block}.html"
        if not source.exists():
            continue
        left = (_text_marks(copy.read_text(encoding="utf-8"))
                & _text_marks(source.read_text(encoding="utf-8")))
        left -= decor.get(block, set())
        if left:
            problems.append(f'{copy.name}: в кадр едет заглушка: '
                            + "; ".join(f"«{text}»" for text in sorted(left)[:3]))
    return {"D22_placeholders": "PASS" if not problems
            else "FAIL: " + "; ".join(problems)}


def _has_insert(scene: dict) -> bool:
    return insert_of(scene) is not None


#: Сколько оплаченных секунд аватара позволено не показать. Ручки островов
#: (`handle_seconds`) дают клипу небольшой запас по краям, и он в кадр
#: действительно не попадает — это не потеря, а стык.
WASTED_AVATAR_TOLERANCE = 0.5


def check_montage(storyboard: dict, *, clips: list[dict] | None = None,
                  duration: float = 0.0) -> dict:
    """Всё, за что заплачено, попало в кадр.

    Грамматика серий (два плана, длина серии, лицо между сериями) отсюда снята:
    число планов роняет `check_shots` ещё до подбора, а длину и зазор
    конструктивно держит отбор `pick_series`.

    Здесь считается обратное тому, что считалось раньше. Прежний гейт следил,
    чтобы аватар не был виден дольше 60 % ролика, — экономия предполагала, что
    показ определяет заказ. Порядок обратный: клипы покупаются до плана
    (pipeline.py:365), и спрятанная ведущая — это выброшенные деньги, а не
    сбережённые. Прогон 462a1c62 потерял так 9,2 с из 27,5 заказанных.
    Потолок заказа остался у `avatar_islands`, а здесь сторожат кошелёк.

    Текст находки обращён к коду, а не к агенту: сцену без ведущей на
    оплаченном куске оставляет `show_ordered_avatar`/`refill_scene`, и чинить
    её агенту нечем.
    """
    scenes = storyboard.get("scenes") or []
    gaps = avatar_gaps(clips or [], duration)
    wasted = []
    seconds = 0.0
    for scene in scenes:
        start = float(scene.get("startSec", 0))
        end = float(scene.get("endSec", 0))
        if str(scene.get("presenter") or "full") != "none":
            continue
        if in_avatar_gap(start, end, gaps):
            continue
        seconds += end - start
        wasted.append(f'{scene.get("id", "?")} ({start:g}–{end:g} с)')

    if seconds > WASTED_AVATAR_TOLERANCE:
        gate = (f"FAIL: {seconds:.1f} с ведущей оплачены и не попали в кадр — "
                + "; ".join(wasted))
    else:
        gate = f"PASS: оплаченной ведущей мимо кадра {seconds:.1f} с"

    return {"D24_avatar_paid_shown": gate}


def frame_filled_problems(scenes: list[dict]) -> list[str]:
    """Сцены, где ведущая уголком или половиной кадра оставила остальное пустым.

    Считалось это по геометрии окна ведущей плюс непрозрачной карточки. Кадр из
    слоёв закрывают другие два прямоугольника: ведущая и вставка. Ведущая во
    весь кадр закрывает его сама; в углу или в половине — остальное обязана
    закрыть вставка, иначе там чёрный прямоугольник. Ровно это и было видно на
    прогоне 13: пустые две трети кадра.

    Геометрию пересчитывать не надо: таблица `INSERT_RECTS` построена как
    дополнение к раскладке ведущей, и `fills_frame` отвечает по ней.

    Список отдаётся наружу, а не сразу вердикт: по нему судят двое — D20 здесь,
    после сборки, и `D35_frame_filled` до заказа ведущей (hf_render.py). Второй
    появился потому, что первый судит уже с оплаченными рендерами HeyGen: боевой
    прогон лёг на `s-06: ведущая 'pip-tl' без вставки`, и это стоило $11,86 без
    ролика. Судят они одно и то же одним кодом — разойтись двум местам нечем.
    """
    problems = []
    for scene in scenes:
        position = str(scene.get("presenter") or "full")
        # Схема закрывает кадр наравне со вставкой: она стоит в верхней трети,
        # и нижний уголок ведущей с ней не спорит. Считается и запланированная,
        # а не только отрисованная: гейт судит и до сборки — а схему, которая в
        # кадр не встала, `drop_schema` снимает вместе с уголком.
        #
        # Спрашиваем `schema_scene`, а не флаг `needsSchema`: флаг — это
        # просьба кода нарисовать запасную схему, и без пригодного `fallback`
        # она невыполнима. Прогон hf-live2 прошёл оба гейта ровно на этой
        # разнице.
        if schema_scene(scene):
            continue
        # Элемент каталога вида `scene` или `effect` закрывает кадр наравне со
        # схемой — и здесь, и в `frame_filler` (D25). Считает их обоим один
        # `filling_element`: прежде плашка закрывала кадр для одного гейта и
        # не закрывала для другого, и повторять это расхождение незачем.
        if filling_element(scene):
            continue
        if not fills_frame(position, _has_insert(scene)):
            problems.append(
                f'{scene.get("id", "?")}: ведущая {position!r} без вставки не '
                "закрывает кадр — остальное будет чёрным")
    return problems


def check_frame_filled(storyboard: dict) -> dict:
    """Ни на одной сцене кадр не пустует."""
    problems = frame_filled_problems(storyboard.get("scenes") or [])
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

    Раскадровкой дело не заканчивается: тот же вопрос задаёт D26
    (`hf_probe._gate_frame_content`) уже собранной композиции. Здесь судится
    решение кода, там — то, что из него вышло в DOM; прогон hf-live2 показал,
    что расхождение между этими двумя ответами и есть пустой кадр.
    """
    problems = []
    for scene in scenes:
        # Чем закрыт кадр — считает `frame_filler`: тем же счётом код решает,
        # можно ли снимать вставку, и два разных счёта означали бы, что код
        # чинит одно, а гейт судит другое. Схема считается и запланированная:
        # не встала — её снимает `drop_schema`, и тогда поле уже пусто.
        if frame_filler(scene):
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


def _sameness_problems(scenes: list[dict]) -> list[str]:
    """Соседние сцены отличаются картинкой.

    Прежний D21 требовал зазор между карточками: приход сцены и её уход детектор
    считал двумя сменами только тогда, когда между ними был кадр без карточки.
    В слоёном кадре зазора нет и быть не может — сцены выстилают ролик. Смену
    даёт сама граница, но только если по её сторонам разная картинка: две сцены
    подряд с ведущей во весь кадр и без вставки — это один план, а не два, и
    детектор их не разделит.

    Пару разводит сам код — `dedupe_neighbours` меняет вид кадра у второй сцены
    либо склеивает обе в одну. Сюда находка доходит, только если не сработало
    ни то ни другое, поэтому текст говорит, что именно осталось несведённым, а
    не велит агенту переделать план: план на этом месте уже не его.
    """
    problems = []
    ordered = sorted(scenes, key=lambda scene: float(scene.get("startSec", 0)))
    for left, right in zip(ordered, ordered[1:]):
        if not same_look(left, right):
            continue
        look = scene_look(left) or "ведущая без вставки"
        problems.append(
            f'{left.get("id", "?")} и {right.get("id", "?")} идут подряд с '
            f"одинаковой картинкой ({look}) — зритель увидит один план, а не "
            "два")
    return problems
