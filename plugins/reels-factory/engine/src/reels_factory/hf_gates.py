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
    FULL_FRAME_PRESENTER, PRESENTER_POSITIONS, avatar_gaps, fills_frame,
    in_avatar_gap,
)
from reels_factory.hf_montage import (
    FRAME_KINDS, RHYTHM_NAMES, RHYTHMS, SERIES_SHOTS, filling_element,
    frame_filler, insert_of, same_look, scene_look, schema_scene,
    shot_queries,
)


def min_scenes(duration: float, rhythm: str = "steady") -> int:
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

    Остаётся один пол — из потолка сцены без смены (раньше D19-мерка на
    готовом файле, теперь та же граница у раскладки): кусок без смены не
    длиннее `holdMax` паттерна `rhythm`, значит сцен не меньше, чем таких
    кусков помещается в ролик. Паттерн ролика ещё не выбран (`rhythm` не
    назван) — считаем по `steady`, тому же числу, что было здесь до
    режиссуры.
    """
    ceiling = RHYTHMS.get(rhythm, RHYTHMS["steady"])["holdMax"]
    return max(1, math.ceil(float(duration) / ceiling))


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
#: разных типа под одним именем их рантайм не разводит вовсе. У `enum` сверх
#: типа сверяется сам выбор: варианты каталог читает из разметки позиции
#: (`hf_catalog._variable_options`), и значение вне списка их движок молча
#: заменит умолчанием — уже после оплаты.
_VARIABLE_TYPES = {
    "number": (int, float),
    "string": (str,),
    "boolean": (bool,),
    "color": (str,),
    "enum": (str,),
}

#: Со скольких слов подряд текст позиции читается пересказом титра, а не
#: подписью. Одно-два слова — это ярлык: карточка НАЗЫВАЕТ то, о чём идёт
#: речь («Помощь», «срок две недели»), и совпадение с титром здесь неизбежно
#: и безвредно. Три слова подряд — это уже реплика, прочитанная второй раз, и
#: в кадре она стоит буква в букву под тем же, что горит в титре.
CAPTION_ECHO_WORDS = 3

_WORD = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)


def _plain_words(text: str) -> list[str]:
    """Текст на слова для сравнения с титром: нижний регистр, без пунктуации.
    Тот же счёт, каким титр отдаёт свои слова (`caption_scene_words`)."""
    return _WORD.findall(str(text or "").lower())


def _caption_echo(text: str, spoken: list[str]) -> str:
    """Самый длинный кусок титра, который этот текст повторяет слово в слово.
    Пусто — такого куска нет либо он короче `CAPTION_ECHO_WORDS`.

    Их собственная полка разводит две работы по этой самой границе: «Captions
    add the _spoken words_ as a readable subtitle; this adds _designed
    graphics_ on top of the playing video»
    (`skills/talking-head-recut/SKILL.md:19-20`), а карточка там — «designed
    graphic cards … — not plain captions (the spoken words as text)» (там
    же:18). Титр у нас идёт весь ролик и ни под чем не молчит
    (`hf_captions.write_caption_data`), значит уступает позиция каталога: она
    и есть карточка.

    Ищется самый длинный ОБЩИЙ кусок, а не совпадение текста целиком: агент
    списывает реплику не буква в букву. В варианте Б прогона
    `exp-beat-direction-2` он выбросил из неё одно слово — титр говорит
    «чтобы человек ТОЧНО согласился», карточка напечатала «чтобы человек
    согласился», — и сравнение целых строк такой пересказ бы пропустило,
    хотя «составь сообщение чтобы человек» стоит в кадре ровно под тем же
    в титре.
    """
    said = _plain_words(text)
    best: list[str] = []
    # Длины короткие (слова карточки против слов одной сцены), поэтому
    # перебор, а не таблица: считать её дольше, чем сравнить.
    for start in range(len(said)):
        for stop in range(start + len(best) + 1, len(said) + 1):
            run = said[start:stop]
            if not _run_inside(run, spoken):
                break
            best = run
    return " ".join(best) if len(best) >= CAPTION_ECHO_WORDS else ""


def _run_inside(run: list[str], spoken: list[str]) -> bool:
    return any(spoken[at:at + len(run)] == run
               for at in range(len(spoken) - len(run) + 1))


def _element_problems(scene: dict, element: dict, cards: dict, skipped: dict,
                      caption_words: list | None = None) -> list[str]:
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
    Здесь он узнаёт причину до заказа. У вида `scene` тот же вопрос стоит
    зеркально: позиция ложится подложкой ПОД окно ведущей, и полнокадровая
    ведущая закрывает её целиком.

    Уместность позиции по-прежнему не проверяется — это решение агента, и гейт
    в него не лезет, как не лезет в выбор формы схемы.

    `caption_words` — расшифровка ролика, а не содержимое `element["words"]`
    (те — слова плана под слоты позиции, читаются ниже своей переменной).
    Имя не совпадает нарочно: `hf_compose.build_composition` уже платит за
    ту же путаницу своей переменной `said`, и здесь тень над параметром
    молча отдала бы `target_absent` не то, что нужно.
    """
    from reels_factory.hf_catalog import (content_channels, number_variables,
                                          word_variables)
    from reels_factory.hf_compose import (effect_zone, paste_target,
                                          target_absent)
    from reels_factory.hf_montage import insert_of

    scene_id = scene.get("id", "?")
    name = str(element.get("name") or "").strip()
    where_id = f"{scene_id}.elements[{name}]"
    if name in skipped:
        return [f"{scene_id}: позицию {name!r} ставить нельзя — "
                f"{skipped[name]}"]
    if cards and name not in cards:
        return [f"{scene_id}: позиции {name!r} в каталоге нет — имена "
                "перечислены в `catalog.index.md` рядом с заданием"]
    card = cards.get(name) or {}
    problems = []
    position = str(scene.get("presenter") or "none")
    # Полнокадровая позиция — подложка кадра под окном ведущей
    # (`.ovl-back`, z-index 15 против 20 у окна). Полнокадровая ведущая
    # закрывает её целиком: установка была бы оплачена и не видна ни одного
    # кадра. Тот же вопрос, что и у зоны эффекта, и задан он там же — до
    # заказа.
    if card.get("kind") == "scene" and position in FULL_FRAME_PRESENTER:
        problems.append(
            f"{where_id}: позиция вида `scene` встаёт подложкой ПОД окно "
            f"ведущей, а ведущая {position!r} занимает кадр целиком и закроет "
            "её собой — дай сцене уголок (`pip-*`), `stack` или `none`")
    # Приём поверх нашего элемента (`targets` в карточке): своей разметки у
    # позиции нет, и живёт она чужим элементом кадра — окном ведущей,
    # вставкой, словами титра, схемой. Спрашивается это ДО заказа: приём,
    # которому не на чем лежать, — оплаченная установка без единого кадра
    # эффекта. Вид `effect` у таких позиций стоит из-за их же карточки
    # реестра, но зона кадра им не нужна: в кадр они не встают вовсе.
    where, refusal = paste_target(card, element)
    if refusal:
        problems.append(f"{where_id}: {refusal}")
    elif where and where != "self":
        lack = target_absent(scene, where, words=caption_words,
                             word=element.get("word"))
        if lack:
            problems.append(f"{where_id}: {lack}")
    if card.get("kind") == "effect" and not card.get("targets")             and effect_zone(position) is None:
        problems.append(
            f"{where_id}: позиция вида `effect` встаёт в свободную зону кадра, а "
            f"ведущая {position!r} её не оставляет — дай сцене уголок "
            "(`pip-*`) или `none`, либо назови позицию другого вида")
    # Держатель кадра без канала содержимого — голый каркас позиции, а не
    # содержание сцены: правило общее, для любой будущей позиции вида
    # `scene`/`effect` без text_slots, рабочей переменной или media_slots —
    # такая встала бы в кадр голым макетом (пустой стопкой карточек, пустой
    # лентой постов), а этот гейт молчал бы про канал вовсе. Ровно это вскрыл
    # живой прогон `exp-beat-direction` на `keyframe-scrub-stack` и
    # `scroll-feed` — но с тех пор карточка обеих несёт `reels.skip` («каркас
    # без канала содержимого»), и сюда они больше не доходят: их снимает более
    # ранняя ветка `name in skipped` этой же функции, которая теперь видит обе
    # подпапки реестра (`hf_catalog.skipped_positions`, ревью PR #90,
    # 07.09.2026). `filling_element` больше не считает такую позицию
    # держателем (`hf_montage.py`), и `frame_filler(scene)` здесь пуст ровно
    # тогда, когда в сцене не осталось ничего другого, чем закрыть кадр: ни
    # ведущей, ни вставки, ни схемы, ни другого элемента с каналом. Позиция
    # вида `effect` без канала не запрещена вовсе — она держится ПОВЕРХ
    # другого держателя (декор, как `aurora-drift`), и там `frame_filler` уже
    # не пуст.
    if (card.get("kind") in FRAME_KINDS and not content_channels(card)
            and frame_filler(scene) == ""):
        problems.append(
            f"{where_id}: позиция вида {card.get('kind')!r} без канала "
            "содержимого (ни `text_slots`, ни рабочей переменной, ни "
            "`media_slots`) сама по себе кадр не наполняет — это каркас "
            "позиции, а не содержание сцены, и держателем кадра стоять не "
            "может. Здесь она названа единственным содержимым, а больше "
            "кадр в этой сцене ничем не закрыт — дай сцене вставку, схему "
            "или полнокадровую ведущую, либо возьми позицию с каналом; эта "
            "годится только декором поверх другого держателя")
    # Слот под файл: позиция несёт рамку под кадр биролла или снимок, и без
    # файла в кадре остаётся пустой макет — телефон без экрана, панель «Before»
    # без картинки. Файл сцене даёт вставка, и спрашивается она здесь, ДО
    # заказа ведущей: после оплаты выбор уже не переиграть.
    if card.get("media_slots"):
        insert = insert_of(scene) or {}
        # Кадр, а не ролик: `<video>` в такой слот их линтер не пускает ни с
        # `data-start` (`video_nested_in_timed_element`), ни без него
        # (`media_missing_data_start`) — разобрано в `hf_slots._media_child`
        # и проверено живой сборкой. Кадр даёт вставка вида `photo`.
        if str(insert.get("kind") or "") != "photo":
            problems.append(
                f"{where_id}: позиция ждёт картинку в слоты "
                + ", ".join(f"`{one}`" for one in sorted(card["media_slots"]))
                + " — её даёт вставка сцены вида `photo`, а у сцены "
                + (f'вставка вида {insert.get("kind")!r}' if insert
                   else "вставки нет вовсе")
                + ". Поставь сцене `insert` с `kind: \"photo\"` или возьми "
                "позицию, которой своя картинка не нужна: без файла в кадре "
                "останется пустой макет")
    # Слот, содержимое которого их контракт ждёт `<template>`-ом в ХОСТОВОЙ
    # странице (`hf_slots.HOST_SLOT`). Наша сборка монтирует позицию
    # сабкомпозицией и такого шаблона не пишет — экран останется серым
    # скелетом-заглушкой, о чём предупреждает и сама позиция в `avoid_when`.
    if card.get("host_slots"):
        problems.append(
            f"{where_id}: содержимое слотов "
            + ", ".join(f"`{one}`" for one in sorted(card["host_slots"]))
            + " эта позиция ждёт разметкой из хостовой страницы, а наша сборка "
            "ставит её сабкомпозицией и такой разметки не пишет — в кадре "
            "останется серый скелет-заглушка. Возьми другую позицию")
    declared = card.get("variables") or {}
    named = element.get("variables")
    if named is not None and not isinstance(named, dict):
        problems.append(f"{where_id}: `variables` — объект «имя → значение»")
        named = {}
    for key, value in (named or {}).items():
        rule = declared.get(key)
        if rule is None:
            problems.append(
                f"{where_id}: переменной {key!r} у позиции нет, есть "
                + (", ".join(f"`{one}`" for one in sorted(declared))
                   or "ни одной"))
            continue
        kinds = _VARIABLE_TYPES.get(str(rule.get("type") or ""))
        # Булево в Python — тоже int, и без этой оговорки `true` прошло бы за
        # число, а число за булево.
        if kinds and (not isinstance(value, kinds)
                      or (isinstance(value, bool) and bool not in kinds)):
            problems.append(
                f"{where_id}: переменная {key!r} объявлена типом "
                f'{rule.get("type")}, а в плане {type(value).__name__}')
            continue
        options = rule.get("options")
        if options and value not in options:
            problems.append(
                f"{where_id}: переменная {key!r} принимает "
                + ", ".join(f"`{one}`" for one in options)
                + f", а в плане {value!r}")
            continue
        # Граница числа — их же клэмп (`conic-progress-ring.html:170-180`),
        # переставленный до заказа: за границей их скрипт молча подрезал бы
        # значение уже в оплаченном кадре, и план не узнал бы, что назвал не
        # то число.
        lo, hi = rule.get("min"), rule.get("max")
        if ((lo is not None or hi is not None)
                and isinstance(value, (int, float))
                and not isinstance(value, bool)):
            if lo is not None and value < lo:
                problems.append(
                    f"{where_id}: переменная {key!r} держит от {lo} до "
                    f"{hi if hi is not None else '∞'}, а в плане {value!r}")
            elif hi is not None and value > hi:
                problems.append(
                    f"{where_id}: переменная {key!r} держит от "
                    f"{lo if lo is not None else '−∞'} до {hi}, а в плане "
                    f"{value!r}")
    # Число из речи — второй канал содержания рядом со словами
    # (`hf_catalog.number_variables`): позиция без слотов разметки, чья
    # величина живёт переменной, без неё оставляет в кадре умолчание
    # карточки, а не то, что названо вслух. Спрашивается здесь, ДО заказа
    # ведущей, тем же доводом, что и слот под файл выше — после оплаты выбор
    # уже не переиграть.
    for number_key in number_variables(card):
        if number_key not in (named or {}):
            problems.append(
                f"{where_id}: позиция ждёт число из речи в переменную "
                f"`{number_key}` (`variables`), а план его не назвал")
    words = element.get("words")
    if words is not None and not isinstance(words, list):
        problems.append(f"{where_id}: `words` — список строк по числу слотов")
    elif words:
        # Слова ложатся либо в слоты разметки, либо — у позиции без слотов —
        # в её текстовые переменные (`hf_catalog.word_variables`): канал один
        # и тот же, «содержание кладёт код».
        slots = (card.get("text_slots") or []) or word_variables(card)
        if len(words) > len(slots):
            problems.append(
                f"{where_id}: слов {len(words)}, а мест под них у позиции "
                f"{len(slots)} — лишние в кадр не попадут")
    problems += _echo_problems(scene, element, card, where_id, caption_words)
    return problems


def _echo_problems(scene: dict, element: dict, card: dict, where_id: str,
                   caption_words: list | None) -> list[str]:
    """Слова позиции не пересказывают титр этой же секунды.

    Оба канала подстановки разом: `words` (слоты разметки) и текстовые
    значения `variables` — содержание кладёт код одним и тем же способом, и
    судить их порознь значило бы поймать одно и пропустить другое. Прогон
    `exp-beat-direction-2`, вариант Б, 6,4 с: слова доехали ПЕРЕМЕННОЙ
    (`chat-message.text`), а не слотом, и позиция напечатала «Составь
    сообщение, чтобы человек согласился со мной» ровно тогда, когда титр
    горел теми же словами.

    Правило до этой работы жило только у форм схемы и только прозой задания
    («одиночный ярлык-существительное … повторит слово, которое в эту секунду
    горит в титре», `hf_montage_skill.py`, форма `items`) — раздел про
    позиции каталога писался позже и её не получил. Здесь оно машинерией и
    одно на оба канала.

    `caption_words` — расшифровка ролика; её нет у D11 после сборки, и тогда
    сравнивать не с чем: молчим, как молчит рядом `target_absent`.
    """
    from reels_factory.hf_captions import caption_scene_words

    if not caption_words or "startSec" not in scene or "endSec" not in scene:
        return []
    spoken = caption_scene_words(caption_words, float(scene["startSec"]),
                                 float(scene["endSec"]))
    if not spoken:
        return []
    declared = card.get("variables") or {}
    texts = [str(one) for one in (element.get("words") or [])
             if isinstance(one, str)]
    for key, value in (element.get("variables") or {}).items():
        if isinstance(value, str) and str(
                (declared.get(key) or {}).get("type") or "") == "string":
            texts.append(value)
    problems = []
    for text in texts:
        echo = _caption_echo(text, spoken)
        if echo:
            problems.append(
                f"{where_id}: текст «{text}» повторяет титр этой же секунды "
                f"слово в слово («{echo}»). Слова реплики показывает титр, он "
                "идёт весь ролик и не молчит; позиция каталога — карточка, и "
                "она добавляет то, чего в озвучке нет: назови вещь, а не "
                "прочитай фразу заново")
            break
    return problems


def elements_problems(scenes: list[dict],
                      caption_words: list | None = None) -> list[str]:
    """Позиции каталога, названные планом, каталогу не противоречат.

    Список отдаётся наружу, а не сразу вердикт: по нему судят двое — D11 здесь,
    после сборки, и `D36_elements` до заказа ведущей (hf_render.py). Судят они
    одно и то же одним кодом — разойтись двум местам нечем.

    `caption_words` — расшифровка ролика, нужна лишь мишени `caption`
    (`target_absent`). До заказа она уже посчитана и передаётся; после
    сборки (D11, `_schema_problems`) её под рукой нет — тогда судить, есть
    ли в сцене названное словом, нечем, и та часть проверки молчит: элемент,
    которому в сцене не нашлось слова, сборка уже сняла бы сама
    (`hf_compose.drop_element`), и в раскадровке его не будет вовсе.
    """
    from reels_factory.hf_catalog import catalog_cards, skipped_positions
    from reels_factory.hf_montage import scene_elements

    try:
        cards = dict(catalog_cards())
        skipped = dict(skipped_positions())
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
            problems += _element_problems(scene, element, cards, skipped,
                                          caption_words)
    return problems


def frame_choice_problems(scenes: list[dict]) -> list[str]:
    """У каждой сцены названо, чем держится её кадр и что она сделала с
    каталогом. Пусто — план возвращается на пересдачу (`D36_elements`).

    Это покрытие, а не порог: сколько позиций каталога стоит в ролике, гейт не
    считает и считать не будет. Мерка — сказано или не сказано, ровно как у
    `D33_avatar_decisions`, где та же форма закрыла ту же дыру: сцена, которая
    решения не несёт, оставляет вместо него догадку кода.

    Причина, по которой поле понадобилось, измерена шестью живыми ранними
    шагами: проход по каталогу — единственный проход задания, который не
    оставляет следа, когда позиция не взята. Отличить «искал и не нашёл» от
    «не искал» было нечем, и в шести прогонах из шести агент не называл
    каталог вовсе (usewhen-report, density-report).

    Имена в `catalog_checked` с каталогом не сверяются: это след решения, а не
    заказ на установку. Ставит позицию поле `elements`, и его имена судит
    `elements_problems` — там неизвестное имя роняет сборку их же `add`.
    """
    from reels_factory.hf_montage import FRAME_HOLDERS

    problems = []
    for scene in scenes:
        scene_id = scene.get("id", "?")
        frame = scene.get("frame")
        if not isinstance(frame, dict):
            problems.append(f"{scene_id}: поля `frame` нет")
            continue
        holder = str(frame.get("holder") or "").strip()
        if holder not in FRAME_HOLDERS:
            problems.append(
                f"{scene_id}: `holder` — одно слово из списка "
                + ", ".join(f"`{word}`" for word in FRAME_HOLDERS)
                + (f", а в плане {holder!r}" if holder else ", а в плане пусто"))
        checked = frame.get("catalog_checked")
        if not isinstance(checked, list) or any(
                not isinstance(name, str) for name in checked):
            problems.append(
                f"{scene_id}: `catalog_checked` — список имён позиций, которые "
                "ты рассмотрел для этой сцены; ни одной — пустой список")
        if not str(frame.get("catalog_reason") or "").strip():
            problems.append(
                f"{scene_id}: `catalog_reason` — одна фраза о том, почему "
                "позиция взята или почему не взята")
    return problems


def plan_elements_gate(scenes: list[dict],
                       caption_words: list | None = None) -> dict:
    """`D36_elements` ДО сборки: план назвал, чем держится кадр, и не спорит
    с каталогом.

    Единственное место, где считается этот вердикт, — так его зовут и путь
    раннего плана (`_early_plan_gates`, hf_render.py, работа 9, до заказа
    ведущей), и цикл пересдачи `assemble_hyperframes`: план, который вернул
    агент на пересдаче после заказа, спрашивают о том же — назвал ли он кадр
    и позицию каталога, — а не только о том, лёг ли он на озвучку
    (`check_shots`/`check_inserts`) и что из названного дошло до кадра
    (`elements_delivered`, ниже). Без этого вызова план, вернувшийся с
    пустым `frame` и `elements`, проходил пересдачу зелёным — так и вышло на
    проде 07.09.2026 (`rb0907-ai-employee`, `rb0907-university`).

    Складывает два независимых изъяна одной сцены — молчание про кадр
    (`frame_choice_problems`) и спор с каталогом (`elements_problems`) — в
    один вердикт, потому что задание называет их агенту одним пунктом сверки
    и одним именем гейта (`hf_brief.py`, пункт «У каждой сцены заполнен
    `frame`…»): развести их значило бы разойтись с текстом, который агент уже
    читал.
    """
    named = elements_problems(scenes, caption_words)
    silent_frame = frame_choice_problems(scenes)
    trouble = []
    if silent_frame:
        trouble.append(
            "поле `frame` стоит у каждой сцены: чем держится её кадр "
            "(`holder`), какие позиции каталога ты рассмотрел "
            "(`catalog_checked`) и почему взял или не взял (`catalog_reason`). "
            "Без него не отличить сцену, которой каталог не подошёл, от сцены, "
            "по которой ты каталог не смотрел: " + "; ".join(silent_frame))
    if named:
        trouble.append(
            "позицию каталога код ставит их же `hyperframes add`, и "
            "неизвестное имя он не ставит вовсе — сборка встанет уже с "
            "оплаченной ведущей. Имена, слоты и переменные позиций "
            "перечислены в `catalog.index.md` рядом с заданием: "
            + "; ".join(named))
    return {"D36_elements": "PASS" if not trouble else "FAIL: "
                            + " ".join(trouble)}


#: Вердикт гейта, который нашёл изъян, но ролик им не заворачивает. От FAIL
#: отличается намеренно: ведущая уже куплена, ролик доезжает до заказчика, и
#: изъян остаётся в карточке словом (решение 05, Вася) — а не пропадает.
WARNED_VERDICT = "WARN"


def elements_delivered(plan: dict, storyboard: dict) -> dict:
    """`D36_elements` после сборки: что просил агент — и что доехало в кадр.

    До заказа тот же гейт судит имена, переменные и геометрию плана
    (`elements_problems`, hf_render.py). После сборки повторять ту же сверку
    бессмысленно: раскадровка обязана описывать собранный кадр, поэтому
    позицию, которая в кадр не встала, сборка из `scene["elements"]`
    вычищает — и `elements_problems` по раскадровке видит пустой список, а не
    пропажу. Пересборка `artyom-rebuild-4b` прошла так с зелёным
    `D36_elements`, потеряв `count-up`.

    Поэтому сравниваются два файла: `plan.json` — то, что вернул агент,
    `storyboard.json` — то, что собралось. Причину берём оттуда, где её
    знают, — из следа сборки (`hf_compose.DROPPED_ELEMENTS`).

    Вердикт под тем же ключом `D36_elements` считает и `plan_elements_gate`
    (выше) — на последней попытке цикла `assemble_hyperframes`, где красный
    гейт больше не роняет сборку (решение 05), оба вердикта уходят в один
    отчёт. Изъян, который нашёл `plan_elements_gate` (сцена молчит про
    `frame` или называет каталогу неизвестное имя), эта функция не видит и не
    лечит: она сравнивает то, что уже стоит в `plan.json` дальше, с тем, что
    доехало в кадр, — а не спрашивает план заново, назвал ли он кадр вообще.
    Поэтому PASS/WARN отсюда не вправе заменить FAIL `plan_elements_gate` под
    тем же ключом — сливает их вызывающая сторона (`assemble_hyperframes`),
    FAIL там побеждает.
    """
    from reels_factory.hf_compose import DROPPED_ELEMENTS
    from reels_factory.hf_montage import scene_elements

    why = {(str(note.get("scene")), str(note.get("name"))): str(note.get("why"))
           for note in storyboard.get(DROPPED_ELEMENTS) or []
           if isinstance(note, dict)}
    built = {str(scene.get("id")): {str(element["name"]).strip()
                                    for element in scene_elements(scene)}
             for scene in storyboard.get("scenes") or []}
    lost = []
    for scene in plan.get("scenes") or []:
        scene_id = str(scene.get("id"))
        for element in scene_elements(scene):
            name = str(element["name"]).strip()
            if name in built.get(scene_id, set()):
                continue
            # Сцены в раскадровке нет вовсе — её секунды ушли соседке
            # (`absorb_scene`) или пара склеилась в один кусок
            # (`dedupe_neighbours`), и элемент уехал вместе со сценой.
            reason = why.get((scene_id, name)) or (
                "сцена не дошла до кадра — её секунды сведены с соседней"
                if scene_id not in built else "причину сборка не назвала")
            lost.append(f"{scene_id}: {name} — {reason}")
    if not lost:
        return {"D36_elements": "PASS"}
    return {"D36_elements": f"{WARNED_VERDICT}: позиция каталога, названная "
                            "планом, в кадр не встала — агент выбирал её под "
                            "содержание сцены, и кадр вышел беднее плана: "
                            + "; ".join(lost)}


def schema_position_problems(scenes: list[dict],
                             face: dict | None = None) -> list[str]:
    """Схеме есть куда встать при том положении ведущей, что назвал план.

    Вопрос здесь один и геометрический: «зона есть или нет». Считает её тот
    же `hf_compose.schema_zone`, которым сборка ставит коробку схемы, — своего
    списка положений у гейта нет и быть не может, иначе список и кадр
    разойдутся при первой же правке прямоугольников.

    Что зону закрывает: окно ведущей (`hf_layout.VIDEO_RECTS`), её лицо
    (`face.json`) и полоса титра. Прогон `rb0907-philosophers`, сцена `s-08`
    (`presenter: "punch"` + `schema.form: "brand"`) лёг ровно потому, что
    геометрию схемы считал один `hf_schema.build`, который ни о ведущей, ни о
    лице не знает: карточка бренда центровалась в полосе `0..980` и попала на
    лицо.

    `face` есть не всегда, и это не небрежность вызывающего, а порядок
    прогона: `face.json` пишет `prepare` вместе с клипами
    (`hf_render.py:1628`), то есть уже после HeyGen, а ранний гейт судит план
    ДО заказа (`write_brief(..., face=None)`, hf_render.py:1497). Без замера
    полнокадровая ведущая закрывает кадр целиком, и обещать схеме полосу
    нечем — `schema_zone` отвечает `None`, и план отклоняется до денег. После
    сборки (`D11_schema`) замер уже есть, и та же функция отвечает по нему:
    сцена, где лицо стоит достаточно высоко, схему сохраняет — ужатой в
    полосу под лицом.
    """
    from reels_factory.hf_compose import SCHEMA_MIN_SCALE, schema_zone
    from reels_factory.hf_montage import schema_safe_presenter
    from reels_factory.hf_schema import SAFE_BOTTOM

    problems = []
    need = round(SCHEMA_MIN_SCALE * SAFE_BOTTOM)
    for scene in scenes:
        if not schema_scene(scene):
            continue
        position = str(scene.get("presenter") or "none")
        if schema_zone(position, face=face) is not None:
            continue
        # Зоны нет по одной из двух причин, и агенту важна разница: при
        # уголке или половине полоса есть, просто короткая, а при
        # полнокадровой ведущей до заказа обещать нечего вовсе — лицо ещё не
        # измерено. Полосу меряем той же функцией с нулевым полом, а не
        # вторым счётом.
        free = schema_zone(position, face=face, min_height=0)
        room = (f'ей остаётся {free["height"]} px' if free else
                "ведущая кроет кадр целиком, а где в нём окажется её лицо, "
                "до заказа неизвестно")
        corners = "/".join(f"`{name}`" for name in schema_safe_presenter())
        problems.append(
            f'{scene.get("id", "?")}: схеме нужна полоса кадра выше слов '
            f"титра и вне лица ведущей — не меньше {need} px, иначе подписи "
            f"в ней уже не прочесть. При `{position}` {room}. Дай сцене "
            f"уголок {corners}, либо сними схему")
    return problems


def _schema_problems(storyboard: dict, face: dict | None = None) -> list[str]:
    """Расхождения с их схемой v3 (SKILL.md:130-165, 610-616).

    Схема их, но список сцен у нас называется `scenes`, а не `cards`: карточкой
    была непрозрачная сцена во весь кадр, и этого объекта в кадре больше нет.
    Схему это не ломает — их же дока говорит про `storyboard.json`, что «no CLI
    command consumes it» (talking-head-recut/SKILL.md:125): файл существует,
    чтобы решения были явными, а разбирает его только наш код.
    """
    problems = []
    # Решение о ритме — одно на весь ролик, и его агент обязан назвать
    # раньше сцен: `direct()` (`hf_montage.py`) превращает его в числа по
    # каждой сцене ДО раскладки, и без него подставить нечего, только
    # умолчание. Проверяем здесь, а не молчаливым дефолтом в коде компоновки:
    # план без `direction` — не то же самое, что план, где агент осознанно
    # выбрал `steady`, а гейту нужно различить незаполненное поле и
    # обдуманный выбор.
    direction = storyboard.get("direction")
    if not isinstance(direction, dict):
        problems.append(
            "нет поля `direction` — сначала одно решение на весь ролик: "
            "`world` (где зритель и что переживает) и `rhythm` (паттерн из "
            "свода правил, раздел «Режиссура»)")
    else:
        if not str(direction.get("world") or "").strip():
            problems.append(
                "`direction.world` пуст — назови, где зритель и что он "
                "переживает, одной-двумя строками")
        rhythm = direction.get("rhythm")
        if rhythm not in RHYTHM_NAMES:
            problems.append(
                f"`direction.rhythm` {rhythm!r} неизвестен, есть "
                f"{', '.join(RHYTHM_NAMES)}")
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
        problems += schema_position_problems([scene], face)
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
        # Схема закрывает кадр наравне со вставкой: она занимает полосу над
        # титром, и нижний уголок ведущей лежит ниже неё
        # (`hf_compose.schema_zone` при таком положении отдаёт полосу целой).
        # Считается и запланированная, а не только отрисованная: гейт судит и
        # до сборки — а схему, которая в кадр не встала, `drop_schema` снимает
        # вместе с уголком.
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
                     duration: float = 0.0,
                     face: dict | None = None) -> dict:
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
    # D13 (плотность) — пол `ceil(duration / holdMax)` следует из того, что
    #   сцены обязаны выстилать ролик без дыр и ни одна не длиннее потолка
    #   паттерна ритма; и то и другое роняет `lay_out_scenes` раньше гейтов.
    #   Сама `min_scenes` жива — её число идёт агенту в задание.
    # D23 (грамматика серий) — число планов роняет `check_shots` до подбора,
    #   а длину серии и лицо между сериями обеспечивает отбор `pick_series`.
    #   D24 (доля аватара) остаётся: она ловит дрейф ПОСЛЕ отбора, когда
    #   `settle_inserts` переводит сцену без вставки на полнокадровую ведущую.
    #
    # D10 (зона карточки из списка пяти) снят раньше: зон в слоёном кадре нет.
    result = {"D11_schema": gate(_schema_problems(storyboard, face)),
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
