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

**Порядок скриптов важнее, чем кажется.** GSAP подключается в `<head>`, до
всего остального. Их компонент субтитров строит свой таймлайн внутри
`document.fonts.ready.then(...)` и зовёт голый `gsap.timeline()`
(`caption-highlight.html:405`), а библиотеку подключает сам, тоже в `<head>`
(там же:13). Пока наш тег стоял ПОСЛЕ снятого с компонента сниппета, в рендере
шрифты успевали стать готовыми раньше, чем выполнялся gsap: колбэк падал
ReferenceError внутри промиса — молча, — и `window.__timelines`
["caption-highlight"] не появлялся. Их ожидание сабтаймлайнов висело весь
таймаут и не звало `__hfForceTimelineRebind`
(`packages/engine/src/services/frameCapture.ts:1523,1556`), а без него ни один
дочерний таймлайн не вложен в корневой: рендер шёл БЕЗ слоя субтитров, хотя
превью и `snapshot` его рисовали. Гонка: прогон 22 её выиграл, прогон 23
проиграл.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import re
import shutil
from pathlib import Path

from reels_factory.config import FPS, OUT_H, OUT_W
from reels_factory.hf_captions import caption_snippet, write_caption_data
from reels_factory.hf_frame import DEFAULTS as FRAME_DEFAULTS
from reels_factory.hf_layout import (
    VIDEO_RECTS, avatar_gaps, effect_rect, icon_fits, in_avatar_gap,
    insert_rect, quantize,
)
from reels_factory.hf_media import insert_problem
from reels_factory.hf_montage import (
    cut_into_plans, drop_schema, flash_moments, insert_of, refill_scene,
    scene_elements, shot_queries,
    shots_for, split_series, zoom_ladder,
)
from reels_factory.hf_schema import (
    FORMS, SAFE_BOTTOM as SCHEMA_SAFE_BOTTOM, build as schema_build,
    is_elastic as schema_is_elastic, min_seconds as schema_min_seconds,
    palette_css, port_block,
)

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

#: Дорожка накладок агента. Соседние накладки могут пересечься по времени —
#: ротация по двум дорожкам это разводит.
TRACK_OVERLAY = 40

#: Полоса дорожек под элементы каталога, названные агентом в `elements`.
#: Двадцать дорожек ротацией: элемент вида `overlay` стартует ЗА срез сцены и
#: потому нарочно пересекается по времени с элементом соседней сцены, а клипы
#: на одной дорожке пересекаться не могут (`overlapping_clips_same_track`).
#: Полоса 60..79 свободна: ниже сидят накладки (40, 41), выше — титр (90) и
#: вспышки (95). В счёт плотности элементы не идут — они маунты (см.
#: `TRACK_SCHEMA`).
TRACK_ELEMENT = 60
ELEMENT_TRACKS = 20

#: За сколько до среза сцены встаёт элемент вида `overlay`. Число их: «place
#: this block spanning the host's cut point (e.g. start 0.9s before the cut)»
#: (registry/blocks/mk-clone-wall-transition/mk-clone-wall-transition.html:
#: 117-121, то же у `hw-scribble-transition`:76-78). Накладка кроет кадр в
#: середине своего хода, и срез должен прийтись именно туда.
STITCH_LEAD = 0.9

#: Дорожка схем. Отдельная от накладок: схема занимает кадр целиком и с
#: плашкой в одной сцене не встречается, а на одной дорожке клипы пересекаться
#: не могут — их линтер зовёт это `overlapping_clips_same_track`.
#:
#: Ротации по дорожкам здесь нет и не нужно: их счётчик плотности
#: `timeline_track_too_dense` пропускает маунты первой же строкой цикла —
#: `if (isCompositionRootOrMount(tag.raw)) continue;`
#: (packages/lint/src/rules/composition.ts:394 на пине v0.7.84, признак —
#: `data-composition-id` или `data-composition-src`, там же:106-110). Схема
#: выезжает именно маунтом, то есть до счётчика не доходит. У вставок ротация
#: законна: их слой — обычный `div` с `data-start`, не маунт.
TRACK_SCHEMA = 30

#: Первая дорожка слоя читаемости под накладкой без своей подложки. Скрим —
#: обычный `div` с `data-start`, а не маунт, поэтому счётчик плотности
#: `timeline_track_too_dense` его считает, и четвёртый скрим на одной дорожке
#: дал бы предупреждение (composition.ts:17,409), а под `--strict` — падение.
#: Раскладываем по дорожкам ротацией, как вставки. Полоса 31..39: ниже сидит
#: схема (30), выше — накладки (40, 41). Девять дорожек по три — 27 скримов;
#: плашке нужно не меньше своего пола (~3,4 с), и в ролике их столько не
#: помещается.
TRACK_SCRIM = 31

#: Сколько скримов кладём на одну дорожку. Порог их линтера тот же, что у
#: вставок.
SCRIMS_PER_TRACK = INSERTS_PER_TRACK

#: Дрейф фоновых полей под схемой — числа их компонента `aurora-drift`
#: (registry/components/aurora-drift/aurora-drift.html, массив `paths`):
#: смещение фазы, амплитуда по X в `cqw`, амплитуда по Y в `cqh`. Оформление
#: вмержено сниппетом в `templates/reel.html` — почему именно так, написано там
#: же. Один полный оборот синуса за сцену: у них «the phase proxy advances
#: through exactly one whole sine cycle during HOLD», и поза на границах сцены
#: совпадает.
AURORA_PATHS = ((0.0, 4.6, 3.2), (2.0944, 4.1, 3.8), (4.1888, 3.6, 3.0))
AURORA_CYCLE = 6.2832

#: Значок: длительность входа и потолок свечения. Обе цифры их —
#: `POP_DUR 0.4–0.7s` (rules/spring-pop-entrance.md:90) и «peak opacity stays
#: restrained (≤ 0.45 hard ceiling)» (rules/ambient-glow-bloom.md:19).
ICON_BLOOM = 0.6
ICON_GLOW_PEAK = 0.42

#: Полоса титра — их же формула (product-launch-video/scripts/lib/
#: dimensions.mjs:36-45): у полосы есть верх, и «frame content must end
#: safetyPx above the band top». Их полоса — нижние 16,67% (титр у низа);
#: наш титр стоит по их rail-гайду для 9:16 на 620 от низа, и его полоса
#: выше: верх зоны слов ~1000 — замерен их же аудитом (слово титра на
#: y=1127 при двух строках, прогон 23). Широкая накладка (канвас 1920x1080)
#: вписывается по ширине кадра и ставится так, чтобы весь её бокс кончался
#: выше foregroundMaxY: на прежних 640 нижняя треть блока ложилась прямо
#: на слова титра (content_overlap #lt-name против span.hl-word-text).
#: Вертикальные накладки (1080x1920) встают во весь кадр как есть.
CAPTION_BAND_TOP = 1000
CAPTION_BAND_SAFETY = 20


def _overlay_wide_top(box_height: float) -> int:
    return max(0, CAPTION_BAND_TOP - CAPTION_BAND_SAFETY - round(box_height))


def effect_zone(presenter: str) -> dict | None:
    """Свободная зона кадра под элемент-эффект при этом положении ведущей.

    `None` — зоны нет, и элемент вида `effect` в такую сцену не встаёт.

    Одна дверь на троих: сборка ставит по ней коробку, ранняя сверка плана
    (`hf_gates._element_problems`) отвечает по ней же «зоны нет» — до заказа
    ведущей, а не молча на сборке, — и задание печатает по ней же список
    положений, при которых зоны не бывает (`hf_brief._no_effect_zone`).
    Полоса титра — наша, `hf_layout.effect_rect` о ней не знает, и подставить
    её в трёх местах порознь значит завести три разных правила.
    """
    return effect_rect(presenter,
                       band_top=CAPTION_BAND_TOP - CAPTION_BAND_SAFETY)


def _overlay_geometry(block: str, canvas: tuple) -> tuple[float, str]:
    """Масштаб и место плашки в кадре по её канвасу.

    Фактура кроет кадр целиком, плашка стоит полосой над титром. Обе приезжают
    канвасом 1920x1080, и различить их можно только по метке каталога — той
    же, которой помечены их собственные обработки кадра. Вертикальная позиция
    встаёт во весь кадр как есть.

    Одна арифметика на два места: по этому же правилу встаёт и позиция
    каталога, у которой вид в карточке не объявлен, — это сегодняшняя плашка,
    и вести себя она обязана так же.
    """
    if str(block) in _texture_blocks():
        scale = OUT_H / canvas[1]
        return scale, f"left:{-round((canvas[0] * scale - OUT_W) / 2)}px;top:0"
    if canvas[0] > canvas[1]:
        scale = OUT_W / canvas[0]
        return scale, f"left:0;top:{_overlay_wide_top(canvas[1] * scale)}px"
    return OUT_W / canvas[0], "left:0;top:0"


@functools.lru_cache(maxsize=1)
def _texture_blocks() -> frozenset:
    """Имена накладок-фактур из каталога. Каталога может не быть (тесты,
    чужая машина) — тогда фактур просто нет, и всё широкое встаёт плашкой."""
    from reels_factory.hf_catalog import texture_overlays
    try:
        return frozenset(texture_overlays())
    except (OSError, ValueError):
        return frozenset()


@functools.lru_cache(maxsize=1)
def _skipped_blocks() -> dict:
    """Блоки, которые ставить нельзя, и причина. План мог назвать такой блок
    раньше, чем он попал в этот список, — тогда снимаем его на сборке, а не
    роняем прогон: агент этого не исправит."""
    from reels_factory.hf_catalog import skipped_blocks
    try:
        return dict(skipped_blocks())
    except (OSError, ValueError):
        return {}


@functools.lru_cache(maxsize=1)
def _known_overlays() -> frozenset:
    """Имена накладок, которые каталог действительно отдаёт.

    Паспорта лежат в `OVERLAYS.md` рядом с заданием, и агент открывает файл
    сам. Не открыл — назовёт имя по памяти, а такого блока в реестре нет:
    `hyperframes add` его не поставит, и `_stage_overlay` уронит попытку
    целиком. Накладка того не стоит — снимаем её, как снимаем запрещённые.

    Каталог недоступен — возвращаем пустое множество, и проверка не
    применяется: обвинять план в том, что не поднялся наш же реестр, незачем.
    """
    from reels_factory.hf_catalog import overlay_names
    try:
        return frozenset(overlay_names())
    except (OSError, ValueError):
        return frozenset()


@functools.lru_cache(maxsize=1)
def _catalog_cards() -> dict:
    """Карточки позиций, которые агент вправе назвать в `elements`.

    Тот же словарь читает ранняя сверка плана (`hf_gates.elements_problems`):
    два разных чтения каталога означали бы, что до денег план судят по одному
    списку, а собирают по другому. Каталога может не быть (тесты, чужая
    машина) — тогда позиций нет, и элементы снимаются как неизвестные.
    """
    from reels_factory.hf_catalog import catalog_cards
    try:
        return dict(catalog_cards())
    except (OSError, ValueError):
        return {}


@functools.lru_cache(maxsize=1)
def _block_backing() -> dict:
    """Есть ли у накладки своя подложка под текстом. Каталога может не быть —
    тогда скрим не кладём: лишний тёмный слой хуже, чем его отсутствие."""
    from reels_factory.hf_catalog import block_backing
    try:
        return dict(block_backing())
    except (OSError, ValueError):
        return {}

#: Растровые картинки. Слот может получить и mp4 (например через
#: `media-use --from`), и тогда тег другой.
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg")

#: Вставки, которые вписываются целиком, а не обрезаются: у логотипа и значка
#: обрезать нечего.
_CONTAIN_KINDS = {"logo", "icon"}


def _q(value: float) -> float:
    return quantize(float(value))


def markup_time(seconds: float) -> float:
    """Время, каким оно уходит в разметку и в позиции твинов.

    `quantize` округляет до трёх знаков, и напечатанное время выходит БОЛЬШЕ
    настоящей границы кадра: 2/30 = 0,0666667 печатается как «0.067». Рантайм
    показывает элемент при `currentTime >= start` без допуска, а сикает ровно
    в `frameIndex/fps` — и треть времён встаёт на кадр позже задуманного.
    Поэтому берём НАИБОЛЬШЕЕ четырёхзначное число, не превышающее границу
    своего кадра: floor, а не round, потому что `:.4f` от 0,0666667 даёт
    «0.0667» — всё ещё за границей кадра, то есть тот же опоздавший кадр.

    Числа на диске (`clips.json`, раскадровка, планы, гейты) остаются
    трёхзначными и читаемыми: опаздывала только разметка.

    Длительность печатать ПАРНО — `markup_time(start + duration) -
    markup_time(start)`, а не `markup_time(duration)`: наивная форма даёт
    расхождение 1e-4 при допуске их линта 1e-6 и возвращает наезд клипов.

    Мимо этой функции идут ровно два числа, и оба намеренно: корневая
    длительность ролика (она задаёт число кадров и обрезку звука) и старт
    вспышки (на кадр стыка привязан её пик, а не старт). Причины — у самих
    мест. Гейты тоже судят по сырым числам: функция монотонна, и наезд, не
    видный на сырых, не появится и на напечатанных.
    """
    frame = round(float(seconds) * FPS)
    return math.floor(frame / FPS * 10000) / 10000


def _rect_style(rect: dict) -> str:
    return (f'left:{rect["left"]}px;top:{rect["top"]}px;'
            f'width:{rect["width"]}px;height:{rect["height"]}px')


def _js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


# ------------------------------------------------------------------ вставки

def media_key(scene_id: str, shot: int) -> str:
    """Ключ подобранного плана серии: у сцены их два."""
    return f"{scene_id}::shot{shot}"


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

    Серия — два плана, и запрос у каждого свой: намерений на сцену тоже два.
    `rect` — прямоугольник, который файл закроет в кадре: по нему отсев меряет
    растяжение. `required` — сцена без ведущей: там вставка обязательна, и
    отсев вправе смягчиться, мыло лучше чёрного кадра.
    """
    requests = []
    for scene in storyboard.get("scenes") or []:
        insert = insert_of(scene)
        if insert:
            kind = str(insert.get("kind") or "video").lower()
            span = round(float(scene.get("endSec", 0))
                         - float(scene.get("startSec", 0)), 3)
            need = shots_for(scene)
            for shot, query in enumerate(shot_queries(scene)[:need]):
                requests.append({"key": media_key(scene["id"], shot),
                                 "type": MEDIA_TYPES.get(kind, "video"),
                                 "intent": query,
                                 "rect": insert_rect(str(scene.get("presenter")
                                                         or "full")),
                                 "required": scene.get("presenter") == "none",
                                 "seconds": round(span / need, 3)})
    return requests


def icon_intents(scenes: list[dict]) -> list[dict]:
    """Значки — вторым заходом, после `settle_inserts`, и только тем сценам,
    где значок в кадр действительно встанет.

    Значок объявлен запасом: приехала вставка — значка нет. Пока запросы
    собирались вместе со вставками, за него платили независимо от этого — на
    каждую сцену со вставкой шёл поиск по каталогу, скачивание до
    `JUDGE_CANDIDATES` превью и доля платной сессии судьи, — и всё под выброс,
    потому что задание требует запаса у КАЖДОЙ сцены со вставкой. Хуже платы:
    выброшенный значок успевал занять `id` каталога в `taken`
    (`hf_media._resolve_icons`) и отбирал его у сцены, которой закрыть кадр
    больше нечем.

    Тем же вторым заходом идёт запасная схема (`schema_intents`): к этому
    моменту известно, что сток ответил, а что нет.
    """
    requests = []
    for scene in scenes:
        icon = scene.get("icon")
        if not (isinstance(icon, dict) and str(icon.get("query") or "").strip()):
            continue
        # Вставка и раскладка ведущей здесь уже настоящие: `settle_inserts`
        # обнуляет `insert` у сцен, чья серия не собралась, и переводит их на
        # полнокадровую ведущую. Оба условия сборка перепроверит ещё раз перед
        # постановкой — здесь они решают только, за что платить.
        if insert_of(scene):
            continue
        if not icon_fits(str(scene.get("presenter") or "none")):
            continue
        requests.append({"key": f'{scene["id"]}::icon', "type": "icon",
                         "intent": str(icon["query"]).strip(),
                         "rect": None, "required": False, "seconds": 0})
    return requests


def schema_plan(scene: dict) -> dict | None:
    """Схема этой сцены: названная агентом либо запасная.

    Агент выбирает схему по смыслу реплики (`schema`), и это его решение.
    Запасная (`fallback`) включается только тогда, когда сток не дал биролла и
    закрыть кадр больше нечем: она не подменяет выбор, а спасает сцену.
    """
    plan = scene.get("schema")
    if isinstance(plan, dict) and plan.get("form") in FORMS:
        return plan
    if scene.get("needsSchema"):
        plan = scene.get("fallback")
        if isinstance(plan, dict) and plan.get("form") in FORMS:
            return plan
    return None


def schema_key(scene_id: str, index: int) -> str:
    return f"{scene_id}::brand{index}"


def schema_intents(scenes: list[dict], *,
                   theme: dict | None = None) -> list[dict]:
    """Знаки брендов для схем формы `brand` — единственное, что схеме нужно
    искать: цифру, список и связь агент называет словами.

    Начертание знака выбирается по палитре ролика: на тёмной нужен светлый
    знак, на светлой тёмный — иначе он тонет в фоне, который выбрал агент.
    """
    from reels_factory.hf_frame import dark_frame

    dark = dark_frame(theme)
    requests = []
    for scene in scenes:
        plan = schema_plan(scene)
        if not plan or plan.get("form") != "brand":
            continue
        for index, brand in enumerate(plan.get("brands") or []):
            entity = str(brand or "").strip()
            if not entity:
                continue
            requests.append({"key": schema_key(scene["id"], index),
                             "type": "logo", "intent": f"{entity} logo",
                             "entity": entity, "dark_frame": dark,
                             "rect": None, "required": False, "seconds": 0})
    return requests


def _insert_tag(scene: dict, rect: dict, source: str, *, start: float,
                duration: float, track: int, name: str) -> str:
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
    # Время в разметку — только через `markup_time`, длительность парно.
    start, duration = (markup_time(start),
                       markup_time(start + duration) - markup_time(start))
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
    # Позиция твина — время на шкале, значит через `markup_time`. Длительности
    # твинов оставлены как есть: GSAP интерполирует непрерывно.
    at = markup_time(at)
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
    at = markup_time(at)
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

#: Их же маркер «этот файл поставлен реестром» (`isRegistryInstalledFile`,
#: `packages/lint/src/rules/composition.ts:94-95`) — простая проверка первых
#: 512 байт на комментарий этой формы, `re.match` здесь эквивалентен их `^`.
_REGISTRY_MARKER = re.compile(r"\s*<!--\s*hyperframes-registry-item:", re.I)

#: Внешние шрифты блока. Их линтер зовёт это `google_fonts_import`, под
#: `--strict` предупреждение роняет сборку, и он прав: композиция обязана быть
#: самодостаточной. Кириллицу всё равно врезаем мы — `hf_fonts.inject_fonts`.
_CDN_FONTS = re.compile(
    r'<link[^>]+fonts\.(?:googleapis|gstatic)\.com[^>]*>'
    r'|@import\s+url\([^)]*fonts\.googleapis\.com[^)]*\);?')

#: Гарнитура блока. Своих шрифтов их блоки не возят: имя ссылается на внешний
#: источник, а он композиции запрещён. Убрав ссылку, надо и имя заменить —
#: иначе их же линтер даёт `font_family_without_font_face`, а кириллица уходит
#: в подменный шрифт. Наши Manrope и Unbounded врезает `hf_fonts`.
_FONT_FAMILY = re.compile(r"font-family:\s*[^;}]+")
_OUR_STACK = "font-family: 'Manrope', sans-serif"

#: Простой относительный src/href/xlink:href (SVG `<use>` ссылается им же) —
#: без ведущего "/" (корень проекта), без "data:" (инлайн) и без "../" (тот
#: их линтер/рантайм переписывает сам, `rewriteAssetPath`,
#: `packages/parsers/src/rewriteSubCompPaths.ts` в исходнике клона — на нашем
#: пине 0.7.84 у неё нет третьего параметра `assetExists`, и такой путь
#: остаётся как есть, то есть резолвится от корня проекта буквально после
#: монтажа `data-composition-src`). Исключение "../" здесь в регэксп не
#: попадает — держит его явная проверка в `_prefixed`, а не то, что "../x"
#: почти никогда не существует рядом с файлом позиции.
_REL_SRC = re.compile(
    r"""((?:src|href|xlink:href)=)(["'])(?!https?:|/|data:)([^"']+)\2""")
_REL_URL = re.compile(r"""url\(\s*(["']?)(?!https?:|/|data:)([^)"']+)\1\s*\)""")


def _rewrite_sibling_assets(html: str, *, install_dir: Path, project_root: Path
                            ) -> str:
    """Простой относительный src/href/url(...) — префиксом до настоящей папки.

    Их `add` кладёт ассет позиции рядом с ЕЁ ЖЕ файлом (`remapTarget`,
    `add.ts`: префикс `paths.blocks`/`paths.components` получает только
    таргет, начинающийся с `compositions/` — голое `assets/…` остаётся как
    есть и приземляется МИМО `public/`, проверено живым `add`). А ссылка
    внутри файла позиции — простой относительный путь вида `src="assets/
    x.svg"`, который на нашем пине браузер после монтажа ищет от корня
    проекта. Совместить одно с другим может только код: префикс — папка, где
    ассет реально лежит (`compositions/` для блока, `compositions/
    components/` для компонента), а не то, что написано в файле позиции.

    Правим только ссылки, для которых рядом с файлом позиции на диске
    реально есть файл — редкая намеренно-корневая ссылка (если такая
    когда-нибудь встретится) молча не пострадает.
    """
    rel_dir = install_dir.relative_to(project_root).as_posix()

    def _prefixed(value: str) -> str | None:
        clean = value.split("?", 1)[0].split("#", 1)[0]
        if not clean or "../" in clean:
            return None
        if not (install_dir / clean).exists():
            return None
        return f"{rel_dir}/{value}"

    def sub_src(match: re.Match) -> str:
        prefixed = _prefixed(match.group(3))
        if prefixed is None:
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}{prefixed}{match.group(2)}"

    def sub_url(match: re.Match) -> str:
        prefixed = _prefixed(match.group(2))
        if prefixed is None:
            return match.group(0)
        return f"url({match.group(1)}{prefixed}{match.group(1)})"

    html = _REL_SRC.sub(sub_src, html)
    return _REL_URL.sub(sub_url, html)


_CANVAS = re.compile(
    r'data-composition-id="[^"]+"[^>]*data-width="(\d+)"[^>]*'
    r'data-height="(\d+)"', re.S)
_NATIVE = re.compile(
    r'data-composition-id="[^"]+"[^>]*data-duration="([\d.]+)"', re.S)


def _installed_path(public, name: str, card_type: str = "block") -> Path:
    """Куда `hyperframes add` кладёт файл позиции.

    Блок ложится в плоскую `compositions/`, компонент — в свою подпапку
    `compositions/components/` (`hyperframes.json#paths`, задаёт их
    `write_project_config`, `hf_catalog.py:51`). Одно место на обоих читателей
    источника — `_stage_overlay` и подстановку `root` для палитры: разойдись
    они, компонент читался бы по чужому пути и валил сборку рантайм-ошибкой
    «не установлен», хотя `add` его честно поставил, просто в другую
    подпапку.

    Формула плоского пути верна почти всегда, но не для карточки, чей
    собственный `registry-item.json` объявляет вложенный `target` (у
    `texture-mask-text` html лежит рядом с 66 текстурами в одноимённой
    подпапке — `hf_catalog.component_install_target`, сверено байт-в-байт с
    их клоном). `add` кладёт файл ровно туда, куда велит этот `target`
    (`remapTarget`, `add.ts:40-59`, меняет только префикс), поэтому путь
    сперва спрашивается у манифеста и только при его отсутствии считается по
    формуле.
    """
    base = Path(public) / "compositions"
    if card_type == "component":
        from reels_factory.hf_catalog import component_install_target
        target = component_install_target(name)
        if target:
            return Path(public) / target
        return base / "components" / f"{name}.html"
    return base / f"{name}.html"


def _stage_overlay(public, block: str, scene_id: str, *, sdk=None,
                   text: dict | None = None,
                   words: list[str] | None = None,
                   port: dict | None = None,
                   card_type: str = "block") -> tuple[str, float, tuple]:
    """Копия накладки под сцену. Возвращает (имя, родная длительность, канвас).

    Копия, а не общий файл: ключ таймлайна сабкомпозиции один на
    `data-composition-id`, два хоста с одним ключом затёрли бы друг друга.
    Текст в слоты вписывает наш код их же SDK (`hf_slots.fill_ops`) — у них
    механизма нет, агент у них правит файл руками
    (hyperframes-registry/SKILL.md:78). GSAP переводится на локальный:
    внешние ссылки в композиции запрещены её же контрактом.

    `words` — строки плана по порядку; какие в позиции слоты и в каком они
    порядке, спрашивается у самой разметки (`hf_slots.text_slot_names`), а не у
    карточки каталога. Карточка отвечает индексу — что агенту предложить и
    сколько слов принять, — и разойтись с разметкой она может (у `v-code-diff`
    в ней лежали видимые демо-строки вместо имён слотов, и элемент терялся на
    каждой сборке — отчёт B4). Разбор здесь единственный на весь путь, и он же
    ставит слова, поэтому расходиться нечему. `text` — прежний путь по именам
    слотов, им ходят плашка и схема.

    Декоративный текст блока (`reels.decor_texts` карточки — таймстемп «now»
    или SVG-глиф «HF» у `v-macos-notification`) читаем тем же `hf_catalog.
    decor_texts`, что и гейт заглушек D22, и отдаём в `fill_ops`: без этого
    подстановщик слотов не отличает нарисованную надпись от незаполненной
    заглушки и удаляет её из кадра (отчёт руки B2.5, прогон через настоящий
    SDK-мост).

    Исходник ищем по `card_type` (`_installed_path`) — он может лежать в
    подпапке `components/`, — а копию всегда кладём в плоскую `compositions/`:
    их загрузчик читает её буквально по
    `data-composition-src="compositions/{unique}.html"`
    (`compositionLoader.ts`), и рядом с исходником-компонентом эта ссылка не
    разрешилась бы.
    """
    from reels_factory.hf_catalog import decor_texts
    from reels_factory.hf_slots import fill_ops, prune_timeline

    source = _installed_path(public, block, card_type)
    if not source.exists():
        raise RuntimeError(
            f"накладка {block} не установлена: нет {source}. Ставит её код "
            "командой `hyperframes add` перед сборкой")
    # Исходник на диске правим сразу и один раз: их `check` судит ЛЮБОЙ html
    # под `compositions/`, включая неиспользуемый исходник (не только копию),
    # и без этой правки находка `missing_local_asset` оставалась даже после
    # того, как копия уже несла верный путь. Идемпотентно — второй заход по
    # уже поправленному тексту ничего не меняет (`install_dir / "compositions/
    # assets/…"` не существует, раз ассет реально лежит в `assets/`).
    stencil_html = source.read_text(encoding="utf-8")
    fixed_stencil = _rewrite_sibling_assets(
        stencil_html, install_dir=source.parent, project_root=Path(public))
    if fixed_stencil != stencil_html:
        source.write_text(fixed_stencil, encoding="utf-8")
    unique = f"{block}--{scene_id}"
    target = Path(public) / "compositions" / f"{unique}.html"
    if (text or words) and sdk is not None:
        from reels_factory.hf_slots import text_slot_names

        decor = decor_texts().get(block)
        sdk.open(unique, source)
        nodes = sdk.elements(unique)
        if words:
            text = dict(zip(text_slot_names(nodes, decor),
                            [str(word) for word in words]))
        sdk.dispatch(unique, fill_ops(nodes, text=text, decor=decor))
        sdk.save(unique, target)
        sdk.close(unique)
        html = target.read_text(encoding="utf-8")
    else:
        html = source.read_text(encoding="utf-8")
    html = html.replace(f'data-composition-id="{block}"',
                        f'data-composition-id="{unique}"')
    html = html.replace(f'__timelines["{block}"]', f'__timelines["{unique}"]')
    # Ключ таймлайна не всегда стоит в самой скобке: их компоненты кладут его в
    # переменную (`var compositionId = "grid-card-assemble"`), и без этой
    # замены обе копии регистрировались под одним именем — вторая затирала
    # первую, первая не рисовалась вовсе, а рендер ждал по 45 с на каждого
    # рабочего и отдавал `sub_timeline_readiness_timeout`. Проверено кадром:
    # убери второй хост — первый оживает.
    html = html.replace(f'= "{block}"', f'= "{unique}"')
    if card_type == "component" and not _REGISTRY_MARKER.match(html):
        # Их линтер снимает `composition_file_too_large` (и три похожих
        # правила) на файле, что несёт первой строкой комментарий
        # `<!-- hyperframes-registry-item: NAME -->` — `isRegistryInstalledFile`
        # (`packages/lint/src/rules/composition.ts:94`), проверка чисто
        # текстовая, тип карточки не смотрит. Их же `hyperframes add` пишет
        # этот комментарий блокам (`addRegistryItemMarker`, `installer.ts:
        # 136-141`), но только когда `isInstalledRegistryBlockComposition`
        # (`installer.ts:124-127`) видит `item.type === "hyperframes:block"` —
        # компоненту, даже настоящий `add`, маркер не ставит никогда
        # (проверено живым `hyperframes add` на `chart-story`: первая строка
        # файла — `<!doctype html>`, без маркера). Мы монтируем компонент с
        # `reels.mount: composition` в точности как блок (та же сабкомпозиция
        # через `data-composition-src`, тот же путь `_stage_overlay`) — и,
        # как блок, никогда не даём человеку её отредактировать: копия ниже
        # не трогает CSS/JS позиции, только `data-composition-id`/
        # `data-duration`/переменные хоста. Дописываем маркер сами, тем же
        # текстом, каким наградил бы блок настоящий `add`.
        html = f"<!-- hyperframes-registry-item: {block} -->\n{html}"
    # GSAP блока — плоским именем и ДВУМЯ копиями: их резолверы расходятся
    # (рендер идёт от файла копии, живая проверка — от корня проекта,
    # invalid_parent_traversal_in_asset_path это прямо говорит), а путь через
    # ../ запрещён их линтером. Копия рядом с копией кормит рендер, копия в
    # корне — живой runtime-чек (без неё он давал 404 и блок оставался без
    # анимации — прогон 23). Рядом с копией, не с исходником: у компонента
    # исходник лежит в `components/`, а грузится и рендерится всегда
    # `target` — плоская `compositions/{unique}.html`.
    original = Path(public) / "vendor" / "gsap.min.js"
    for target_dir in (target.parent, Path(public)):
        vendored = target_dir / "gsap-vendor.min.js"
        if not vendored.exists() and original.exists():
            shutil.copyfile(original, vendored)
    html = _CDN_GSAP.sub('src="gsap-vendor.min.js"', html)
    html = _CDN_FONTS.sub("", html)
    html = _FONT_FAMILY.sub(_OUR_STACK, html)
    html = _rewrite_sibling_assets(html, install_dir=source.parent,
                                   project_root=Path(public))
    if text:
        # Оригинал — разметка блока до подстановки: мёртвой считается только
        # цель, которая в ней была и пропала (см. `prune_timeline`).
        html = prune_timeline(html, fixed_stencil)
    # Блок схемы приезжает нарисованным под ландшафт и с их содержимым: канвас,
    # длительность, содержимое и палитру подставляем здесь же, до записи копии.
    if port:
        html = port_block(html, duration=port["duration"],
                          elastic=port.get("elastic", False),
                          height=port.get("height"),
                          config=port["config"], css=port.get("css", ""),
                          patches=tuple(port.get("patches") or ()))
    target.write_text(html, encoding="utf-8")

    canvas_match = _CANVAS.search(html)
    canvas = ((int(canvas_match.group(1)), int(canvas_match.group(2)))
              if canvas_match else (1920, 1080))
    native_match = _NATIVE.search(html)
    native = float(native_match.group(1)) if native_match else 4.0
    return unique, native, canvas


#: Корневой div paste-контрактного примитива: `class="имя-класса ...другие"`
#: без своего `data-composition-id` и `<template>` — их полка велит вставлять
#: разметку литералом («Paste the markup, CSS and script into a
#: composition», `registry/components/badge-pop/badge-pop.html:2`). Имя
#: класса — первый токен: оно же имя, которым скрипт компонента ищет себя
#: (`document.querySelectorAll(".hf-transition-badge-pop")`).
_PASTE_ROOT_CLASS = re.compile(r'<div\b[^>]*\bclass="([^"\s]+)')
_PASTE_STYLE = re.compile(r"<style[^>]*>.*?</style>", re.S)
#: Модульные скрипты (`type="module"`) не читаем: с ними неизвестный
#: компонент уже стоит в `reels.skip` по своей причине (`page_error:
#: Cannot use import statement outside a module`) — паста этого не чинит,
#: вставка исполняемого текста в поток документа не превращает его в модуль.
#: Внешний `<script src="…">` (шрифт-CDN, GSAP-CDN) тоже пропускаем: внутри
#: него извлекать нечего, а без исключения первый совпавший тег — он, а не
#: настоящий скрипт позиции. Так устроен и `caption-highlight.html`: внешний
#: GSAP подключён в `<head>` ДО корня, свой код — обычным `<script>` после.
_PASTE_SCRIPT = re.compile(
    r'<script(?![^>]*\btype="module")(?![^>]*\bsrc=)[^>]*>.*?</script>', re.S)


def paste_fragment(sdk, public, source, *, selector: str | None = None
                   ) -> tuple[str, str, str]:
    """Кусок чужого файла: стиль, корень и скрипт как есть, ещё не пристроенные.

    Общее место для caption-highlight (`hf_captions.caption_snippet`) и
    paste-контрактных позиций каталога (`reels.mount == "paste"`, работа
    B1.5) — оба вставляют готовый компонент литералом в композицию, а не
    саб-композицией через `data-composition-src`: их полка сама говорит
    «paste the markup, CSS and script», а `data-composition-src` копирует в
    живой DOM только содержимое `<template>` и выбросил бы стиль вовсе
    (`hf_captions.py`, шапка модуля). Корень режем их же SDK, а не
    регэкспом: вложенные `<div>` регэксп с балансировкой тегов не берёт,
    `sdk.extract` — их настоящий парсер.

    `selector` — готовый CSS-селектор корня для тех, кто не по конвенции
    paste-позиций реестра (класс первым токеном): у `caption-highlight`
    корень несёт `id="highlight"`, а не класс, и найти его можно только
    явным `#highlight`. Не назван — ищем класс сами (`_PASTE_ROOT_CLASS`).
    """
    source = Path(source)
    html = source.read_text(encoding="utf-8")
    # Тот же одноразовый идемпотентный ремонт исходника, каким `_stage_overlay`
    # чинит стенсиль composition-контракта: их `check` судит любой html под
    # `compositions/`, включая сам исходник, не только вставленный кусок.
    fixed = _rewrite_sibling_assets(
        html, install_dir=source.parent, project_root=Path(public))
    if fixed != html:
        source.write_text(fixed, encoding="utf-8")
        html = fixed
    if selector is None:
        match = _PASTE_ROOT_CLASS.search(html)
        if not match:
            raise RuntimeError(
                f"в {source} нет корневого div с class — разметка "
                "paste-компонента не по контракту полки (docstring "
                "`registry/components/*/*.html`)")
        selector = f".{match.group(1)}"
    found = sdk.extract(source, selector)
    if not found:
        raise RuntimeError(f"в {source} не нашёлся корень {selector}")
    root = found[0]["outer"]
    style_match = _PASTE_STYLE.search(html)
    script_match = _PASTE_SCRIPT.search(html)
    return (style_match.group(0) if style_match else "",
           root,
           script_match.group(0) if script_match else "")


def paste_effect(sdk, public, name: str, *, unique: str,
                 variables: dict) -> str:
    """Позиция каталога вида `paste` литералом: стиль + корень + скрипт.

    `reels.mount == "paste"` (карточка B1) — полка размечает такую позицию
    без `data-composition-id` и `<template>`: `_stage_overlay` смонтировать
    её не может (проверено живым `check --strict` на `badge-pop`: копия
    оставалась без корня, находки `missing_or_empty_sub_composition` +
    `root_missing_composition_id` + `root_missing_dimensions`).

    Переменные — тенью перед скриптом компонента: их полка велит читать
    `window.__hyperframes.getVariables()` синхронно на старте («the script
    reads each one, falls back to the declared default», их же карточки), а
    скрипты страницы исполняются в порядке разметки — тень, поставленная
    прямо перед своим скриптом, успевает подставиться до его же чтения. Их
    скоуп для этого вызова (`compositionScoping.ts`, таблица
    `__hfVariablesByComp`) размечен только для настоящих саб-композиций —
    паста в него не попадает, и подмена глобала здесь не обходит их
    контракт, а единственный канал, которым контракт вообще снабжён данными
    вне саб-композиции.

    Класс корня — общий для всех копий одной и той же позиции в кадре: без
    переименования вторая копия читала бы значения первой (обе слушают один
    `querySelectorAll` по общему классу). Переименование — тем же приёмом,
    каким `_stage_overlay` переименовывает `data-composition-id`.

    Анимация из комментария «Timeline integration» в их файле не
    подключается: это рецепт для хоста, не исполняемый код (их полка ждёт,
    что автор допишет вызовы в свой таймлайн руками,
    `hyperframes-registry/SKILL.md:78`). Позиция встаёт статичным финальным
    кадром на весь свой интервал, без входа и выхода — сознательно оставленная
    граница объёма, не забытая деталь.
    """
    source = _installed_path(public, name, "component")
    style, root, script = paste_fragment(sdk, public, source)
    class_match = _PASTE_ROOT_CLASS.search(root)
    if not class_match:
        raise RuntimeError(f"корень {name} потерял class при извлечении")
    klass = class_match.group(1)
    scoped = f"{klass}--{unique}"
    boundary = re.compile(r"(?<![\w-])" + re.escape(klass) + r"(?![\w-])")
    root = boundary.sub(scoped, root)
    style = boundary.sub(scoped, style)
    script = boundary.sub(scoped, script)

    style = _CDN_FONTS.sub("", style)
    style = _FONT_FAMILY.sub(_OUR_STACK, style)
    script = _CDN_GSAP.sub('src="gsap-vendor.min.js"', script)
    rewrite_kw = {"install_dir": source.parent, "project_root": Path(public)}
    style = _rewrite_sibling_assets(style, **rewrite_kw)
    root = _rewrite_sibling_assets(root, **rewrite_kw)
    script = _rewrite_sibling_assets(script, **rewrite_kw)

    shim = (" <script>window.__hyperframes = window.__hyperframes || {};"
           " window.__hyperframes.getVariables = function () { return "
           + json.dumps(variables or {}, ensure_ascii=False) +
           "; };</script>")
    return f"{style}\n{root}\n{shim}\n{script}"


#: Корневой элемент позиции: тот, что несёт `data-composition-id`. Его id
#: нужен правилу палитры и шрифта — целиться в `:root` их контракт тем прямо
#: запрещает (`themes/CONTRACT.md:3`). Атрибуты идут в обоих порядках:
#: `<div id="root" data-composition-id="…">` у их полки,
#: `<div data-composition-id="…" id="mk-ps-root">` у части блоков.
_ROOT_ID = re.compile(
    r'id="([^"]+)"[^>]*data-composition-id="(?P<a>[^"]+)"'
    r'|data-composition-id="(?P<b>[^"]+)"[^>]*id="([^"]+)"')


def block_root(html: str) -> str:
    """Id корня позиции. Пустая строка — корень без id."""
    match = _ROOT_ID.search(html)
    if not match:
        return ""
    return match.group(1) or match.group(4) or ""


def declare_box(path, unique: str, width: int, height: int) -> None:
    """Объявить копии позиции размер её коробки в кадре.

    Упругая позиция полки размеров не объявляет нарочно — «no data-width or
    data-height; it fills whatever box the host clip gives it»
    (`registry/components/count-up/README.md:33`). Их же линтер зовёт это
    `root_missing_dimensions` (severity error), и под `--strict` ошибка роняет
    сборку целиком: файл он судит сам по себе, о хосте не зная.

    Коробку считает код — зону эффекта или весь кадр, — поэтому её и
    объявляем. Хосту это ничего не ломает: их загрузчик копирует размеры корня
    на хост только когда хост их не объявил
    (`inlineSubCompositions.ts:392-394`), а числа здесь те же самые.
    """
    path = Path(path)
    html = path.read_text(encoding="utf-8")
    marker = f'data-composition-id="{unique}"'
    out = []
    for piece in html.split(marker):
        out.append(piece)
    if len(out) < 2:
        return
    fixed = out[0]
    for piece in out[1:]:
        tail = piece.split(">", 1)[0]
        fixed += marker + ("" if "data-width" in tail else
                           f' data-width="{int(width)}"'
                           f' data-height="{int(height)}"') + piece
    path.write_text(fixed, encoding="utf-8")


def needed_blocks(storyboard: dict) -> list[str]:
    """Какие блоки каталога сборка поставит их же `hyperframes add`.

    Блок вспышки нужен всегда: где именно она вспыхнет, решает арифметика
    планов камеры уже во время сборки, а ставить блок тогда поздно — реестр
    поднят раньше.
    """
    found: list[str] = [FLASH_BLOCK]
    for scene in storyboard.get("scenes") or []:
        block = (scene.get("overlay") or {}).get("block") \
            if isinstance(scene.get("overlay"), dict) else None
        if block and block not in found and str(block) not in _skipped_blocks():
            found.append(str(block))
        for element in scene_elements(scene):
            name = str(element["name"]).strip()
            if name not in found and name not in _skipped_blocks():
                found.append(name)
        # Блоки схем ставим по любой названной форме — и выбранной агентом, и
        # запасной: какая из них понадобится, выяснится уже после подбора, а
        # реестр к тому времени опущен.
        for field in ("schema", "fallback"):
            plan = scene.get(field)
            form = plan.get("form") if isinstance(plan, dict) else None
            block = FORMS.get(form)
            if block and block not in found:
                found.append(block)
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


#: Раскладки, в которых ведущая занимает не меньше половины кадра. Наезд в
#: окне-уголке не виден: 312 px по ширине, 18 % прироста там — три пикселя.
_BIG_PRESENTER = ("full", "punch", "stack", "split")

#: Куда целится масштаб. Точка лица берётся из замера `face.json`, а не
#: назначается: наезд от центра кадра уводит голову за верхний край.
DEFAULT_ORIGIN = "50% 38%"


def zoom_origin(face: dict | None) -> str:
    """`transform-origin` наезда — точка лица в долях кадра."""
    if not face:
        return DEFAULT_ORIGIN
    return (f'{float(face["cx"]) / OUT_W * 100:.1f}% '
            f'{float(face["cy"]) / OUT_H * 100:.1f}%')


#: Порог их гейта `--frame-check`: выезд медиа за корень композиции меньше
#: max(120 px, 6 % короткой стороны канваса) находкой не считается
#: (packages/cli/src/utils/checkPipeline.ts:75-76,314-317 на пине 0.7.84). На
#: 1080x1920 доля даёт 64,8 — работает пиксельный порог.
FRAME_BREACH_FLOOR = 120.0


def frame_safe_scale(position: str, face: dict | None) -> float:
    """Потолок наезда, при котором окно ведущей не роняет `frame_out_of_frame`.

    Гейт меряет `getBoundingClientRect` тега `<video>` против корня композиции
    и не видит ни `overflow:hidden` обёртки, ни `data-layout-allow-overflow`:
    в их сборщике кандидатов проверки флагов нет вовсе
    (packages/cli/src/commands/layout-audit.browser.js:1411-1415), а сама
    находка читает только severity (checkPipeline.ts:310-330). Штатной пометки
    у правила нет — значит держим геометрию.

    Окно, кроющее ≥95 % канваса по ОБЕИМ сторонам, их проверка пропускает
    (`candidateIsSized`, checkPipeline.ts:222-228): это `full`, `punch` и
    `overlay`, им потолка нет. Остальным считаем, насколько можно вырасти,
    пока выезд за каждый край меньше порога: прирост стороны делит точка
    отсчёта, а к краю кадра прибавляется зазор, который у окна уже есть.
    Округляем вниз — на самом пороге находка ещё срабатывает.
    """
    rect = _presenter_rect(position)
    if rect["width"] >= 0.95 * OUT_W and rect["height"] >= 0.95 * OUT_H:
        return math.inf
    ox, oy = (float(part.rstrip("%")) / 100
              for part in zoom_origin(face).split())
    room = []
    for share, size, before, after in (
            (ox, rect["width"], rect["left"],
             OUT_W - rect["left"] - rect["width"]),
            (oy, rect["height"], rect["top"],
             OUT_H - rect["top"] - rect["height"])):
        for part, gap in ((share, before), (1 - share, after)):
            if part * size > 0:
                room.append((FRAME_BREACH_FLOOR + gap) / (part * size))
    return math.floor((1.0 + min(room)) * 1000) / 1000 if room else math.inf


#: Кадрирование по умолчанию — то же, что `object-fit: cover` делает сам.
DEFAULT_FIT = "50% 50%"

#: Запас над макушкой, долями высоты головы. В пикселях его назначать не из
#: чего: `h` в face.json не измерена, а выведена из доли кадра
#: (face_detect.FACE_HEIGHT_RATIO), да и «макушка = cy − h» — такая же
#: прикидка. Голова — единственная мерка, в которой обе прикидки живут: 0,4
#: головы покрывают и их, и покачивание ведущей вокруг медианного `cy`
#: (детектор берёт медиану центров по кадрам, zoom.detect_face_anchor).
CROP_HEADROOM = 0.4


def crop_position(face: dict | None) -> str:
    """`object-position` окна ведущей — где резать исходник по вертикали.

    Клип 1080x1920 вписывается в окно раскладки правилом `object-fit: cover`,
    и от центра у `stack` (окно 1080x844) видна полоса исходника 538..1382:
    макушка остаётся выше неё, у говорящего срезан верх головы (прогон 24,
    face.json cx=526 cy=707 h=269 — макушка на 438).

    Правило CSS одно на все раскладки, а окно меняется по ходу ролика, поэтому
    считаем долю по каждой и берём наименьшую: меньшая доля показывает больше
    ВЕРХА исходника, то есть годится и для всех остальных окон — лишний запас
    над головой кадру не вредит, срезанная макушка вредит. Раскладки, где по
    вертикали резать нечего (`full`, `pip-*`), в счёт не идут вовсе: там
    `object-position` ничего не двигает.
    """
    _, down = crop_fractions(face)
    if not face:
        return DEFAULT_FIT
    # По горизонтали не двигаем ничего: клип и кадр одной ширины, резать нечего
    # (`crop_fractions` всегда отдаёт середину), и дробь там была бы шумом.
    return f"50% {down * 100:.1f}%"


def crop_fractions(face: dict | None) -> tuple[float, float]:
    """Те же доли числами — их читает гейт «текст не на лице».

    Гейт пересчитывает лицо в координаты кадра (`hf_layout.moved_face`) и без
    этих долей считал бы вырез от середины: прямоугольник охранял бы место,
    где лица уже нет.
    """
    if not face:
        return 0.5, 0.5
    # верхняя граница полосы, которую обязано быть видно
    top = float(face["cy"]) - float(face["h"]) * (1 + CROP_HEADROOM)
    shares = []
    for rect in VIDEO_RECTS.values():
        scale = max(rect["width"] / OUT_W, rect["height"] / OUT_H)
        # сколько высоты исходника не влезло в окно — по нему и ездит доля
        spare = OUT_H * scale - rect["height"]
        if spare <= 0:
            continue
        shares.append(top * scale / spare)
    share = min(shares, default=0.5)
    return 0.5, min(max(share, 0.0), 1.0)


def camera_plans(moments: list[tuple], words: list[dict],
                 duration: float, *, face: dict | None = None) -> list[dict]:
    """Планы камеры на всё аватарное время, со ступенями масштаба.

    Куски с ведущей режутся на планы по паузам речи (`hf_montage`), и каждому
    плану достаётся ступень: соседние отличаются не меньше чем на 8 %, наезд —
    не чаще каждого третьего плана и только там, где окно большое.

    Ступень подрезается потолком окна (`frame_safe_scale`): у окна, которое
    кадр не кроет, наезд выносит `<video>` за край кадра, и их `--frame-check`
    зовёт это `frame_out_of_frame`. Числа пишутся сюда же, в `camera.json`, —
    гейт наездов меряет готовый файл по ним.
    """
    plans: list[dict] = []
    for index, (start, position) in enumerate(moments):
        if position == "none":
            continue
        end = moments[index + 1][0] if index + 1 < len(moments) else duration
        if end - start < 0.2:
            continue
        cut = cut_into_plans(words, float(start), float(end))
        big = [position in _BIG_PRESENTER] * len(cut)
        cap = frame_safe_scale(position, face)
        plans += [dict(plan, position=position,
                       scale_from=min(plan["scale_from"], cap),
                       scale_to=min(plan["scale_to"], cap))
                  for plan in zoom_ladder(cut, big=big, offset=len(plans))]
    return plans


def _zoom_timeline(plans: list[dict]) -> list[str]:
    """Ступени и наезды на окне ведущей.

    Целимся в `<video>` внутри обёртки, а не в саму обёртку: обёртке геометрию
    назначает раскладка, и драться с ней за один и тот же стиль нельзя.
    Масштаб через `scale` — их линтер и требует трансформы:
    твин по `width`/`height` он заворачивает `gsap_non_transform_motion`.
    Смена ступени скачком (`set`), наезд — твином, как у Юли.
    """
    lines: list[str] = []
    target = _js("#video-wrap video")
    for plan in plans:
        # Позиция ступени — время на шкале: `markup_time`, а не `_q`.
        at = markup_time(plan["start"])
        if plan["kind"] == "push":
            lines.append(
                f'tl.fromTo({target}, {{ scale: {plan["scale_from"]} }}, '
                f'{{ scale: {plan["scale_to"]}, duration: {plan["ramp"]}, '
                f'ease: "power2.out" }}, {at});')
        else:
            lines.append(
                f'tl.set({target}, {{ scale: {plan["scale_from"]} }}, {at});')
    return lines


def _presenter_move(position: str, at: float) -> list[str]:
    """Перестановка окна ведущей мгновенная — стыком, а не переездом.

    Твин по `left`/`top` их линтер заворачивает ошибкой
    `gsap_non_transform_motion`: эти свойства прилипают к целому пикселю при
    вёрстке, и на покадровой съёмке медленное движение дёргается. Через
    трансформы нельзя: раскладки меняют пропорции окна, и неравномерный `scale`
    раздавил бы кадр. А эталонным рилсам переезд и не нужен — там смена
    положения всегда на стыке.
    """
    at = markup_time(at)
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


def overlay_problem(block: str) -> str | None:
    """Почему эту накладку в кадр не поставить. `None` — поставить можно.

    Один ответ на два места: этим проходом (`settle_fillers`) плашка снимается
    до разбора пустых сцен, а сборка проверяет то же самое ещё раз, уже перед
    вёрсткой слоя. Разойдись они — проход посчитал бы кадр закрытым, сборка
    сняла бы плашку, и сцена осталась бы с пустым кадром.
    """
    reason = _skipped_blocks().get(str(block))
    if reason:
        return reason
    known = _known_overlays()
    if known and str(block) not in known:
        return ("такого блока в каталоге нет — паспорта лежат в "
                "OVERLAYS.md рядом с заданием")
    return None


def element_problem(name: str) -> str | None:
    """Почему эту позицию каталога в кадр не поставить. `None` — можно.

    Тот же вопрос задан трижды и одним кодом: ранняя сверка плана до заказа
    ведущей (`hf_gates.elements_problems`), проход `settle_fillers` до разбора
    пустых сцен и сама вёрстка слоя. Разойдись они — план прошёл бы сверку,
    проход посчитал бы кадр закрытым, а сборка сняла бы элемент.
    """
    reason = _skipped_blocks().get(str(name))
    if reason:
        return reason
    cards = _catalog_cards()
    if cards and str(name) not in cards:
        return ("такой позиции в каталоге нет — они перечислены в "
                "`catalog.index.md` рядом с заданием")
    return None


#: Поле раскадровки со снятыми позициями каталога: `{scene, name, why}`.
#: Читает его `D36_elements` после сборки (`hf_gates.elements_delivered`):
#: раскадровка обязана описывать собранный кадр, поэтому снятая позиция из
#: `scene["elements"]` вычищается — и без этого следа гейту нечего судить.
#: Пересборка `artyom-rebuild-4b` потеряла так `count-up`: строка в логе была,
#: `D36_elements` остался PASS, и в карточку изъян не попал.
DROPPED_ELEMENTS = "elementsDropped"


def drop_element(board: dict, scene: dict, name: str, reason: str) -> None:
    """Снять позицию каталога из кадра — вслух, а не одной строкой в логе.

    Одна дверь на все причины снятия (каталог отказал, зоны нет, слов не
    хватило, до конца ролика не осталось секунд): лог видит тот, кто откроет
    папку прогона, а карточку сборки — заказчик и гейты.
    """
    print(f'{scene.get("id", "?")}: элемент {name} снят — {reason}')
    board.setdefault(DROPPED_ELEMENTS, []).append(
        {"scene": str(scene.get("id", "?")), "name": str(name),
         "why": str(reason)})


def settle_fillers(board: dict, resolved: dict[str, dict]) -> list[str]:
    """Снять с раскадровки то, чего в кадре не будет: значок без файла и
    накладку с непригодным блоком.

    Обе снимались уже в `build_composition` (значок — не ответил подбор,
    плашка — имя блока названо по памяти), то есть ПОСЛЕ прохода, который
    разбирает пустые сцены. Сцена без аватара, стоявшая на одном значке,
    оставалась после этого с фоном и титром: починить её код уже не успевал,
    и сборку роняли D25 по раскадровке и D26 по собранной композиции. Значок и
    плашка — законный способ закрыть кадр по нашему же закрытому списку
    (`hf_montage.frame_filler`), и правило «средство, которого не будет,
    снимается до разбора пустых сцен» обязано действовать на них так же, как
    на вставку (`settle_inserts`).

    Здесь судится только то, что известно без вёрстки: файл значка уже
    подобран, каталог уже опрошен. Остальные отказы сборки (плашке не хватило
    места до следующей или до конца ролика, слот назван не тем именем) требуют
    поставить блок и потому остаются на месте — их по-прежнему ловят гейты.
    Геометрию значка (`icon_fits`) здесь не считаем нарочно: значок уступает
    место только ведущей, а с ведущей в кадре сцена не пуста.

    Возвращает id сцен, у которых средство снято.
    """
    touched = []
    for scene in board.get("scenes") or []:
        name = str(scene.get("id"))
        if scene.get("icon") and not (
                resolved.get(f"{name}::icon") or {}).get("file"):
            # Двух причин две записи в логе: у сцены со вставкой значка нет по
            # правилу (его и не подбирали — `icon_intents`), у остальных не
            # ответил подбор.
            print(f"{name}: значок снят — "
                  + ("вставка приехала, а значок ей запас, а не довесок"
                     if insert_of(scene) else "подбор не дал файла"))
            scene.pop("icon", None)
            touched.append(name)
        overlay = scene.get("overlay")
        block = overlay.get("block") if isinstance(overlay, dict) else None
        reason = overlay_problem(str(block)) if block else None
        if reason:
            print(f"{name}: накладка {block} снята — {reason}")
            scene.pop("overlay", None)
            if name not in touched:
                touched.append(name)
        elements = scene_elements(scene)
        kept = []
        for element in elements:
            reason = element_problem(str(element["name"]))
            if reason:
                drop_element(board, scene, str(element["name"]), reason)
                continue
            kept.append(element)
        if len(kept) != len(elements):
            scene["elements"] = kept
            if name not in touched:
                touched.append(name)
    return touched


def settle_inserts(board: dict, resolved: dict[str, dict],
                   clips: list[dict], duration: float,
                   public=None) -> list[str]:
    """Свести план с тем, что реально нашёл `media-use`.

    Вставка засчитывается, только если файл нашёлся и годится (см.
    `insert_problem`). Ронять прогон из-за одной картинки дорого, а оставить как
    есть нельзя: на её месте будет чёрный прямоугольник. Дальше по обстановке:
    где ведущая есть — сцена отдаётся ей во весь кадр; где её нет — сцена
    помечается `needsSchema`, и кадр закрывает запасная схема из `fallback`
    (логотип и значок), которую подбирают вторым заходом.

    Возвращает список сцен, оставшихся без вставки, — для отчёта.
    """
    gaps = avatar_gaps(clips, duration)
    scenes = board.get("scenes") or []

    def usable(key: str) -> str | None:
        found = resolved.get(key) or {}
        if not found.get("file"):
            return None
        if public is not None and insert_problem(Path(public) / found["file"]):
            return None
        return found["file"]

    # Один файл на один план. `media-use` отвечает на близкие намерения
    # одним и тем же снимком — на прогоне 15 три сцены получили общий файл, а
    # ещё две получили один снимок под разными именами (`image_002.jpg` и
    # `image_014.jpg` совпали побайтно). Поэтому сверяем содержимое, а не путь.
    # Повтор кадра — и монтажный брак (в эталонных рилсах картинка не
    # повторяется), и находка их линтера: `duplicate_media_discovery_risk`
    # (packages/lint/src/rules/media.ts:239), а под `--strict` она валит сборку.
    good: dict[str, list[str] | None] = {}
    taken: set[str] = set()
    for scene in scenes:
        if not insert_of(scene):
            continue
        need = shots_for(scene)
        files: list[str] = []
        for shot in range(need):
            file = usable(media_key(scene["id"], shot))
            mark = _content_mark(public, file) if file else None
            if mark is None or mark in taken:
                continue
            taken.add(mark)
            files.append(file)
        # Серия живёт целиком или не живёт вовсе: одиночной вставки в монтаже
        # не бывает, и половина серии — это как раз она.
        good[scene["id"]] = files if len(files) == need else None

    def neighbours(index: int, what: str) -> set:
        return {(scenes[i].get(what) if 0 <= i < len(scenes) else None)
                for i in (index - 1, index + 1)}

    lost = []
    for index, scene in enumerate(scenes):
        if not insert_of(scene) or good.get(scene["id"]):
            continue
        scene["insert"] = None
        # Чем закрыть кадр — решает то же правило, что и при отборе серий:
        # нижний уголок ведущей переживает потерю биролла вместе со схемой,
        # остальное уходит под полнокадровую ведущую или под схему целиком.
        # Прежде здесь стояла копия чужой вставки («занять у соседа») — она
        # ставила в кадр картинку не про эту реплику и обходила сверку по
        # содержимому, ради которой всё это и считается.
        refill_scene(scenes, index, gaps)
        if not scene.get("needsSchema"):
            lost.append(scene["id"])
    schemas = [s["id"] for s in scenes if s.get("needsSchema")]
    if schemas:
        print("кадр закрывает запасная схема: " + ", ".join(schemas))
    return lost


# ----------------------------------------------------------------- сборка

def build_composition(rdir, sdk, *, storyboard: dict, clips: list[dict],
                      duration: float, words: list[dict],
                      resolved: dict[str, dict] | None = None,
                      sfx_whoosh: str | None = None,
                      theme: dict | None = None,
                      face: dict | None = None) -> Path:
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
    # Биролл входит в кадр СЕРИЕЙ из двух планов: вход в серию и выход из неё
    # — жёсткая склейка, движение живёт только на шве между планами. Правило
    # Юли, её же эталон (docs/HANDOFF-BROLL-ZOOM-V6.md, пункт 2): одиночная
    # вставка читается как случайная картинка, а пара планов — как монтаж.
    series: dict[str, list[str]] = {}
    for scene in scenes:
        if not insert_of(scene):
            continue
        files = [(resolved.get(media_key(scene["id"], shot)) or {}).get("file")
                 for shot in range(shots_for(scene))]
        if all(files):
            series[scene["id"]] = files
    # Дорожки вставок — ротацией: планы, пересекающиеся на шве, обязаны лежать
    # на разных дорожках, а больше трёх на одной их линтер зовёт
    # `timeline_track_too_dense`. Ротация по ceil(n/3) дорожек закрывает оба
    # требования разом.
    shot_count = sum(len(files) for files in series.values())
    insert_tracks = max(2, -(-shot_count // INSERTS_PER_TRACK))
    staged = 0
    for scene in scenes:
        files = series.get(scene["id"])
        if not files:
            continue
        rect = insert_rect(str(scene.get("presenter") or "full"))
        if rect is None:
            raise RuntimeError(
                f'{scene["id"]}: ведущая стоит {scene.get("presenter")!r} и '
                "закрывает кадр целиком — вставке места нет. Либо убери "
                "вставку, либо отправь ведущую в угол (`pip-*`), в половину "
                "кадра (`stack`, `split`) или убери её из сцены (`none`)")
        beat = _beat(scene)
        for shot, (open_at, close_at) in enumerate(split_series(scene, words)):
            file = files[shot]
            open_at, close_at = _q(open_at), _q(close_at)
            name = f'ins-{scene["id"]}-{shot}'
            # Уходящий план живёт на CUT_SECONDS дольше своего куска: их
            # правило — «outgoing scene content must be fully visible when the
            # transition starts» (transitions/overview.md:23), шов делает
            # движение, а не гашение. Последний план серии не продлеваем:
            # выход из серии — жёсткая склейка.
            last = shot == len(files) - 1
            overlap = 0.0 if last else CUT_SECONDS
            body.append(_insert_tag(
                scene, rect, file, start=open_at,
                duration=close_at - open_at + overlap,
                track=TRACK_INSERT + staged % insert_tracks, name=name))
            image = file.lower().split("?")[0].endswith(_IMAGE_SUFFIXES)
            target = f"#{name} .ins-media" if image else f"#{name}-box"
            if shot:
                # шов внутри серии: второй план приезжает движением
                timeline += _entry(target, beat, open_at)
            if not last:
                timeline += _exit(target, beat, close_at)
            staged += 1

    # ── накладки агента: их блоки из каталога ────────────────────────────
    # Плашка живёт свою родную длительность от начала сцены — резать чужой
    # таймлайн сильно короче значит показать полусобранную сцену
    # (min_card_seconds, порог проверен кадрами прогона 13).
    #
    # Но дольше начала СЛЕДУЮЩЕЙ плашки она не живёт: обе стоят на одном
    # месте кадра, и наложение их же аудит зовёт `content_overlap` (прогон 24,
    # две плашки подряд на сценах 19,63 и 23,13 при родных 4,8 с). Не влезает
    # по минимуму — вторую не ставим вовсе: полплашки хуже её отсутствия.
    from reels_factory.hf_slots import min_card_seconds

    marked = []
    for scene in scenes:
        overlay = scene.get("overlay")
        block = overlay.get("block") if isinstance(overlay, dict) else None
        if not block:
            continue
        # Тот же вопрос уже задан в `settle_fillers` до разбора пустых сцен;
        # здесь он повторяется на случай, если сборку позвали без прохода.
        reason = overlay_problem(str(block))
        if reason:
            print(f'{scene["id"]}: накладка {block} снята — {reason}')
            scene.pop("overlay", None)
            continue
        marked.append(scene)
    # Сколько дорожек отвести скримам — по тому же счёту, что у вставок:
    # больше трёх с `data-start` на одной дорожке их линтер зовёт
    # `timeline_track_too_dense`. Считаем до цикла и с запасом: сцена может
    # ещё потерять накладку по времени, лишняя дорожка ничего не стоит.
    scrim_tracks = max(1, -(-sum(
        1 for scene in marked
        if _block_backing().get(str(scene["overlay"]["block"])) == "none"
        and insert_of(scene)) // SCRIMS_PER_TRACK))
    staged_overlays = staged_scrims = 0
    for position, scene in enumerate(marked):
        overlay = scene["overlay"]
        start = _q(scene["startSec"])
        room = duration - start
        if position + 1 < len(marked):
            room = min(room, _q(marked[position + 1]["startSec"]) - start)
        try:
            unique, native, canvas = _stage_overlay(
                public, str(overlay["block"]), scene["id"], sdk=sdk,
                text={k: str(v)
                      for k, v in (overlay.get("text") or {}).items()})
        except RuntimeError as error:
            # Слот назван не тем именем либо не назван вовсе: заполнение
            # падает, и раньше вместе с ним падала вся попытка. Паспорта
            # лежат в OVERLAYS.md, агент открывает их сам — цена ошибки
            # должна быть равна цене плашки, а не цене прогона.
            print(f'{scene["id"]}: накладка {overlay["block"]} снята — {error}')
            scene.pop("overlay", None)
            continue
        length = round(min(native, room), 4)
        if length < min_card_seconds(native):
            if position + 1 < len(marked) and room < duration - start:
                print(f'{scene["id"]}: накладка {overlay["block"]} снята — до '
                      f"следующей плашки {room:.2f} с, а ей нужно "
                      f"{min_card_seconds(native):g}")
                scene.pop("overlay", None)
                continue
            # До конца ролика места не хватило. Раньше это роняло попытку
            # целиком — из-за плашки, без которой ролик прекрасно живёт;
            # задание при этом само предлагало ставить её «на призыве в
            # финале», где места нет никогда.
            print(f'{scene["id"]}: накладка {overlay["block"]} снята — до '
                  f"конца ролика {duration - start:.2f} с, а ей нужно "
                  f"{min_card_seconds(native):g}")
            scene.pop("overlay", None)
            continue
        scale, box = _overlay_geometry(str(overlay["block"]), canvas)
        # Накладке без своей подложки нужен слой читаемости: их проверка
        # контраста меряет пиксели под буквами, а `text-shadow` не
        # засчитывает — на светлом биролле белый текст проваливается. Градиент
        # их же: «Glass without legibility gradient = white-on-white
        # catastrophe over bright video. Always pair them»
        # (talking-head-recut/references/layouts/overlay.html:52-68).
        # Время в разметку — `markup_time`, длительность парно.
        at, span = (markup_time(start),
                    markup_time(start + length) - markup_time(start))
        # `class="clip"` обязателен: элемент со временем, но без этого токена
        # их линтер валит ошибкой `timed_element_missing_clip_class`
        # (packages/lint/src/rules/composition.ts:544-576 на пине 0.7.84,
        # severity error), а ошибка обрывает `check` до браузерной части.
        # Причина ровно эта, одна: видимость рантайм держит по атрибуту, а не
        # по классу — `syncTimedElementVisibility` обходит
        # `document.querySelectorAll("[data-start]")`
        # (packages/core/src/runtime/init.ts:1921-1923), и класса `clip` не
        # проверяет нигде. Их же линтер обещает обратное («will be visible for
        # the entire composition», composition.ts:570) — это их текст, не наш
        # опыт: в кадре весь ролик градиент не стоял.
        if _block_backing().get(str(overlay["block"])) == "none" \
                and insert_of(scene):
            body.append(
                f'    <div class="ovl-scrim clip" id="scrim-{scene["id"]}"'
                f' data-start="{at:.4f}" data-duration="{span:.4f}"'
                f' data-track-index='
                f'"{TRACK_SCRIM + staged_scrims % scrim_tracks}"></div>')
            staged_scrims += 1
        body.append(
            f'    <div class="ovl" style="{box}">'
            f'<div data-layout-allow-overflow="true" style="position:absolute;'
            f'left:0;top:0;transform:scale({scale:.4f});transform-origin:0 0">'
            f'<div id="ovl-{scene["id"]}" class="clip"'
            f' data-layout-allow-overflow="true"'
            f' data-composition-id="{unique}"'
            f' data-composition-src="compositions/{unique}.html"'
            f' data-start="{at:.4f}" data-duration="{span:.4f}"'
            f' data-track-index="{TRACK_OVERLAY + staged_overlays % 2}"'
            f' data-width="{canvas[0]}" data-height="{canvas[1]}"></div>'
            f"</div></div>")
        staged_overlays += 1

    # ── элементы каталога ─────────────────────────────────────────────────
    # Имя позиции агент выбирает поиском по смыслу в `catalog.index.md` — так
    # велит их же скилл реестра («Search by intent before browsing»,
    # hyperframes-registry/SKILL.md:88). Всё остальное считает код: секунды,
    # зону, подстановку слов, установку. Чем позиция становится в кадре,
    # решает её карточка (`reels.kind`), а не поле плана:
    #
    # - `scene` — во весь кадр, их же портом под вертикаль, ПОДЛОЖКОЙ под окно
    #   ведущей (`.ovl-back`, z-index 15): окно уголка остаётся видно поверх,
    #   как остаётся оно видно под схемой;
    # - `effect` — коробкой в свободной зоне кадра (`effect_zone`);
    # - `overlay` — на стык сцен поверх всего, за `STITCH_LEAD` до среза;
    # - вида нет — это сегодняшняя плашка, и геометрия у неё та же
    #   (`_overlay_geometry`).
    staged_elements = 0
    #: Имя -> тип карточки: исходник компонента снят по `components/`, не по
    #: плоской `compositions/` — тип нужен ниже, чтобы объявить ему коробку
    #: по верному пути (`_installed_path`).
    stencils: dict[str, str] = {}
    for scene in scenes:
        kept = []
        for element in scene_elements(scene):
            name = str(element["name"]).strip()
            reason = element_problem(name)
            if reason:
                drop_element(storyboard, scene, name, reason)
                continue
            card = _catalog_cards().get(name) or {}
            kind = str(card.get("kind") or "")
            start, end = _q(scene["startSec"]), _q(scene["endSec"])
            # Срез — это начало сцены, и элемент стыка встаёт ЗА него: накладка
            # кроет кадр серединой своего хода, а не началом. Решает вид
            # карточки, а не план: агенту не из чего выбирать иначе — только
            # стык живёт на границе сцен, остальные виды — внутри своей.
            cut = kind == "overlay"
            begin = max(0.0, _q(start - STITCH_LEAD)) if cut else start
            # У стыка длительность своя — родная длительность позиции: резать
            # чужой ход значит показать полперехода. У остальных элемент живёт
            # свою сцену.
            length = (float(card.get("duration") or FLASH_NATIVE)
                      if kind == "overlay" else end - begin)
            length = round(min(length, duration - begin), 4)
            if length <= 0.2:
                drop_element(storyboard, scene, name,
                             "до конца ролика остаётся "
                             f"{duration - begin:.2f} с")
                continue
            rect = None
            if kind == "effect":
                position = str(scene.get("presenter") or "none")
                rect = effect_zone(position)
                if rect is None:
                    drop_element(storyboard, scene, name,
                                 f"ведущая {position!r} не оставила в кадре "
                                 "свободной зоны выше полосы титра")
                    continue
            # Слова агента идут в слоты по порядку самой разметки: их читает
            # `_stage_overlay` разбором позиции и раскладывает существующим
            # слоем (`hf_slots.fill_ops`). Карточка тут не спрашивается — она
            # отвечает индексу, и её `text_slots` держали видимые демо-строки
            # вместо имён слотов, из-за чего `v-code-diff` терялся на каждой
            # сборке (отчёт B4).
            # Имя своё, не `words`: так зовётся параметр сборки со словами
            # титра, и тень над ним роняла бы весь слой субтитров ниже.
            said = [str(word) for word in element.get("words") or []]
            card_type = str(card.get("type") or "block")
            # Paste-контрактный эффект (`reels.mount`, карточка B1) не
            # монтируется саб-композицией вовсе — своего `data-composition-id`
            # и `<template>` у него нет (`_stage_overlay` на нём даёт
            # `missing_or_empty_sub_composition`, проверено живым
            # `check --strict` на `badge-pop`). Вставляем литералом
            # (`paste_effect`), той же идеей, какой каталог уже вставляет
            # `caption-highlight`.
            mount_kind = str(card.get("mount") or "composition")
            paste_html = None
            if kind == "effect" and mount_kind == "paste":
                unique = f"{name}--{scene['id']}"
                try:
                    paste_html = paste_effect(
                        sdk, public, name, unique=unique,
                        variables=element.get("variables") or {})
                except RuntimeError as error:
                    drop_element(storyboard, scene, name, str(error))
                    continue
            else:
                source = _installed_path(public, name, card_type)
                root = (block_root(source.read_text(encoding="utf-8"))
                        if source.exists() else "")
                dimensions = card.get("dimensions") or {}
                landscape = (int(dimensions.get("width") or 0)
                            > int(dimensions.get("height") or 0))
                # Канвас переносим только ландшафтной сцене: сплошная замена
                # литералов меняет 1920 и 1080 местами, и вертикальную позицию
                # она уложила бы на бок. Палитра и гарнитура — правилом CSS
                # ниже по файлу: `_FONT_FAMILY` выше стирает типографику
                # позиции целиком.
                port = {"duration": length,
                       "elastic": not (kind == "scene" and landscape),
                       "height": OUT_H if kind == "scene" else None,
                       "config": {},
                       "css": palette_css(name, colors, root=root)}
                try:
                    unique, _, canvas = _stage_overlay(
                        public, name, scene["id"], sdk=sdk if said else None,
                        words=said or None, port=port, card_type=card_type)
                except RuntimeError as error:
                    drop_element(storyboard, scene, name, str(error))
                    continue
                if not dimensions and kind in ("scene", "effect"):
                    box = ((OUT_W, OUT_H) if kind == "scene"
                           else (rect["width"], rect["height"]))
                    declare_box(
                        Path(public) / "compositions" / f"{unique}.html",
                        unique, box[0], box[1])
                    canvas = box
                    if name not in stencils:
                        stencils[name] = card_type
            # Значения переменных — одним JSON на хосте, их штатным каналом
            # (`add.ts:64-72`): в файл позиции их не вписывают, чтобы два
            # маунта одной позиции могли нести разное.
            values = (" data-variable-values='"
                      + json.dumps(element.get("variables") or {},
                                   ensure_ascii=False).replace("'", "&#39;")
                      + "'") if element.get("variables") else ""
            at = markup_time(begin)
            span = markup_time(begin + length) - at
            mount = f'el-{scene["id"]}-{staged_elements}'
            track = TRACK_ELEMENT + staged_elements % ELEMENT_TRACKS
            # Хостовый `data-composition-id` — НЕ тот же текст, что несёт
            # корень скопированного файла: копия уже переименована в
            # `unique` (`_stage_overlay`, строка с `.replace(f'data-
            # composition-id="{block}"', ...)`), и их `inlineSubCompositions.
            # ts` вклеивает содержимое файла в тот же документ, а не в
            # настоящий `<iframe>` — `document.querySelectorAll` внутри их
            # скоуп-скрипта (`compositionScoping.ts`) тогда находит ДВА узла
            # с одним `data-composition-id`: хост и корень копии. Живой
            # прогон (`hyperframes snapshot --at` на секундах 1/3/5/7.5)
            # показал: с совпадающим id содержимое элементов вроде focus-rack
            # держится первые ~3 с и гаснет — с разведёнными id (суффикс
            # `-host` только на хосте, корень копии не трогаем) держится до
            # конца отведённой длительности. Разбор — scratchpad/catalog-
            # tails/id-collision-rootcause.md.
            common = (f' data-composition-id="{unique}-host"'
                      f' data-composition-src="compositions/{unique}.html"'
                      f' data-start="{at:.4f}" data-duration="{span:.4f}"'
                      f' data-track-index="{track}"')
            if kind == "scene":
                # Подложка (`.ovl-back`), а не накладка: слой ниже окна
                # ведущей. Позиция полки заливает свою коробку целиком, и
                # слоем накладки (z-index 28) она кроет собой оплаченный клип —
                # ровно ту ошибку, которую задание называет самой дорогой.
                body.append(
                    f'    <div class="ovl-back">'
                    f'<div id="{mount}" class="clip"{common}'
                    f' data-width="{OUT_W}" data-height="{OUT_H}"'
                    f' style="position:absolute;left:0;top:0;'
                    f'width:{OUT_W}px;height:{OUT_H}px"{values}></div></div>')
            elif kind == "effect" and paste_html is not None:
                # Без `data-composition-src`: содержимое уже здесь, литералом.
                # Центрируем в коробке — paste-примитивы полки саморазмерны
                # (кнопка, бейдж, плашка), а не «эластичны» под любой размер,
                # как саб-композиции с `declare_box`.
                body.append(
                    f'    <div class="ovl" style="left:{rect["left"]}px;'
                    f'top:{rect["top"]}px;width:{rect["width"]}px;'
                    f'height:{rect["height"]}px">'
                    f'<div id="{mount}" class="clip"'
                    f' data-start="{at:.4f}" data-duration="{span:.4f}"'
                    f' data-track-index="{track}"'
                    f' style="position:absolute;left:0;top:0;'
                    f'width:{rect["width"]}px;height:{rect["height"]}px;'
                    f'display:flex;align-items:center;'
                    f'justify-content:center">{paste_html}</div></div>')
            elif kind == "effect":
                body.append(
                    f'    <div class="ovl" style="left:{rect["left"]}px;'
                    f'top:{rect["top"]}px;width:{rect["width"]}px;'
                    f'height:{rect["height"]}px">'
                    f'<div id="{mount}" class="clip"{common}'
                    f' style="position:absolute;left:0;top:0;'
                    f'width:{rect["width"]}px;'
                    f'height:{rect["height"]}px"{values}></div></div>')
            else:
                # Стык и плашка приезжают чужим канвасом, и вписывает их в
                # кадр обёртка с `transform`: их загрузчик жёстко ставит хосту
                # пиксели канваса позиции (compositionLoader.ts:517-524).
                if kind == "overlay":
                    scale = OUT_H / canvas[1]
                    place = (f"left:{-round((canvas[0] * scale - OUT_W) / 2)}px"
                             ";top:0")
                    layer = "fx"
                else:
                    scale, place = _overlay_geometry(name, canvas)
                    layer = "ovl"
                body.append(
                    f'    <div class="{layer}" style="{place}">'
                    f'<div data-layout-allow-overflow="true"'
                    f' style="position:absolute;left:0;top:0;'
                    f'transform:scale({scale:.4f});transform-origin:0 0">'
                    f'<div id="{mount}" class="clip"'
                    f' data-layout-allow-overflow="true"{common}'
                    f' data-width="{canvas[0]}" data-height="{canvas[1]}"'
                    f"{values}></div></div></div>")
            staged_elements += 1
            kept.append(element)
        if scene.get("elements") is not None:
            # Раскадровка на диске обязана описывать собранный кадр: по ней
            # судят гейты, и элемент, которого в кадре нет, закрывал бы сцену
            # на бумаге.
            scene["elements"] = kept
    # Исходник упругой позиции остаётся на диске после `hyperframes add` и в
    # кадр не едет — с него сняты копии, — но их `check` судит каждый файл
    # отдельно и отвечает на него тем же `root_missing_dimensions`. Объявляем
    # ему кадр: числа стенсиля ни на что не влияют, а сборку он больше не
    # роняет. Правится ПОСЛЕ копий: копии снимаются с него, и своя коробка у
    # каждой уже проставлена.
    for name, card_type in stencils.items():
        declare_box(_installed_path(public, name, card_type),
                    name, OUT_W, OUT_H)

    # ── значки фоновых сцен ──────────────────────────────────────────────
    # Значок из их подбора лежит на подложке, за подложкой светит фирменный
    # акцент. Оба движения — их правила: вход `spring-pop-entrance` (scale
    # 0 -> 1 на power3.out, без отскока: «Bouncy back.out is the #1 instant
    # turn-off», rules/spring-pop-entrance.md:10) и `ambient-glow-bloom` —
    # свечение расцветает ПОД посадку плашки, «glow and hero resolve as ONE
    # beat» (rules/ambient-glow-bloom.md:14), а держится конечным дыханием
    # через прокси-фазу, а не yoyo-петлёй (там же:16).
    #
    # НЕ клип и без data-атрибутов — их же PiP-рецепт «wrapper без data»,
    # видимостью правит наш таймлайн. (Прежде тут стояло, что клип с `<img>`
    # роняет слой субтитров. Это оказалось не так: титры терялись из-за
    # порядка скриптов — captions.js шёл раньше gsap, см. templates/reel.html.
    # Обёртка остаётся простой потому, что у значка нет своей композиции.)
    for scene in scenes:
        found_icon = resolved.get(f'{scene["id"]}::icon') or {}
        # Поле `icon` снимаем всюду, где значок в кадр не встал: раскадровка на
        # диске обязана описывать собранный кадр, по ней судят гейты.
        if not found_icon.get("file"):
            scene.pop("icon", None)
            continue
        # Значок стоит в верхней трети по центру: при ведущей во весь кадр или
        # в верхней половине это её лицо. Раскладка сцены могла смениться уже
        # после подбора (`settle_inserts` переводит сцену без вставки на
        # полнокадровую ведущую), поэтому решает геометрия здесь, а не заявка.
        if not icon_fits(str(scene.get("presenter") or "none")):
            print(f'{scene["id"]}: значок снят — ведущая '
                  f'{scene.get("presenter")!r} занимает его место в кадре')
            scene.pop("icon", None)
            continue
        # Значок — ЗАПАС, и ведёт себя как запас: приехала вставка — значка
        # нет. Прежде он стоял безусловно, и в боевом ролике круглая плашка с
        # тарелкой легла поверх руки со сковородой — два раза про одно и то же
        # в одном кадре. Кадр от этого не пустеет: `hf_montage.frame_filler`
        # называет такую сцену вставкой, а не значком, — счёт гейтов D20/D25
        # не меняется. Судим по собранной серии, а не по полю `insert`:
        # именно она решает, что зритель увидит.
        if series.get(scene["id"]):
            print(f'{scene["id"]}: значок снят — вставка приехала, '
                  "а значок ей запас, а не довесок")
            scene.pop("icon", None)
            continue
        start = _q(scene["startSec"])
        end = _q(scene["endSec"])
        name = f'icon-{scene["id"]}'
        body.append(
            f'    <div id="{name}" class="icon-spot">'
            f'<div id="{name}-glow" class="icon-glow"></div>'
            f'<div id="{name}-plate" class="icon-plate">'
            f'<img src="{found_icon["file"]}" alt=""></div></div>')
        spot, glow = _js(f"#{name}"), _js(f"#{name}-glow")
        plate = _js(f"#{name}-plate")
        # Свечение стартует раньше плашки ровно на свою длительность, чтобы
        # оба доехали в один такт.
        bloom = round(min(ICON_BLOOM, max(0.0, end - start)), 4)
        phase = f"phase_{scene['id'].replace('-', '_')}"
        breathe = max(0.0, end - start - bloom)
        cycles = max(1, int(breathe / 5.2))
        # Позиции твинов — через `markup_time`; длительности (`bloom`, дыхание)
        # остаются как есть, GSAP интерполирует непрерывно.
        at_start, at_end = markup_time(start), markup_time(end)
        timeline += [
            f'tl.set({spot}, {{ autoAlpha: 0 }}, 0);',
            f'tl.set({spot}, {{ autoAlpha: 1 }}, {at_start});',
            f'tl.fromTo({glow}, {{ opacity: 0, scale: 0.82 }}, '
            f'{{ opacity: {ICON_GLOW_PEAK}, scale: 1, duration: {bloom}, '
            f'ease: "power2.out" }}, {at_start});',
            f'tl.fromTo({plate}, {{ scale: 0, opacity: 0 }}, '
            f'{{ scale: 1, opacity: 1, duration: {bloom}, '
            f'ease: "power3.out" }}, {at_start});',
            f'tl.set({spot}, {{ autoAlpha: 0 }}, {at_end});']
        if breathe > 1.0:
            timeline += [
                f'const {phase} = {{ p: 0 }};',
                f'const {phase}_el = document.querySelector({glow});',
                f'tl.to({phase}, {{ p: {round(6.2832 * cycles, 4)}, '
                f'duration: {round(breathe, 4)}, ease: "none", onUpdate: '
                f'() => {{ const s = Math.sin({phase}.p); '
                f'{phase}_el.style.opacity = String({ICON_GLOW_PEAK} + s * 0.09); '
                f'{phase}_el.style.transform = `scale(${{1 + s * 0.05}})`; }} '
                f'}}, {markup_time(start + bloom)});']

    # ── схема ─────────────────────────────────────────────────────────────
    # То, что нельзя снять камерой: цифра, список шагов, связь двух понятий и
    # знак бренда. Каждую форму собирает их же блок, вписанный в вертикаль
    # (`hf_schema`); прежде здесь стоял одинокий значок на белом кружке, и в
    # кадре он читался эмблемой, а не сценой.
    #
    # Все схемы ролика лежат на одной дорожке: по времени они не пересекаются
    # (каждая занимает свою сцену целиком), а счёт плотности их линтера схему
    # не видит вовсе — маунт он пропускает (см. `TRACK_SCHEMA`).
    for scene in scenes:
        plan = schema_plan(scene)
        if not plan:
            continue
        start, end = _q(scene["startSec"]), _q(scene["endSec"])
        content = dict(plan)
        if plan["form"] == "brand":
            files = [(resolved.get(schema_key(scene["id"], index)) or {}).get("file")
                     for index in range(len(plan.get("brands") or []))]
            content["files"] = [f for f in files if f]
            if not content["files"]:
                print(f'{scene["id"]}: схема бренда снята — знак не подобрался')
                drop_schema(scenes, scene)
                continue
        block, config, css, patches = schema_build(
            plan["form"], content, duration=end - start, colors=colors)
        need = schema_min_seconds(plan["form"],
                                  len(content.get("files")
                                      or content.get("items")
                                      or content.get("rows")
                                      or content.get("nodes") or [1]))
        if end - start < need - 0.05:
            print(f'{scene["id"]}: схема «{plan["form"]}» снята — сцене '
                  f"{end - start:.1f} с, а форме нужно {need:.1f}")
            drop_schema(scenes, scene)
            continue
        elastic = schema_is_elastic(block)
        # Упругий блок раскладывается по коробке, а не по числам внутри себя:
        # во весь кадр он ставил третью карточку прямо под слова титра (их
        # `content_overlap` на `div.gca-label`, замер 1260..1292 при пороге
        # 980). Коробку обрезаем по той же черте, что держат остальные формы, —
        # и обрезаем её НА КОРНЕ БЛОКА: их загрузчик читает `data-height`
        # оттуда и ею же переписывает высоту хоста
        # (`compositionLoader.ts:516-524`), поэтому обрезанный хост сам по себе
        # распрямлялся обратно во весь кадр.
        height = SCHEMA_SAFE_BOTTOM if elastic else OUT_H
        unique, _, _ = _stage_overlay(
            public, block, scene["id"], sdk=None,
            port={"duration": end - start, "css": css, "patches": patches,
                  "elastic": elastic, "height": height,
                  "config": {} if elastic else config})
        # У упругого блока содержимое идёт штатным каналом на хост, а не
        # довеском к литералу: он читает `getVariables()`.
        values = (" data-variable-values='"
                  + json.dumps(config, ensure_ascii=False).replace("'", "&#39;")
                  + "'") if elastic else ""
        # ── живой фон под схемой ─────────────────────────────────────────
        # Корень схемы прозрачен у всех пяти блоков, а на схемной сцене под ним
        # нет ни ведущей, ни вставки: в кадре оставался ровный цвет из
        # frame.md. Фон ставит КОД — как титр и скрим под накладкой: агент о
        # нём не знает, средств в его таблице по-прежнему пять.
        #
        # НЕ клип и без `data-start`: их счётчик плотности дорожки считает
        # только элементы с `data-start` (rules/composition.ts:396), а гейт
        # пустого кадра — только идентификаторы из `FRAME_CONTENT_PREFIXES`.
        # Фон не должен попасть ни туда, ни туда.
        #
        # `data-layout-allow-overflow` — про выезд полей за края кадра: он и
        # есть их геометрия (`left:-18cqw`, `right:-28cqw`, `bottom:-34cqh` в
        # шаблоне), а `.aurora` этот выезд срезает своим `overflow:hidden`. Их
        # аудит раскладки видит ровно это — `container_overflow` на каждом
        # поле, — и сам называет выход: «mark intentional overflow with
        # data-layout-allow-overflow». Атрибут стоит на обёртке, а не на трёх
        # полях: отказ они ищут через `closest()`
        # (packages/cli/src/commands/layout-audit.browser.js:104-106). Тем же
        # атрибутом здесь помечены ведущая и вспышка — и по той же причине:
        # одиночную выборку аудит считает `info`, но две похожие сливает в
        # находку `warning`, а `check --strict` роняет сборку на любом
        # предупреждении.
        aurora = f'bg-aurora-{scene["id"]}'
        body.append(
            f'    <div id="{aurora}" class="aurora"'
            f' data-layout-allow-overflow="true">'
            f'<div class="ad-base"></div>'
            f'<div class="ad-blob ad-blob-a"></div>'
            f'<div class="ad-blob ad-blob-b"></div>'
            f'<div class="ad-blob ad-blob-c"></div>'
            f'<div class="ad-vignette"></div></div>')
        drift = f'aurora_{scene["id"].replace("-", "_")}'
        at_start, at_end = markup_time(start), markup_time(end)
        # Вне своей сцены фон снимается `display: none`, а не прозрачностью.
        # Каждый фон — пять полей с `filter: blur` и радиальными градиентами, и
        # у них про такие элементы записано: «Presence alone matters: opacity:0
        # and visibility:hidden overlays still contribute to the capture-layer
        # regression… The only escape hatch is `display: none`»
        # (packages/lint/src/rules/composition.ts:1186-1191). Порог их
        # предупреждения — 25 таких элементов, наблюдённый дефект — сплошной
        # чёрный кадр на первой половине рендера при сорока. Пять схемных сцен
        # дают ровно 25, так что `autoAlpha` (то есть `visibility:hidden`) нас
        # бы не спас. Заодно снятый фон не даёт аудиту раскладки выборок вне
        # своей сцены: невидимый элемент он не меряет (isVisibleElement,
        # layout-audit.browser.js:192-197).
        timeline += [
            f'tl.set({_js("#" + aurora)}, {{ display: "none" }}, 0);',
            f'tl.set({_js("#" + aurora)}, {{ display: "block" }}, {at_start});',
            f'const {drift} = {{ p: 0 }};',
            f'const {drift}_b = document.querySelectorAll('
            f'{_js("#" + aurora + " .ad-blob")});',
            f'const {drift}_paths = '
            + json.dumps([list(path) for path in AURORA_PATHS]) + ';',
            # Оборот замыкается ровно на 2π, и их же оговорка: на конце берём
            # литеральный ноль, иначе остаётся мусор с плавающей точки.
            f'tl.to({drift}, {{ p: {AURORA_CYCLE}, '
            f'duration: {round(at_end - at_start, 4)}, ease: "none", '
            f'onUpdate: () => {{ const f = {drift}.p === {AURORA_CYCLE} '
            f'? 0 : {drift}.p; {drift}_paths.forEach((path, i) => '
            f'window.gsap.set({drift}_b[i], {{ '
            f'x: Math.sin(f + path[0]) * path[1] + "cqw", '
            f'y: Math.sin(f + path[0] + Math.PI / 2) * path[2] + "cqh" }})); '
            f'}} }}, {at_start});',
            f'tl.set({_js("#" + aurora)}, {{ display: "none" }}, {at_end});']
        body.append(
            f'    <div class="ovl">'
            f'<div id="schema-{scene["id"]}" class="clip"'
            f' data-composition-id="{unique}"'
            f' data-composition-src="compositions/{unique}.html"'
            f' data-start="{markup_time(start):.4f}"'
            f' data-duration="{markup_time(end) - markup_time(start):.4f}"'
            f' data-track-index="{TRACK_SCHEMA}"'
            f' data-width="{OUT_W}" data-height="{height}"'
            f' style="position:absolute;left:0;top:0;'
            f'width:{OUT_W}px;height:{height}px"{values}></div></div>')
        scene["schemaShown"] = True

    # ── ведущая ───────────────────────────────────────────────────────────
    # `class="clip"` на `<video>` их линтер не требует — теги `video`/`audio` он
    # из проверки исключает (packages/lint/src/rules/composition.ts:548), а одна
    # страница доков его прямо запрещает (docs/reference/html-schema.mdx:92).
    # Но их же справочник ставит его в примере (variables-and-media.md:74), а у
    # нас без него клип в кадре не появлялся вовсе: окно на месте, внутри пусто.
    # Оставляем — проверено кадрами.
    #
    # `data-layout-allow-overflow` — про наезд камеры. Клип масштабируется
    # внутри `#video-wrap` с `overflow:hidden`, то есть выезд за окно и есть
    # наезд: лишнее срезает обёртка. Их аудит раскладки видит это как
    # `container_overflow` и сам подсказывает выход — «mark intentional
    # overflow with data-layout-allow-overflow». Одиночную выборку он считает
    # `info`, но две похожие сливает в одну находку и поднимает до `warning`, а
    # `check --strict` роняет сборку на любом предупреждении: прогоны 37 и 38
    # встали именно так, при том что на 30 и 31 та же геометрия прошла как
    # `info`. Тем же атрибутом здесь же помечена вспышка (ниже по файлу).
    # Длительность НЕ квантуем в одиночку: в clips.json она уже разность
    # квантованных времён (`hf_render.py:353`), и своя обработка разности и
    # есть та ошибка в миллисекунду, что сдвигает конец клипа с сетки кадров.
    # В разметку она идёт парно — `markup_time(конец) - markup_time(начало)`.
    tags = []
    for index, clip in enumerate(clips):
        begin = markup_time(clip["start"])
        finish = markup_time(_q(clip["start"]) + float(clip["duration"]))
        tags.append(
            f'      <video class="clip" id="clip-{index:02d}"'
            f' src="{clip["file"]}"'
            f' muted playsinline data-layout-allow-overflow="true"'
            f' data-start="{begin:.4f}"'
            f' data-duration="{finish - begin:.4f}"'
            f' data-track-index="{TRACK_VIDEO}"></video>')
    videos = "\n".join(tags)
    # Клипы ведущей лежат встык на одной дорожке. Наезд соседей их линт
    # видит как `overlapping_clips_same_track` и роняет `check --strict`
    # (допуск 1e-6), а зазор съедает целый кадр: окно видимости у них
    # полуоткрытое, без допуска. Ловим у себя и называем виновных, а не
    # ждём чужого отчёта.
    # Судим по исходным числам, а не по напечатанным: `markup_time` монотонна,
    # поэтому если не наезжают сырые, то не наезжают и напечатанные, — а на
    # сырых виден и наезд короче полукадра, который округление съело бы в ноль.
    for index in range(1, len(clips)):
        before, after = clips[index - 1], clips[index]
        finish = _q(before["start"]) + float(before["duration"])
        begin = _q(after["start"])
        if finish > begin + 1e-6:
            raise RuntimeError(
                f"клипы ведущей на дорожке {TRACK_VIDEO} наезжают друг на "
                f"друга: clip-{index - 1:02d} кончается на {finish:.4f} с, "
                f"а clip-{index:02d} начинается раньше — на {begin:.4f} с")
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

    plans = camera_plans(moments, words, duration, face=face)
    timeline += _zoom_timeline(plans)
    origin = zoom_origin(face)

    # ── вспышки ───────────────────────────────────────────────────────────
    # Их накладка целиком: прозрачная сабкомпозиция 1920x1080, вписанная в
    # вертикальный кадр обёрткой с transform — их загрузчик жёстко ставит
    # хосту пиксели канваса блока (compositionLoader.ts:517-524), поэтому
    # масштаб может нести только обёртка вокруг клипа.
    #
    # Мест два, не больше: вспышка живёт на «выдохе» — возврате масштаба к
    # 100 % после крупного плана, и кульминация, названную агентом, идёт
    # первой. Правило и предел — Юлины (`hf_montage.flash_moments`).
    climax = next((_q(scene["startSec"]) for scene in scenes
                   if _beat(scene) == "climax"), None)
    flashes = flash_moments(plans, climax=climax, duration=duration)
    # Что из задуманного реально встало в разметку. Пишется в `camera.json`
    # вместо `flashes`: гейт `D26_flash` (`hf_zoom.py`) идёт мерить яркость по
    # этому списку, и обещание вспышки, которой в разметке нет, роняло приёмку
    # впустую — прогон 3ecf2289 обещал 1.974 и 45.533, а в кадре стоял один
    # `fx-1`.
    staged: list[float] = []
    for order, hit in enumerate(flashes):
        flash_start = round(hit - FLASH_HIT * FLASH_NATIVE, 4)
        flash_length = min(FLASH_NATIVE, duration - flash_start)
        if flash_start < 0 or flash_length < FLASH_HIT * FLASH_NATIVE + 0.2:
            # Пропуск больше не молчит: раньше вспышка исчезала без следа, и
            # разойтись список с разметкой мог незаметно. Подрезать разгон
            # блока здесь нечем — это отдельная работа.
            print(f"вспышка на {hit:.2f} с снята — "
                  + (f"разгон блока {FLASH_HIT * FLASH_NATIVE:.2f} с не "
                     f"влезает в начало ролика"
                     if flash_start < 0 else
                     f"до конца ролика ({duration:.2f} с) не остаётся места "
                     f"на саму вспышку"))
            continue
        staged.append(hit)
        unique, _, _ = _stage_overlay(public, FLASH_BLOCK, f"fx{order}")
        # Единственное время мимо `markup_time`: на кадр стыка привязан не
        # старт вспышки, а её пик (`flash_start = hit - FLASH_HIT *
        # FLASH_NATIVE`), и любой сдвиг старта уводит пик со стыка.
        scale = OUT_H / 1080.0
        left = -round((1920 * scale - OUT_W) / 2)
        # Растянутый канвас блока шире кадра: обёртка режет его по краю, а
        # допуск переполнения снимает находку canvas_overflow их аудита.
        body.append(
            f'    <div class="fx"><div data-layout-allow-overflow="true"'
            f' style="position:absolute;'
            f'left:{left}px;top:0;transform:scale({scale:.4f});'
            f'transform-origin:0 0">'
            f'<div id="fx-{order}" class="clip"'
            f' data-layout-allow-overflow="true"'
            f' data-composition-id="{unique}"'
            f' data-composition-src="compositions/{unique}.html"'
            f' data-start="{flash_start:.4f}"'
            f' data-duration="{flash_length:.4f}"'
            f' data-track-index="{TRACK_FX + order}"'
            f' data-width="1920" data-height="1080"></div></div></div>')
        if sfx_whoosh:
            body.append(
                f'    <audio id="sfx-{order}" src="{sfx_whoosh}"'
                f' data-start="{max(0.0, hit - 0.15):.4f}"'
                f' data-duration="0.6" data-track-index="{TRACK_SFX}"'
                f' data-volume="0.5"></audio>')

    # Планы камеры и моменты вспышек уезжают на диск: после рендера их меряют
    # по готовому файлу. Правило Юли — «зум проверять числами, а не глазами:
    # спикер сам наклоняется к камере, и на стоп-кадрах это читается как
    # наезд» (broll-zoom-toolkit/README.md, грабля 2).
    #
    # Пишется ПОСЛЕ разметки и только тем, что в неё встало: файл — отчёт о
    # сделанном, а не замысел.
    (Path(rdir) / "camera.json").write_text(
        json.dumps({"origin": origin, "plans": plans, "flash": staged},
                   ensure_ascii=False, indent=1), encoding="utf-8")

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
                        # Корневая длительность идёт мимо `markup_time`: она не
                        # время на шкале, а число кадров ролика, и по нему же
                        # их сборка режет звук (`frameCount/fps`). Запас вверх
                        # даёт лишний пустой кадр, нехватка — отрезанный хвост
                        # живой речи; берём запас.
                        ("__DURATION__", f"{duration:.4f}"),
                        ("__BG__", colors["bg"]),
                        ("__INK__", colors["ink"]),
                        ("__ORIGIN__", zoom_origin(face)),
                        ("__FIT__", crop_position(face)),
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
    """Убрать блоки прошлой попытки: и копии под сцены, и сами установленные.

    Копии — потому что их имя зависит от сцены, а сцены переписаны. Сами блоки —
    потому что неудачная установка оставляет блок наполовину: прогон 28 потерял
    попытку на `hyperframes add instagram-follow` (нет `assets/avatar.jpg`), и
    осиротевший HTML доехал до второй попытки, где его нашёл уже их `check` —
    `missing_local_asset` плюс полтора десятка предупреждений о селекторах
    блока, которого в плане не было вовсе. Нужные блоки сборка ставит заново
    сама, это секунды.

    Компоненты (`compositions/components/`) не трогаем: субтитры ставятся один
    раз на прогон и от плана не зависят.
    """
    compositions = public / "compositions"
    if not compositions.exists():
        return
    for path in compositions.glob("*.html"):
        path.unlink()
