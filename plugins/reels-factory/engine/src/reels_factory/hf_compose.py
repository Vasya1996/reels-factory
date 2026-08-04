"""Сборка `public/index.html` по плану агента.

Раньше композицию писал агент: 670 строк, из них 200 — таймлайн и 72 — спаны
субтитров. Потом — только карточки своей вёрстки, и это всё ещё было 42 тысячи
токенов на выходе, то есть четверть часа прогона. Теперь агент не пишет
разметку вовсе: он называет блок каталога и содержимое его слотов, а сцену
ставит код.

Правку самих блоков делает их редактор композиций (`hf_sdk.py`,
`@hyperframes/sdk`): элементы, их атрибуты, собственный текст и твины, которые
в элемент целятся, читает он, и правки идут его операциями.

Сам файл композиции собирается здесь, из шаблона `templates/reel.html`. Их SDK
это не умеет и не заявляет: он открывает **существующую** композицию
(`packages/sdk/src/session.ts:858`), а единственная его операция, добавляющая
разметку, отказывает на любом фрагменте со `<script>`
(`packages/sdk/src/engine/mutate.ts:1649-1652`). Наша композиция без скриптов
невозможна: их же компонент субтитров подключается вставкой куска с `<script>`
(`docs/catalog/components/caption-highlight.mdx`), а `addGsapTween` требует
уже объявленного таймлайна (`packages/sdk/src/engine/mutate.ts:1747-1749`).
Поэтому каркас — данные (шаблон), а не код: структура ролика в него не зашита,
и подставить вместо него готовый шаблон проекта можно будет без правок здесь.

Субтитры не наши: их пословный караоке-титр берётся готовым компонентом
`caption-highlight` из их реестра (`hf_captions.py`).
"""
from __future__ import annotations

import json
from pathlib import Path

from reels_factory.config import FPS, OUT_H, OUT_W
from reels_factory.hf_captions import caption_snippet, write_caption_data
from reels_factory.hf_layout import VIDEO_RECTS, quantize
from reels_factory.hf_sdk import set_timing
from reels_factory.hf_slots import (
    fill_ops, find_slots, min_card_seconds, prune_timeline,
)

#: Слои кадра. Ведущая под карточками: блок каталога — непрозрачная сцена во
#: весь кадр, и там, где ведущая нужна, она стоит внутри самого блока.
TRACK_VIDEO = 2
TRACK_CARD = 5
TRACK_CAPTION = 8
TRACK_AUDIO = 20

#: Отступ титра от низа кадра. Нижняя граница их вилки для 9:16
#: (embedded-captions/references/rail.md:20-21): выше — начинает спорить с
#: карточками, ниже — попадает под интерфейс платформы.
CAPTION_BOTTOM = 620

#: Полоса, которую титр занимает: две строки кегля 80 плюс отступы.
CAPTION_BAND = {"left": 0, "top": OUT_H - CAPTION_BOTTOM - 260,
                "width": OUT_W, "height": 260}

#: Каркас композиции. Файл, а не строка в коде: следующим шагом на его место
#: встанет готовый шаблон проекта с объявленными `data-composition-variables`.
TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "reel.html"

#: Наименьший кусок паузы, который стоит показывать отдельным планом. Порог
#: привязан к наименьшему зазору между карточками (0,8 с): агент ставит зазоры
#: ровно по нижней границе, и на пороге в полсекунды наезд не срабатывал ни
#: разу — прогон 04.08 дал 18 смен вместо 20 при десяти карточках.
PUNCH_MIN_HALF = 0.35


def _q(value: float) -> float:
    return quantize(float(value))


def _rect_style(rect: dict) -> str:
    return (f'left:{rect["left"]}px;top:{rect["top"]}px;'
            f'width:{rect["width"]}px;height:{rect["height"]}px')


def _js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _clean_text(text: dict[str, str]) -> dict[str, str]:
    """Убрать из текста плана разделитель плашки-рубрики.

    Гейт D17 считает `·` на экране служебной надписью и заворачивает сборку
    целиком. В прогоне 03.08 повторную сессию агента — четверть часа — вызвала
    ровно одна такая точка в его собственном тексте. Запрет стоит и в задании,
    но полагаться на то, что модель его соблюдёт, дороже, чем срезать точку
    здесь: смысла строки она не несёт.
    """
    return {key: " ".join(str(value or "").replace("·", " ").split())
            for key, value in text.items()}


# -------------------------------------------------------------------- блоки

def _stage_block(sdk, public: Path, card: dict, block: str, *, duration: float,
                 text: dict, media: dict) -> str:
    """Положить блок под карточку своей копией и вернуть её имя файла.

    Копия на карточку, а не общий файл: один блок может встретиться дважды, а
    ключ таймлайна у сабкомпозиции один на `data-composition-id` — два хоста с
    одним ключом затёрли бы друг друга.
    """
    source = public / "compositions" / f"{block}.html"
    if not source.exists():
        raise RuntimeError(
            f"блок {block} не установлен: нет {source}. Ставит его код "
            "командой `hyperframes add` перед сборкой")
    unique = f'{block}--{card["id"]}'
    sdk.open(unique, source)
    nodes = sdk.elements(unique)
    native = next((float(n.attrs.get("data-duration") or 0) for n in nodes
                   if n.attrs.get("data-composition-id")), 0.0)
    # Сцена блока собирается своим таймлайном за родную длительность. Обрезать
    # её сильно короче — значит показать полусобранную сцену: на прогоне 04.08
    # блок g05 родной длительности 4,5 с стоял 1,2 с, и в кадре была пустота с
    # одним титром. Растянуть чужой таймлайн нечем: он живёт в `<script>` блока.
    floor = min_card_seconds(native) if native else 0.0
    if floor and duration < floor - 0.001:
        raise RuntimeError(
            f'{card["id"]}: блок {block} собирается {native:g} с, а карточке '
            f"отведено {duration:.2f} с — сцена не успеет собраться. Дай ей "
            f"не меньше {floor:g} с (это число стоит в паспорте блока) или "
            "возьми блок короче")
    ops = fill_ops(nodes, text=text, media=media)
    # Длительность блока — карточкина: родная (3–8 с) оставила бы после себя
    # замерший хвост или обрезала сцену на середине. Правим и корень
    # композиции, и его клип: рантайм смотрит на оба.
    for node in nodes:
        if node.attrs.get("data-composition-id") or node.has_class("clip"):
            ops.append(set_timing(node.hfid, duration=round(duration, 4)))
    sdk.dispatch(unique, ops)
    target = public / "compositions" / f"{unique}.html"
    sdk.save(unique, target)
    sdk.close(unique)
    # Что осталось текстом. Имя композиции их SDK менять не даёт вовсе —
    # «data-composition-id is a reserved composition attribute and cannot be
    # reassigned» (`packages/sdk/src/engine/mutate.ts`), а тело `<script>` он не
    # правит по устройству: «GSAP is managed by the composition's single script
    # block» (там же:1653). Копия блока обязана называться по-своему, иначе две
    # карточки одного блока затрут друг другу таймлайн.
    html = target.read_text(encoding="utf-8")
    html = html.replace(f'data-composition-id="{block}"',
                        f'data-composition-id="{unique}"')
    html = html.replace(f'__timelines["{block}"]', f'__timelines["{unique}"]')
    target.write_text(prune_timeline(html), encoding="utf-8")
    return unique


def block_slots(sdk, public: Path, block: str) -> list:
    source = public / "compositions" / f"{block}.html"
    name = f"passport--{block}"
    sdk.open(name, source)
    slots = find_slots(sdk.elements(name))
    sdk.close(name)
    return slots


# ------------------------------------------------------------------ ведущая

def _clip_for(clips: list[dict], start: float) -> dict | None:
    for clip in clips:
        if clip["start"] <= start + 1e-6 < clip["start"] + clip["duration"]:
            return clip
    return None


def _presenter_media(clips: list[dict], card: dict) -> dict | None:
    """Кусок клипа под карточку: какой файл и с какого места внутри него."""
    start, end = _q(card["startSec"]), _q(card["endSec"])
    clip = _clip_for(clips, start)
    if not clip:
        return None
    tail = clip["start"] + clip["duration"] - start
    return {"file": clip["file"], "start": 0.0,
            "duration": round(min(end - start, tail), 3),
            "media_start": round(start - clip["start"], 3)}


def _presenter_rect(name: str) -> dict:
    rect = VIDEO_RECTS.get(name)
    if rect is None:
        raise RuntimeError(
            f"положение ведущей {name!r} неизвестно; есть {sorted(VIDEO_RECTS)}")
    return rect


#: Ключ подобранной вставки: карточка и слот.
def media_key(card_id: str, slot: str) -> str:
    return f"{card_id}::{slot}"


def _card_words(card: dict) -> str:
    """Чем карточка держит зрителя — словами самой карточки."""
    hints = card.get("contentHints") or {}
    parts = [str(hints.get(key) or "") for key in ("title", "detail", "kicker")]
    parts.append(str(card.get("intent") or ""))
    return " ".join(part for part in parts if part).strip()


def photo_slots(sdk, public, block: str) -> list[str]:
    """Слоты блока под картинку — все, кроме окна ведущей."""
    return [slot.name for slot in block_slots(sdk, public, block)
            if slot.kind in ("image", "video") and slot.role != "presenter"]


def collect_intents(sdk, public, storyboard: dict) -> list[dict]:
    """Все намерения под вставки: из плана, а где его нет — из слов карточки.

    Агент называет словами, что должно быть на экране, и подбор делает код.
    Но выбрав блок с фотослотом, он этим уже решил, что там фотография; если
    намерение он назвать забыл, слот уехал бы пустым и гейт D16 завернул бы
    сборку — прогон 04.08 потерял на этом целую сессию, четверть часа. Поэтому
    пустое намерение достраивается из собственных слов карточки: сцену выбрал
    агент, а слова в ней — его же.
    """
    requests = []
    for card in storyboard.get("cards") or []:
        render = card.get("render") or {}
        block = render.get("block")
        if not block:
            continue
        named = {name: value for name, value in (render.get("media") or {}).items()
                 if isinstance(value, str) and value.strip()}
        for name in photo_slots(sdk, public, block):
            intent = named.get(name) or _card_words(card)
            if not intent:
                continue
            requests.append({"key": media_key(card["id"], name),
                             "type": "image", "intent": intent.strip()})
    return requests


def complete_storyboard(board: dict, *, clips: list[dict],
                        duration: float) -> dict:
    """Дописать шапку раскадровки: она целиком выводится из материала.

    `schemaVersion`, `composition`, `videoTrack` и `subtitles` решений не
    содержат — размер кадра, частота, длительность и путь к клипу известны до
    агента. Прогон 03.08 на Sonnet потерял на этом попытку: агент отдал
    `videoTrack` списком по клипу на запись, гейт схемы искал `bounds` и
    заворачивал сборку. Спрашивать у агента то, что мы знаем сами, — способ
    получить расхождение, а не план.

    Зона карточки тоже выводится: карточка теперь всегда блок каталога, а блок
    — непрозрачная сцена во весь кадр.
    """
    board = dict(board)
    board["schemaVersion"] = 3
    board["composition"] = {
        "fps": FPS, "width": OUT_W, "height": OUT_H,
        "durationSeconds": _q(duration), "layout": "portrait",
        "themeId": (board.get("composition") or {}).get("themeId", "noir"),
        "seed": (board.get("composition") or {}).get("seed", 42),
    }
    board["videoTrack"] = {
        "sourcePath": clips[0]["file"] if clips else "clips/clip-00.mp4",
        "startSec": 0, "endSec": _q(duration),
        "bounds": {"x": 0, "y": 0, "width": OUT_W, "height": OUT_H},
    }
    board["subtitles"] = {"enabled": True}
    for card in board.get("cards") or []:
        render = card.setdefault("render", {})
        render.setdefault("kind", "block")
        card["zone"] = "fullscreen"
    return board


def build_composition(rdir, sdk, *, storyboard: dict, clips: list[dict],
                      duration: float, words: list[dict],
                      resolved: dict[str, dict] | None = None) -> Path:
    """Собрать `public/index.html`. Возвращает путь к нему."""
    rdir = Path(rdir)
    public = rdir / "public"
    cards = sorted(storyboard.get("cards") or [],
                   key=lambda card: float(card["startSec"]))
    duration = _q(duration)
    resolved = resolved or {}

    body: list[str] = []
    timeline: list[str] = []

    # ── ведущая ───────────────────────────────────────────────────────────
    # `class="clip"` обязателен на каждом элементе с временем — их квикстарт
    # называет это правилом: «timed elements need data-start, data-duration,
    # data-track-index and class="clip"»
    # (https://hyperframes.heygen.com/quickstart). Тот же класс стоит на
    # `<video>` в примере композиции на главной их репозитория. Без него клип
    # с ведущей в кадре не появляется вовсе: окно на месте, внутри пусто.
    videos = "\n".join(
        f'      <video class="clip" id="clip-{index:02d}" src="{clip["file"]}"'
        f' muted playsinline'
        f' data-start="{_q(clip["start"]):.4f}"'
        f' data-duration="{_q(clip["duration"]):.4f}"'
        f' data-track-index="{TRACK_VIDEO}"></video>'
        for index, clip in enumerate(clips))
    moments = presenter_timeline(cards, clips, duration)
    first = moments[0][1] if moments else "full"
    initial = next((name for _, name in moments if name != "none"), "full")
    style = _rect_style(_presenter_rect(initial))
    if first == "none":
        style += ";visibility:hidden;opacity:0"
        timeline.append('tl.set("#video-wrap", { autoAlpha: 0 }, 0);')
    body.append(f'    <div id="video-wrap" style="{style}">\n'
                f"{videos}\n    </div>")
    previous = first
    for time, position in moments[1:]:
        timeline += _presenter_move(previous, position, _q(time))
        previous = position

    # ── карточки ──────────────────────────────────────────────────────────
    for card in cards:
        start, end = _q(card["startSec"]), _q(card["endSec"])
        render = card.get("render") or {}
        block = render.get("block")
        if not block:
            raise RuntimeError(
                f'{card["id"]}: не назван блок каталога. Карточка собирается '
                "только блоком; если подходящего нет, это дырка каталога — "
                "её место в списке пробелов, а не в вёрстке на лету")
        media = {}
        for slot in block_slots(sdk, public, block):
            if slot.role == "presenter":
                piece = _presenter_media(clips, card)
                if piece:
                    media[slot.name] = piece
        for name in photo_slots(sdk, public, block):
            found = resolved.get(media_key(card["id"], name)) or {}
            # Не подобралась — слот уедет пустым, как незаполненный. Ронять
            # из-за одной картинки весь прогон дорого: каталог отвечает не на
            # каждое намерение. Что вставок не осталось совсем, ловит D16.
            if found.get("file"):
                media[name] = {"file": found["file"]}
        unique = _stage_block(sdk, public, card, block, duration=end - start,
                              text=_clean_text(render.get("text") or {}),
                              media=media)
        # `class="clip"` обязателен и на хосте сабкомпозиции: без него рантайм
        # держит элемент видимым весь ролик и не смотрит на
        # data-start/data-duration. Блок — непрозрачная сцена во весь кадр,
        # поэтому забытый класс кроет ведущую от начала и до конца.
        body.append(
            f'    <div id="host-{card["id"]}" class="clip"'
            f' data-composition-id="{unique}"'
            f' data-composition-src="compositions/{unique}.html"'
            f' data-start="{start:.4f}" data-duration="{end - start:.4f}"'
            f' data-track-index="{TRACK_CARD}"'
            f' data-width="{OUT_W}" data-height="{OUT_H}"></div>')
        # Титр под карточкой гасим таймлайном, а не только выброшенными словами.
        # Компонент держит группу слов на экране до начала следующей, поэтому
        # последняя группа паузы доживала до пришедшей сцены и ложилась поверх
        # неё — кадр 13,3 с прогона 04.08.
        timeline.append(f'tl.set("#highlight", {{ autoAlpha: 0 }}, {start});')
        timeline.append(f'tl.set("#highlight", {{ autoAlpha: 1 }}, {end});')

    # ── субтитры ──────────────────────────────────────────────────────────
    write_caption_data(public, words=words, cards=cards, duration=duration)
    body.append(caption_snippet(sdk, public, track_index=TRACK_CAPTION,
                                duration=duration))

    body.append(
        f'    <audio id="voice" src="voice.wav" data-start="0"'
        f' data-duration="{duration:.4f}" data-track-index="{TRACK_AUDIO}"'
        f' data-volume="1"></audio>')

    html = TEMPLATE.read_text(encoding="utf-8")
    for name, value in (("__W__", str(OUT_W)), ("__H__", str(OUT_H)),
                        ("__FPS__", str(FPS)),
                        ("__CAPTION_BOTTOM__", str(CAPTION_BOTTOM)),
                        ("__DURATION__", f"{duration:.4f}"),
                        ("__BODY__", "\n".join(body)),
                        ("__TIMELINE__",
                         "\n".join("          " + line for line in timeline))):
        html = html.replace(name, value)
    target = public / "index.html"
    target.write_text(html, encoding="utf-8")

    # Раскадровку переписываем округлённой: гейт сетки кадров должен судить те
    # времена, что реально встали в композицию, а не те, что назвал агент.
    for card in cards:
        card["startSec"], card["endSec"] = _q(card["startSec"]), _q(card["endSec"])
    storyboard["cards"] = cards
    (rdir / "storyboard.json").write_text(
        json.dumps(storyboard, ensure_ascii=False, indent=1), encoding="utf-8")
    return target


def presenter_timeline(cards: list[dict], clips: list[dict],
                       duration: float) -> list[tuple]:
    """Где общее окно ведущей в каждый момент ролика.

    Под карточкой его нет никогда: карточка — блок каталога, непрозрачная
    сцена во весь кадр, и ведущая там либо внутри сцены, либо её нет вовсе.
    Верить полю `presenter` из плана нельзя было ровно по этой причине: прогон
    03.08 назначил `pip-tr` и `split` карточкам-блокам, окно послушно переехало
    и осталось за сценой — проба насчитала два положения вместо четырёх.

    Между карточками зритель смотрит на ведущую во весь кадр. Без этого правила
    после сцены, где ведущая жила внутри блока, кадр оставался чёрным до самой
    следующей карточки.
    """
    moments: list[tuple[float, str]] = []
    cursor = 0.0
    frame = 1.0 / FPS

    def pause(start: float, end: float) -> None:
        """Пауза между карточками: полный кадр, а на длинной — ещё и наезд.

        Пауза одним неподвижным планом — потерянная смена картинки: детектор
        сцен видит только приход и уход карточки. В эталонных рилсах пауза
        всегда разрезана «попом» — наездом на ведущую. Режем ровно посередине
        и только там, где паузы хватает на оба куска.
        """
        if not _clip_for(clips, start):
            moments.append((start, "none"))
            return
        moments.append((start, "full"))
        if end - start >= 2 * PUNCH_MIN_HALF:
            moments.append((_q((start + end) / 2), "punch"))

    for card in cards:
        start, end = _q(card["startSec"]), _q(card["endSec"])
        if start - cursor > frame:
            pause(cursor, start)
        moments.append((start, "none"))
        cursor = max(cursor, end)
    if duration - cursor > frame:
        pause(cursor, duration)

    collapsed: list[tuple[float, str]] = []
    for time, position in moments:
        if not collapsed or collapsed[-1][1] != position:
            collapsed.append((time, position))
    return collapsed


def _presenter_move(previous: str, position: str, at: float) -> list[str]:
    """Перестановка окна ведущей мгновенная — стыком, а не переездом.

    Твин по `left`/`top` их линтер заворачивает ошибкой
    `gsap_non_transform_motion`: эти свойства прилипают к целому пикселю при
    вёрстке, и на покадровой съёмке медленное движение дёргается. Через
    трансформы нельзя: раскладки меняют пропорции окна, и неравномерный `scale`
    раздавил бы кадр. А эталонным рилсам переезд и не нужен — там смена
    положения всегда на стыке.
    """
    if position == "none":
        return [f'tl.set("#video-wrap", {{ autoAlpha: 0 }}, {at});']
    rect = _presenter_rect(position)
    # Скругление и кант PiP переключаем атрибутом, а не `className`: плагин
    # className у GSAP снимает разницу стилей до и после смены класса и
    # возвращает то, что считает «классовым», — вместе с ним он возвращал
    # `visibility:hidden` из строки стиля, и окно ведущей больше не
    # появлялось. Проверено пробой: rect правильный, visible=false.
    pill = "pip-pill" if position.startswith("pip") else ""
    return [
        f'tl.set("#video-wrap", {{ attr: {{ class: {_js(pill)} }},'
        f' left: {rect["left"]}, top: {rect["top"]},'
        f' width: {rect["width"]}, height: {rect["height"]},'
        f' autoAlpha: 1 }}, {at});']


def clear_generated(public: Path) -> None:
    """Убрать копии блоков прошлой попытки: имя копии зависит от карточки."""
    compositions = public / "compositions"
    if not compositions.exists():
        return
    for path in compositions.glob("*--*.html"):
        path.unlink()
