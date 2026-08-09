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
from reels_factory.hf_frame import DEFAULTS as FRAME_DEFAULTS
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

#: Дорожки накладок агента и слоя иконок. Соседние накладки могут пересечься
#: по времени — ротация по двум дорожкам это разводит.
TRACK_OVERLAY = 40
TRACK_ICON = 15

#: Куда садится накладка с широким канвасом 1920x1080: вписывается по ширине
#: кадра (масштаб 0.5625) и висит над полосой титра. Вертикальные накладки
#: (1080x1920) встают во весь кадр как есть.
OVERLAY_WIDE_TOP = 640

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
    return found if isinstance(found, dict) and found.get("query") else None


def media_key(scene_id: str) -> str:
    """Ключ подобранной вставки. Вставка у сцены одна, поэтому ключ — её id."""
    return str(scene_id)


#: Какой тип подбора просить под названный агентом вид вставки. Основной вид —
#: видео-биролл (решение 08.08.2026): живое видео из Pexels, суд моделью,
#: заморозка их `resolve --from`. Фото — запасной путь через их каталог.
#:
#: `icon` и `logo` агенту не предлагаются: их подбор отдаёт прозрачный PNG
#: (проверено на прогоне 14 — все три иконки пришли 200x200 rgba), а вставка
#: занимает весь кадр или его половину, и сквозь прозрачное там виден чёрный
#: фон сцены. Значок поверх картинки — это накладка, и её место в работе с их
#: реестром накладок, а не здесь.
MEDIA_TYPES = {"video": "video", "photo": "image", "icon": "icon",
               "logo": "logo"}


def collect_intents(storyboard: dict) -> list[dict]:
    """Все намерения под вставки: сцена называет их словами, ищет код.

    `rect` — прямоугольник, который файл закроет в кадре: по нему отсев меряет
    растяжение. `required` — сцена без ведущей: там вставка обязательна, и
    отсев вправе смягчиться, мыло лучше чёрного кадра.
    """
    requests = []
    for scene in storyboard.get("scenes") or []:
        insert = insert_of(scene)
        if insert:
            kind = str(insert.get("kind") or "video").lower()
            requests.append({"key": media_key(scene["id"]),
                             "type": MEDIA_TYPES.get(kind, "video"),
                             "intent": str(insert["query"]).strip(),
                             "rect": insert_rect(str(scene.get("presenter")
                                                     or "full")),
                             "required": scene.get("presenter") == "none",
                             "seconds": round(float(scene.get("endSec", 0))
                                              - float(scene.get("startSec", 0)),
                                              3)})
        icon = scene.get("icon")
        if isinstance(icon, dict) and str(icon.get("query") or "").strip():
            requests.append({"key": f'{scene["id"]}::icon', "type": "icon",
                             "intent": str(icon["query"]).strip(),
                             "rect": None, "required": False, "seconds": 0})
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

_CANVAS = re.compile(
    r'data-composition-id="[^"]+"[^>]*data-width="(\d+)"[^>]*'
    r'data-height="(\d+)"', re.S)
_NATIVE = re.compile(
    r'data-composition-id="[^"]+"[^>]*data-duration="([\d.]+)"', re.S)


def _stage_overlay(public, block: str, scene_id: str, *, sdk=None,
                   text: dict | None = None) -> tuple[str, float, tuple]:
    """Копия накладки под сцену. Возвращает (имя, родная длительность, канвас).

    Копия, а не общий файл: ключ таймлайна сабкомпозиции один на
    `data-composition-id`, два хоста с одним ключом затёрли бы друг друга.
    Текст в слоты вписывает наш код их же SDK (`hf_slots.fill_ops`) — у них
    механизма нет, агент у них правит файл руками
    (hyperframes-registry/SKILL.md:78). GSAP переводится на локальный:
    внешние ссылки в композиции запрещены её же контрактом.
    """
    from reels_factory.hf_slots import fill_ops, prune_timeline

    source = Path(public) / "compositions" / f"{block}.html"
    if not source.exists():
        raise RuntimeError(
            f"накладка {block} не установлена: нет {source}. Ставит её код "
            "командой `hyperframes add` перед сборкой")
    unique = f"{block}--{scene_id}"
    target = source.with_name(f"{unique}.html")
    if text and sdk is not None:
        sdk.open(unique, source)
        sdk.dispatch(unique, fill_ops(sdk.elements(unique), text=text))
        sdk.save(unique, target)
        sdk.close(unique)
        html = target.read_text(encoding="utf-8")
    else:
        html = source.read_text(encoding="utf-8")
    html = html.replace(f'data-composition-id="{block}"',
                        f'data-composition-id="{unique}"')
    html = html.replace(f'__timelines["{block}"]', f'__timelines["{unique}"]')
    # Копия GSAP лежит РЯДОМ с блоками, а не через ../: путь выше корня их
    # линтер запрещает (invalid_parent_traversal_in_asset_path, прогон 23) —
    # рендер резолвит его от файла блока, живой просмотр — от корня проекта,
    # и сойтись они не могут.
    vendored = source.parent / "gsap-vendor.min.js"
    original = Path(public) / "vendor" / "gsap.min.js"
    if not vendored.exists() and original.exists():
        shutil.copyfile(original, vendored)
    html = _CDN_GSAP.sub('src="gsap-vendor.min.js"', html)
    if text:
        html = prune_timeline(html)
    target.write_text(html, encoding="utf-8")

    canvas_match = _CANVAS.search(html)
    canvas = ((int(canvas_match.group(1)), int(canvas_match.group(2)))
              if canvas_match else (1920, 1080))
    native_match = _NATIVE.search(html)
    native = float(native_match.group(1)) if native_match else 4.0
    return unique, native, canvas


def needed_blocks(storyboard: dict) -> list[str]:
    """Какие блоки каталога сборка поставит их же `hyperframes add`."""
    found: list[str] = []
    for scene in storyboard.get("scenes") or []:
        block = (scene.get("overlay") or {}).get("block") \
            if isinstance(scene.get("overlay"), dict) else None
        if block and block not in found:
            found.append(str(block))
        if (_beat(scene) == "climax"
                and float(scene.get("startSec", 0)) >= FLASH_HIT * FLASH_NATIVE
                and FLASH_BLOCK not in found):
            found.append(FLASH_BLOCK)
    return found


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
                f'{scene["id"]}: вставка «{insert_of(scene)["query"]}» не '
                f"подобралась ({start:g}–{end:g} с), и занять вставку не у "
                "кого — во всём плане не нашлось ни одной пригодной. Пиши "
                "query как действие с предметом по-английски")
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
                      sfx_whoosh: str | None = None,
                      theme: dict | None = None) -> Path:
    """Собрать `public/index.html`. Возвращает путь к нему."""
    rdir = Path(rdir)
    public = rdir / "public"
    scenes = sorted(storyboard.get("scenes") or [],
                    key=lambda scene: float(scene["startSec"]))
    duration = _q(duration)
    resolved = resolved or {}
    if theme is None:
        theme = {"colors": dict(FRAME_DEFAULTS["colors"])}
    colors = theme["colors"]

    body: list[str] = []
    # Дыхание фоновых глоу — их же требование к декоративам: «статичные
    # мертвы» (house-style.md:45). Повторы ограничены длиной ролика, а не
    # бесконечны: repeat: -1 сделал бы длительность таймлайна бесконечной.
    cycles = int(duration // 12) + 1
    timeline: list[str] = [
        f'tl.to("#bg-glow", {{ scale: 1.12, duration: 6, ease: "sine.inOut",'
        f' repeat: {cycles}, yoyo: true }}, 0);',
        f'tl.to("#bg-glow-low", {{ scale: 1.09, duration: 7.3,'
        f' ease: "sine.inOut", repeat: {cycles}, yoyo: true }}, 0);',
    ]

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

    # ── накладки агента: их блоки из каталога ────────────────────────────
    # Плашка живёт свою родную длительность от начала сцены — резать чужой
    # таймлайн сильно короче значит показать полусобранную сцену
    # (min_card_seconds, порог проверен кадрами прогона 13).
    staged_overlays = 0
    for scene in scenes:
        overlay = scene.get("overlay")
        if not isinstance(overlay, dict) or not overlay.get("block"):
            continue
        from reels_factory.hf_slots import min_card_seconds

        start = _q(scene["startSec"])
        unique, native, canvas = _stage_overlay(
            public, str(overlay["block"]), scene["id"], sdk=sdk,
            text={k: str(v) for k, v in (overlay.get("text") or {}).items()})
        length = round(min(native, duration - start), 4)
        if length < min_card_seconds(native):
            raise RuntimeError(
                f'{scene["id"]}: накладке {overlay["block"]} нужно '
                f"{min_card_seconds(native):g} с, а до конца ролика "
                f"{duration - start:.2f} — поставь её раньше или возьми короче")
        wide = canvas[0] > canvas[1]
        scale = OUT_W / canvas[0]
        box = (f"left:0;top:{OVERLAY_WIDE_TOP}px" if wide else "left:0;top:0")
        body.append(
            f'    <div class="ovl" style="{box}">'
            f'<div data-layout-allow-overflow="true" style="position:absolute;'
            f'left:0;top:0;transform:scale({scale:.4f});transform-origin:0 0">'
            f'<div id="ovl-{scene["id"]}" class="clip"'
            f' data-composition-id="{unique}"'
            f' data-composition-src="compositions/{unique}.html"'
            f' data-start="{start:.4f}" data-duration="{length:.4f}"'
            f' data-track-index="{TRACK_OVERLAY + staged_overlays % 2}"'
            f' data-width="{canvas[0]}" data-height="{canvas[1]}"></div>'
            f"</div></div>")
        staged_overlays += 1

    # ── иконки фоновых сцен ──────────────────────────────────────────────
    # Прозрачный значок из их подбора, живёт по их правилам движения: мягкий
    # вход power3 и медленный дрейф — статичные декоративы «мертвы».
    #
    # НЕ клип и без data-атрибутов — их же PiP-рецепт «wrapper без data»,
    # видимостью правит наш таймлайн. Иконка, поставленная timed-клипом,
    # роняла в их рендерере слой субтитров целиком: превью и снапшот живы,
    # рендер — без титров и скрима (прогон 21, найдено бинарным поиском;
    # без иконок тот же рендер рисует всё).
    for scene in scenes:
        found_icon = resolved.get(f'{scene["id"]}::icon') or {}
        if not found_icon.get("file"):
            continue
        start = _q(scene["startSec"])
        end = _q(scene["endSec"])
        body.append(
            f'    <div id="icon-{scene["id"]}" class="icon-spot">'
            f'<img src="{found_icon["file"]}" alt=""></div>')
        spot = _js(f'#icon-{scene["id"]}')
        target = _js(f'#icon-{scene["id"]} img')
        cycles = int((end - start) / 4.8) + 1
        timeline += [
            f'tl.set({spot}, {{ autoAlpha: 0 }}, 0);',
            f'tl.set({spot}, {{ autoAlpha: 1 }}, {start});',
            f'tl.fromTo({target}, {{ autoAlpha: 0, scale: 0.7, y: 24 }}, '
            f'{{ autoAlpha: 1, scale: 1, y: 0, duration: 0.5, '
            f'ease: "power3.out" }}, {start});',
            f'tl.to({target}, {{ y: -14, duration: 2.4, ease: "sine.inOut", '
            f'repeat: {cycles}, yoyo: true }}, {start + 0.5});',
            f'tl.set({spot}, {{ autoAlpha: 0 }}, {end});']

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
        unique, _, _ = _stage_overlay(public, FLASH_BLOCK, scene["id"])
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
    write_caption_data(public, words=words, duration=duration,
                       brand={"primaryColor": colors["ink"],
                              "accentColor": colors["accent"]})
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
                        ("__BG__", colors["bg"]),
                        ("__ACCENT__", colors["accent"]),
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
