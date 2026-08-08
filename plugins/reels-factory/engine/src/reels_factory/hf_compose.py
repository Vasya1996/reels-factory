"""Сборка `public/index.html` по плану агента.

Кадр собирается слоями, а не чередой непрозрачных сцен. Это их же канон:
«For full-frame motion … prefer a **shared background layer + transparent timed
content layers** over stacked opaque scene backgrounds. Stacking opaque scene
divs means every scene change has to repaint the entire frame»
(hyperframes-core/references/full-screen-motion.md:3-7).

Слои снизу вверх:

1. вставка — подобранный `media-use` файл, обычный `<img>`/`<video>` во весь
   кадр либо в половине, где ведущей нет;
2. ведущая — клип в обёртке, обёртке таймлайн меняет геометрию. Обёртка без
   `data-*` — так велит их рецепт PiP: «Animate a wrapper div for
   position/size. The video fills the wrapper. The wrapper has NO data
   attributes» (hyperframes-creative/references/composition-patterns.md:11-14);
3. субтитры — их готовый компонент `caption-highlight` (`hf_captions.py`);
4. звук — мастер-дорожка.

Порядок слоёв держит CSS `z-index`, а НЕ `data-track-index`. Их дока в одном
месте обещает обратное («Controls z-ordering (higher = in front)»,
docs/reference/html-schema.mdx:56), но код говорит прямо: «Track index is
display-only; render never reads it» (packages/core/src/runtime/timeline.ts:599),
и вторая страница доков это подтверждает — «Does not control z-ordering (use CSS
z-index for that)» (docs/concepts/data-attributes.mdx:14). `data-track-index`
остаётся дорожкой времени: на одной дорожке клипы пересекаться не могут, иначе
их линтер даёт ошибку `overlapping_clips_same_track`
(packages/lint/src/rules/composition.ts:614).

Сам файл композиции собирается из шаблона `templates/reel.html`. Их SDK это не
умеет и не заявляет: он открывает **существующую** композицию
(`packages/sdk/src/session.ts:858`), а единственная его операция, добавляющая
разметку, отказывает на любом фрагменте со `<script>`
(`packages/sdk/src/engine/mutate.ts:1649-1652`). Наша композиция без скриптов
невозможна: их же компонент субтитров подключается вставкой куска с `<script>`
(`docs/catalog/components/caption-highlight.mdx`).

Блоки нашего каталога здесь больше не ставятся. Слой подстановки (`hf_slots.py`)
и сам каталог (`hf_catalog.py`) остались на месте: вернуть их — одна строка в
задании агенту.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from reels_factory.config import FPS, OUT_H, OUT_W
from reels_factory.hf_captions import caption_snippet, write_caption_data
from reels_factory.hf_layout import (
    VIDEO_RECTS, avatar_gaps, in_avatar_gap, insert_rect, quantize,
)
from reels_factory.hf_media import insert_problem

#: Дорожки времени. На одной дорожке клипы не пересекаются — это единственное,
#: что `data-track-index` значит на самом деле.
TRACK_VIDEO = 2
TRACK_INSERT = 3
TRACK_CAPTION = 90
TRACK_AUDIO = 99

#: Сколько вставок кладём на одну дорожку. Их линтер за четвёртую даёт
#: предупреждение `timeline_track_too_dense`
#: (packages/lint/src/rules/composition.ts:17,409), а под `--strict`
#: предупреждение роняет сборку. Теги `video` и `audio` из этого счёта
#: исключены (там же:18), поэтому клипы ведущей и звук делить не надо. Раскладка
#: по дорожкам — ровно то, как выглядит любая монтажка: несколько дорожек, на
#: каждой непересекающиеся клипы. На порядок отрисовки это не влияет вовсе
#: (`timeline.ts:599`), его держит z-index.
INSERTS_PER_TRACK = 3

#: Отступ титра от низа кадра. Нижняя граница их вилки для 9:16
#: (embedded-captions/references/rail.md:20-21): выше — начинает спорить с
#: картинкой, ниже — попадает под интерфейс платформы.
CAPTION_BOTTOM = 620

#: Каркас композиции. Файл, а не строка в коде: следующим шагом на его место
#: встанет готовый шаблон проекта с объявленными `data-composition-variables`.
TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "reel.html"

# ------------------------------------------------------------ движение стыков
#
# Самодельный наезд scale 1 -> 1.06 выброшен: это ровно их «bad slow push» —
# «A slow pan or push on elements in the later ~50% of a scene disrupts the
# viewer's sightline… I'd rather have NO motion than BAD motion»
# (product-launch-video/references/motion-language.md:111-118). Страница их
# сайта (prompting/motion.md, правило «The camera is an actor») советует
# обратное — постоянный push-in; идём за установленными скилами, их исполняет
# агент. Вместо дрейфа — их же скоростные стыки: cut-the-curve, «вырезка на
# пике скорости, направление и скорость совпадают по обе стороны»
# (product-launch-video/references/cut-catalog.md:116-156).

#: Путь и время направленного стыка. Числа их: 230 px за 0,3 с, выход
#: `power4.in`, вход `power4.out` — зеркальные половины одной кривой; гашение
#: выхода завершается на ~25–30 % пути (cut-catalog.md:133-149).
CUT_TRAVEL = 230
CUT_SECONDS = 0.3
CUT_FADE = 0.18

#: Биты сцены — их таблица «Narrative position»
#: (hyperframes-animation/transitions/overview.md:66-75): у ролика один
#: первичный переход, разный — только там, где меняется глава рассказа.
BEATS = ("hook", "point", "turn", "climax", "outro")

#: Блок вспышки на кульминации — их накладка из нашего каталога. Прозрачная
#: страница 1920x1080, пик вспышки на 58 % собственной длительности
#: (editorial-flash-overlay.html: `hit = duration * 0.58`).
FLASH_BLOCK = "editorial-flash-overlay"
FLASH_NATIVE = 4.0
FLASH_HIT = 0.58
TRACK_FX = 95
TRACK_SFX = 98

#: Растровые картинки. Слот может получить и mp4 (например через
#: `media-use --from`), и тогда тег другой.
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg")

#: Вставки, которые вписываются целиком, а не обрезаются: у логотипа и значка
#: обрезать нечего.
_CONTAIN_KINDS = {"logo", "icon"}


def _q(value: float) -> float:
    return quantize(float(value))


def _rect_style(rect: dict) -> str:
    return (f'left:{rect["left"]}px;top:{rect["top"]}px;'
            f'width:{rect["width"]}px;height:{rect["height"]}px')


def _js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


# ------------------------------------------------------------------ вставки

def insert_of(scene: dict) -> dict | None:
    """Вставка сцены — либо словарь с намерением, либо ничего."""
    found = scene.get("insert")
    return found if isinstance(found, dict) and found.get("look") else None


def media_key(scene_id: str) -> str:
    """Ключ подобранной вставки. Вставка у сцены одна, поэтому ключ — её id."""
    return str(scene_id)


#: Какой тип `media-use` просить под названный агентом вид вставки. Стокового
#: видео у них нет: `heygen asset search --type video` отвечает «--type must be
#: one of [image icon]», а `resolve --type video` уходит в генерацию аватара
#: (`media-use/scripts/lib/heygen-video-provider.mjs`) — это платно и не про
#: перебивку. Поэтому вставка сейчас всегда неподвижный файл.
#:
#: `icon` и `logo` агенту не предлагаются: их подбор отдаёт прозрачный PNG
#: (проверено на прогоне 14 — все три иконки пришли 200x200 rgba), а вставка
#: занимает весь кадр или его половину, и сквозь прозрачное там виден чёрный
#: фон сцены. Значок поверх картинки — это накладка, и её место в работе с их
#: реестром накладок, а не здесь.
MEDIA_TYPES = {"photo": "image", "icon": "icon", "logo": "logo"}


def collect_intents(storyboard: dict) -> list[dict]:
    """Все намерения под вставки: сцена называет их словами, ищет код.

    `rect` — прямоугольник, который файл закроет в кадре: по нему отсев меряет
    растяжение. `required` — сцена без ведущей: там вставка обязательна, и
    отсев вправе смягчиться, мыло лучше чёрного кадра.
    """
    requests = []
    for scene in storyboard.get("scenes") or []:
        insert = insert_of(scene)
        if not insert:
            continue
        kind = str(insert.get("kind") or "photo").lower()
        requests.append({"key": media_key(scene["id"]),
                         "type": MEDIA_TYPES.get(kind, "image"),
                         "intent": str(insert["look"]).strip(),
                         "rect": insert_rect(str(scene.get("presenter")
                                                 or "full")),
                         "required": scene.get("presenter") == "none"})
    return requests


def _insert_tag(scene: dict, rect: dict, source: str, *, start: float,
                duration: float, track: int) -> str:
    """Слой вставки: клип-обёртка с рамкой и медиа внутри неё.

    Обёртка несёт время и `class="clip"`, потому что клип обязан быть прямым
    потомком корня композиции («Visual clips (`class="clip"`) must be DIRECT
    children of the composition root … To wrap/transform a clip, put the wrapper
    _inside_ the clip», hyperframes-core/references/data-attributes.md:25).
    Наезд целится в медиа внутри, а не в саму обёртку: видимостью клипа
    распоряжается рантайм, и анимировать его же — драться с ним
    (`full-screen-motion.md:57`).
    """
    kind = str((insert_of(scene) or {}).get("kind") or "photo").lower()
    fit = "contain" if kind in _CONTAIN_KINDS else "cover"
    box = _rect_style(rect)
    name = f'ins-{scene["id"]}'
    if source.lower().split("?")[0].endswith(_IMAGE_SUFFIXES):
        return (f'    <div id="{name}" class="ins clip" style="{box}"'
                f' data-start="{start:.4f}" data-duration="{duration:.4f}"'
                f' data-track-index="{track}">'
                f'<img class="ins-media" src="{source}" alt=""'
                f' style="object-fit:{fit}"></div>')
    # У видео время живёт на самом теге: `<video>` внутри клипа их линтер
    # заворачивает ошибкой `video_nested_in_timed_element`
    # (packages/lint/src/rules/media.ts:383), а без `id` — ошибкой
    # `media_missing_id`, «this video will be FROZEN in renders» (там же:486).
    # Рамка остаётся, но времени не несёт.
    return (f'    <div id="{name}-box" class="ins" style="{box}">'
            f'<video id="{name}" class="ins-media clip" src="{source}"'
            f' muted playsinline'
            f' data-start="{start:.4f}" data-duration="{duration:.4f}"'
            f' data-track-index="{track}" style="object-fit:{fit}"></video>'
            f"</div>")


def _beat(scene: dict) -> str:
    """Бит сцены. Неназванный — обычная точка рассказа."""
    value = str(scene.get("beat") or "point")
    return value if value in BEATS else "point"


def _axis(beat: str) -> tuple[str, int]:
    """Ось стыка и знак направления движения.

    Обычные стыки едут влево — одно направление на весь ролик, глаз ведёт
    движение через границу (cut-the-curve: «Same path, same direction»).
    Смена главы (`turn`) — вертикальный вариант: зритель видит, что рассказ
    повернул.
    """
    return ("y", 1) if beat == "turn" else ("x", -1)


def _entry(target: str, beat: str, at: float) -> list[str]:
    """Вход вставки: продолжение движения через стык, а не появление из ничего.

    `fromTo`, не `from`: их правило — начальное состояние явно, иначе холодная
    перемотка рисует элемент до входа (transitions/overview.md:22).
    """
    if beat == "outro":
        return [f'tl.fromTo({_js(target)}, {{ autoAlpha: 0, '
                f'filter: "blur(20px)" }}, {{ autoAlpha: 1, '
                f'filter: "blur(0px)", duration: 0.6, ease: "sine.inOut" }}, '
                f'{at});']
    axis, sign = _axis(beat)
    return [f'tl.fromTo({_js(target)}, {{ {axis}: {-sign * CUT_TRAVEL}, '
            f'autoAlpha: 0.35 }}, {{ {axis}: 0, autoAlpha: 1, '
            f'duration: {CUT_SECONDS}, ease: "power4.out" }}, {at});']


def _exit(target: str, next_beat: str, at: float) -> list[str]:
    """Выход вставки под входящую: ось и направление задаёт следующая сцена.

    Гашение короче пути (CUT_FADE < CUT_SECONDS): элемент исчезает, ещё
    разгоняясь, — «the exit's opacity completes at ~25-30% of its travel»
    (cut-catalog.md:145-149). Выход `power4.in` зеркален входу `power4.out`.
    """
    if next_beat == "outro":
        return [f'tl.to({_js(target)}, {{ autoAlpha: 0, duration: 0.5, '
                f'ease: "sine.inOut" }}, {at});']
    axis, sign = _axis(next_beat)
    return [
        f'tl.to({_js(target)}, {{ {axis}: {sign * CUT_TRAVEL}, '
        f'duration: {CUT_SECONDS}, ease: "power4.in" }}, {at});',
        f'tl.to({_js(target)}, {{ autoAlpha: 0, duration: {CUT_FADE}, '
        f'ease: "none" }}, {at});']


_CDN_GSAP = re.compile(r'src="https://cdn\.jsdelivr\.net/npm/gsap[^"]*"')


def _stage_overlay(public, block: str, scene_id: str) -> str:
    """Копия накладки под сцену. Возвращает имя копии.

    Копия, а не общий файл: ключ таймлайна сабкомпозиции один на
    `data-composition-id`, два хоста с одним ключом затёрли бы друг друга.
    GSAP переводится на локальный: внешние ссылки в композиции запрещены её же
    контрактом, а файл уже лежит в `vendor/` (hf_assets.vendor_gsap).
    """
    source = Path(public) / "compositions" / f"{block}.html"
    if not source.exists():
        raise RuntimeError(
            f"накладка {block} не установлена: нет {source}. Ставит её код "
            "командой `hyperframes add` перед сборкой")
    unique = f"{block}--{scene_id}"
    html = source.read_text(encoding="utf-8")
    html = html.replace(f'data-composition-id="{block}"',
                        f'data-composition-id="{unique}"')
    html = html.replace(f'__timelines["{block}"]', f'__timelines["{unique}"]')
    html = _CDN_GSAP.sub('src="../vendor/gsap.min.js"', html)
    target = source.with_name(f"{unique}.html")
    target.write_text(html, encoding="utf-8")
    return unique


def needed_blocks(storyboard: dict) -> list[str]:
    """Какие блоки каталога сборка поставит их же `hyperframes add`."""
    for scene in storyboard.get("scenes") or []:
        if (_beat(scene) == "climax"
                and float(scene.get("startSec", 0)) >= FLASH_HIT * FLASH_NATIVE):
            return [FLASH_BLOCK]
    return []


# ------------------------------------------------------------------ ведущая

def _presenter_rect(name: str) -> dict:
    rect = VIDEO_RECTS.get(name)
    if rect is None:
        raise RuntimeError(
            f"положение ведущей {name!r} неизвестно; есть {sorted(VIDEO_RECTS)}")
    return rect


def presenter_timeline(scenes: list[dict], clips: list[dict],
                       duration: float) -> list[tuple]:
    """Где окно ведущей в каждый момент ролика.

    Положение называет агент — это его главный ритмический инструмент. Код
    держит одно: где ведущей физически нет (аватар туда не заказан), окно
    гасится независимо от плана. Плану тут верить нельзя — на прогоне 03.08
    названное положение честно применялось к пустому окну, и проба считала
    положения, которых зритель не видел.

    Смотрим на пропуски между островами, а не на «попала ли сцена целиком в
    один клип»: соседние острова идут встык, и сцена на их стыке ведущую не
    теряет.
    """
    gaps = avatar_gaps(clips, duration)
    moments: list[tuple[float, str]] = []
    for scene in scenes:
        start, end = _q(scene["startSec"]), _q(scene["endSec"])
        position = str(scene.get("presenter") or "full")
        if position != "none" and in_avatar_gap(start, end, gaps):
            position = "none"
        moments.append((start, position))

    collapsed: list[tuple[float, str]] = []
    for time, position in moments:
        if not collapsed or collapsed[-1][1] != position:
            collapsed.append((time, position))
    return collapsed


def _presenter_move(position: str, at: float) -> list[str]:
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


# -------------------------------------------------------------- раскадровка

def complete_storyboard(board: dict, *, clips: list[dict],
                        duration: float) -> dict:
    """Дописать шапку раскадровки: она целиком выводится из материала.

    `schemaVersion`, `composition`, `videoTrack` и `subtitles` решений не
    содержат — размер кадра, частота, длительность и путь к клипу известны до
    агента. Прогон 03.08 на Sonnet потерял на этом попытку: агент отдал
    `videoTrack` списком по клипу на запись, гейт схемы искал `bounds` и
    заворачивал сборку. Спрашивать у агента то, что мы знаем сами, — способ
    получить расхождение, а не план.
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
    return board


def _content_mark(public, file: str) -> str:
    """Отпечаток содержимого картинки. Имя файла для этого не годится: подбор
    кладёт один и тот же снимок под разными именами."""
    if public is None:
        return file
    path = Path(public) / file
    if not path.exists():
        return file
    return hashlib.md5(path.read_bytes()).hexdigest()


def _copy_for(public, file: str, scene_id: str) -> str:
    """Копия занятой картинки под своим именем.

    Тот же `src` дважды их линтер считает риском двойного обнаружения медиа
    (`duplicate_media_discovery_risk`), и под `--strict` это валит сборку. Копия
    стоит килобайты и снимает вопрос.
    """
    if public is None:
        return file
    source = Path(public) / file
    target = source.with_name(f"{source.stem}--{scene_id}{source.suffix}")
    if not target.exists():
        shutil.copyfile(source, target)
    return str(target.relative_to(Path(public))).replace("\\", "/")


def settle_inserts(board: dict, resolved: dict[str, dict],
                   clips: list[dict], duration: float,
                   public=None) -> list[str]:
    """Свести план с тем, что реально нашёл `media-use`.

    Вставка засчитывается, только если файл нашёлся и годится (см.
    `insert_problem`). Ронять прогон из-за одной картинки дорого, а оставить как
    есть нельзя: на её месте будет чёрный прямоугольник. Дальше по обстановке:
    где ведущая есть — сцена отдаётся ей во весь кадр, где её нет — картинка
    занимается у другой сцены. Повтор кадра плох, чёрный экран — провал.

    Возвращает список сцен, оставшихся без вставки, — для отчёта.
    """
    gaps = avatar_gaps(clips, duration)
    scenes = board.get("scenes") or []

    def usable(scene_id: str) -> str | None:
        found = resolved.get(media_key(scene_id)) or {}
        if not found.get("file"):
            return None
        if public is not None and insert_problem(Path(public) / found["file"]):
            return None
        return found["file"]

    # Одна картинка на одну сцену. `media-use` отвечает на близкие намерения
    # одним и тем же снимком — на прогоне 15 три сцены получили общий файл, а
    # ещё две получили один снимок под разными именами (`image_002.jpg` и
    # `image_014.jpg` совпали побайтно). Поэтому сверяем содержимое, а не путь.
    # Повтор кадра — и монтажный брак (в эталонных рилсах картинка не
    # повторяется), и находка их линтера: `duplicate_media_discovery_risk`
    # (packages/lint/src/rules/media.ts:239), а под `--strict` она валит сборку.
    good: dict[str, str | None] = {}
    taken: set[str] = set()
    for scene in scenes:
        if not insert_of(scene):
            continue
        file = usable(scene["id"])
        mark = _content_mark(public, file) if file else None
        if mark is not None and mark in taken:
            file = None
        elif mark is not None:
            taken.add(mark)
        good[scene["id"]] = file

    def neighbours(index: int, what: str) -> set:
        return {(scenes[i].get(what) if 0 <= i < len(scenes) else None)
                for i in (index - 1, index + 1)}

    def borrow(index: int, scene: dict) -> str | None:
        """Занять картинку у другой сцены — но не у соседней.

        Повтор кадра плох, но кадр, слившийся с соседним, ломает счёт смен
        картинки (D21), а чёрный экран — вообще провал. Копия под своим именем:
        тот же `src` дважды их линтер зовёт `duplicate_media_discovery_risk`.
        """
        near = {good.get(scenes[i].get("id")) if 0 <= i < len(scenes) else None
                for i in (index - 1, index + 1)}
        spare = next((file for file in good.values()
                      if file and file not in near), None)
        return _copy_for(public, spare, scene["id"]) if spare else None

    lost, borrowed = [], []
    for index, scene in enumerate(scenes):
        if not insert_of(scene) or good.get(scene["id"]):
            continue
        start, end = _q(scene["startSec"]), _q(scene["endSec"])
        # Соседи обязаны отличаться картинкой (D21), иначе две сцены подряд
        # читаются одним планом. Без вставки сцену закрывает только ведущая во
        # весь кадр, и таких раскладок ровно две.
        free = [name for name in ("full", "punch")
                if name not in neighbours(index, "presenter")]
        faceless = in_avatar_gap(start, end, gaps)
        if not faceless and free:
            lost.append(scene["id"])
            scene["insert"] = None
            scene["presenter"] = free[0]
            continue
        # Ведущей тут нет вовсе, либо обе полнокадровые раскладки уже заняты
        # соседями. Остаётся картинка.
        spare = borrow(index, scene)
        if spare is None:
            raise RuntimeError(
                f'{scene["id"]}: вставка «{insert_of(scene)["look"]}» не '
                f"подобралась ({start:g}–{end:g} с), и занять картинку не у "
                "кого — во всём плане не нашлось ни одной пригодной. Опиши "
                "вставки как настоящие фотографии сцен из жизни")
        resolved[media_key(scene["id"])] = {"file": spare}
        good[scene["id"]] = spare
        borrowed.append(scene["id"])
    if borrowed:
        print("вставку заняли у соседней сцены: " + ", ".join(borrowed))
    return lost


# ----------------------------------------------------------------- сборка

def build_composition(rdir, sdk, *, storyboard: dict, clips: list[dict],
                      duration: float, words: list[dict],
                      resolved: dict[str, dict] | None = None,
                      sfx_whoosh: str | None = None) -> Path:
    """Собрать `public/index.html`. Возвращает путь к нему."""
    rdir = Path(rdir)
    public = rdir / "public"
    scenes = sorted(storyboard.get("scenes") or [],
                    key=lambda scene: float(scene["startSec"]))
    duration = _q(duration)
    resolved = resolved or {}

    body: list[str] = []
    timeline: list[str] = []

    # ── вставки ───────────────────────────────────────────────────────────
    # Ниже ведущей по CSS и раньше её в разметке: порядок отрисовки задаёт
    # `z-index` из шаблона, а порядок в DOM повторяет его на случай, если
    # z-index кто-то перебьёт. Внутри слоя входящая вставка ложится поверх
    # уходящей тем же порядком DOM — стык читается как «push».
    files = {scene["id"]: (resolved.get(media_key(scene["id"])) or {}).get("file")
             for scene in scenes if insert_of(scene)}
    # Дорожки вставок — ротацией: соседние вставки обязаны лежать на разных
    # дорожках (они пересекаются на время стыка), а больше трёх на одной их
    # линтер зовёт `timeline_track_too_dense`. Ротация по ceil(n/3) дорожек
    # закрывает оба требования разом.
    insert_count = sum(1 for scene in scenes if files.get(scene["id"]))
    insert_tracks = max(2, -(-insert_count // INSERTS_PER_TRACK))
    staged = 0
    for position, scene in enumerate(scenes):
        file = files.get(scene["id"])
        if not file:
            continue
        rect = insert_rect(str(scene.get("presenter") or "full"))
        if rect is None:
            raise RuntimeError(
                f'{scene["id"]}: ведущая стоит {scene.get("presenter")!r} и '
                "закрывает кадр целиком — вставке места нет. Либо убери "
                "вставку, либо отправь ведущую в угол (`pip-*`), в половину "
                "кадра (`stack`, `split`) или убери её из сцены (`none`)")
        start = _q(scene["startSec"])
        end = _q(scene["endSec"])
        image = file.lower().split("?")[0].endswith(_IMAGE_SUFFIXES)
        follower = scenes[position + 1] if position + 1 < len(scenes) else None
        next_file = files.get(follower["id"]) if follower else None
        # Уходящая вставка живёт на CUT_SECONDS дольше своей сцены: их правило
        # — «outgoing scene content must be fully visible when the transition
        # starts» (transitions/overview.md:23), стык делает движение, а не
        # гашение. Пересечение легально: соседние вставки лежат на разных
        # дорожках (разноска ниже), пересечение запрещено только на одной.
        # Видео не продлеваем: за концом файла кадр замирает.
        overlap = CUT_SECONDS if (image and next_file) else 0.0
        body.append(_insert_tag(
            scene, rect, file, start=start, duration=end - start + overlap,
            track=TRACK_INSERT + staged % insert_tracks))
        target = (f'#ins-{scene["id"]} .ins-media' if image
                  else f'#ins-{scene["id"]}-box')
        timeline += _entry(target, _beat(scene), start)
        if overlap:
            timeline += _exit(target, _beat(follower), end)
        staged += 1

    # ── вспышка на кульминации ────────────────────────────────────────────
    # Их накладка целиком: прозрачная сабкомпозиция 1920x1080, вписанная в
    # вертикальный кадр обёрткой с transform — их загрузчик жёстко ставит
    # хосту пиксели канваса блока (compositionLoader.ts:517-524), поэтому
    # масштаб может нести только обёртка вокруг клипа.
    for scene in scenes:
        if _beat(scene) != "climax":
            continue
        hit = _q(scene["startSec"])
        flash_start = round(hit - FLASH_HIT * FLASH_NATIVE, 4)
        flash_length = min(FLASH_NATIVE, duration - flash_start)
        if flash_start < 0 or flash_length < FLASH_HIT * FLASH_NATIVE + 0.2:
            continue
        unique = _stage_overlay(public, FLASH_BLOCK, scene["id"])
        scale = OUT_H / 1080.0
        left = -round((1920 * scale - OUT_W) / 2)
        # Растянутый канвас блока шире кадра: обёртка режет его по краю, а
        # допуск переполнения снимает находку canvas_overflow их аудита.
        body.append(
            f'    <div class="fx"><div data-layout-allow-overflow="true"'
            f' style="position:absolute;'
            f'left:{left}px;top:0;transform:scale({scale:.4f});'
            f'transform-origin:0 0">'
            f'<div id="fx-{scene["id"]}" class="clip"'
            f' data-layout-allow-overflow="true"'
            f' data-composition-id="{unique}"'
            f' data-composition-src="compositions/{unique}.html"'
            f' data-start="{flash_start:.4f}"'
            f' data-duration="{flash_length:.4f}"'
            f' data-track-index="{TRACK_FX}"'
            f' data-width="1920" data-height="1080"></div></div></div>')
        if sfx_whoosh:
            body.append(
                f'    <audio id="sfx-{scene["id"]}" src="{sfx_whoosh}"'
                f' data-start="{max(0.0, hit - 0.15):.4f}"'
                f' data-duration="0.6" data-track-index="{TRACK_SFX}"'
                f' data-volume="0.5"></audio>')

    # ── ведущая ───────────────────────────────────────────────────────────
    # `class="clip"` на `<video>` их линтер не требует — теги `video`/`audio` он
    # из проверки исключает (packages/lint/src/rules/composition.ts:548), а одна
    # страница доков его прямо запрещает (docs/reference/html-schema.mdx:92).
    # Но их же справочник ставит его в примере (variables-and-media.md:74), а у
    # нас без него клип в кадре не появлялся вовсе: окно на месте, внутри пусто.
    # Оставляем — проверено кадрами.
    videos = "\n".join(
        f'      <video class="clip" id="clip-{index:02d}" src="{clip["file"]}"'
        f' muted playsinline'
        f' data-start="{_q(clip["start"]):.4f}"'
        f' data-duration="{_q(clip["duration"]):.4f}"'
        f' data-track-index="{TRACK_VIDEO}"></video>'
        for index, clip in enumerate(clips))
    moments = presenter_timeline(scenes, clips, duration)
    first = moments[0][1] if moments else "full"
    initial = next((name for _, name in moments if name != "none"), "full")
    style = _rect_style(_presenter_rect(initial))
    if first == "none":
        style += ";visibility:hidden;opacity:0"
        timeline.append('tl.set("#video-wrap", { autoAlpha: 0 }, 0);')
    body.append(f'    <div id="video-wrap" style="{style}">\n'
                f"{videos}\n    </div>")
    for time, position in moments[1:]:
        timeline += _presenter_move(position, _q(time))

    # ── субтитры ──────────────────────────────────────────────────────────
    # Титр идёт весь ролик и больше не гасится: гасить его было нужно, пока
    # сцена была непрозрачным блоком со своим текстом. Теперь текста в кадре
    # нет ни у вставки, ни у ведущей, а в эталонных рилсах «текста в кадре нет
    # ни секунды без».
    write_caption_data(public, words=words, duration=duration)
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
    for scene in scenes:
        scene["startSec"] = _q(scene["startSec"])
        scene["endSec"] = _q(scene["endSec"])
    storyboard["scenes"] = scenes
    (rdir / "storyboard.json").write_text(
        json.dumps(storyboard, ensure_ascii=False, indent=1), encoding="utf-8")
    return target


def clear_generated(public: Path) -> None:
    """Убрать копии блоков прошлой попытки: имя копии зависело от карточки."""
    compositions = public / "compositions"
    if not compositions.exists():
        return
    for path in compositions.glob("*--*.html"):
        path.unlink()
