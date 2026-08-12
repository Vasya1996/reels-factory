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
import re
import shutil
from pathlib import Path

from reels_factory.config import FPS, OUT_H, OUT_W
from reels_factory.hf_captions import caption_snippet, write_caption_data
from reels_factory.hf_frame import DEFAULTS as FRAME_DEFAULTS
from reels_factory.hf_layout import (
    VIDEO_RECTS, avatar_gaps, icon_fits, in_avatar_gap, insert_rect, quantize,
)
from reels_factory.hf_media import insert_problem
from reels_factory.hf_montage import (
    cut_into_plans, flash_moments, insert_of, refill_scene, shot_queries,
    shots_for, split_series, zoom_ladder,
)
from reels_factory.hf_schema import (
    FORMS, SAFE_BOTTOM as SCHEMA_SAFE_BOTTOM, build as schema_build,
    is_elastic as schema_is_elastic, min_seconds as schema_min_seconds,
    port_block,
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

#: Дорожка схем. Отдельная от накладок: схема занимает кадр целиком и с
#: плашкой в одной сцене не встречается, а на одной дорожке клипы пересекаться
#: не могут — их линтер зовёт это `overlapping_clips_same_track`.
TRACK_SCHEMA = 30

#: Дорожка слоя читаемости под накладкой без своей подложки.
TRACK_SCRIM = 38

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
        icon = scene.get("icon")
        if (isinstance(icon, dict) and str(icon.get("query") or "").strip()
                and icon_fits(str(scene.get("presenter") or "none"))):
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

_CANVAS = re.compile(
    r'data-composition-id="[^"]+"[^>]*data-width="(\d+)"[^>]*'
    r'data-height="(\d+)"', re.S)
_NATIVE = re.compile(
    r'data-composition-id="[^"]+"[^>]*data-duration="([\d.]+)"', re.S)


def _stage_overlay(public, block: str, scene_id: str, *, sdk=None,
                   text: dict | None = None,
                   port: dict | None = None) -> tuple[str, float, tuple]:
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
    # Ключ таймлайна не всегда стоит в самой скобке: их компоненты кладут его в
    # переменную (`var compositionId = "grid-card-assemble"`), и без этой
    # замены обе копии регистрировались под одним именем — вторая затирала
    # первую, первая не рисовалась вовсе, а рендер ждал по 45 с на каждого
    # рабочего и отдавал `sub_timeline_readiness_timeout`. Проверено кадром:
    # убери второй хост — первый оживает.
    html = html.replace(f'= "{block}"', f'= "{unique}"')
    # GSAP блока — плоским именем и ДВУМЯ копиями: их резолверы расходятся
    # (рендер идёт от файла блока, живая проверка — от корня проекта,
    # invalid_parent_traversal_in_asset_path это прямо говорит), а путь через
    # ../ запрещён их линтером. Копия рядом с блоком кормит рендер, копия в
    # корне — живой runtime-чек (без неё он давал 404 и блок оставался без
    # анимации — прогон 23).
    original = Path(public) / "vendor" / "gsap.min.js"
    for target_dir in (source.parent, Path(public)):
        vendored = target_dir / "gsap-vendor.min.js"
        if not vendored.exists() and original.exists():
            shutil.copyfile(original, vendored)
    html = _CDN_GSAP.sub('src="gsap-vendor.min.js"', html)
    html = _CDN_FONTS.sub("", html)
    html = _FONT_FAMILY.sub(_OUR_STACK, html)
    if text:
        html = prune_timeline(html)
    # Блок схемы приезжает нарисованным под ландшафт и с их содержимым: канвас,
    # длительность, содержимое и палитру подставляем здесь же, до записи копии.
    # Порядок важен — `prune_timeline` вырезает строки с шестнадцатеричным
    # кодом, приняв их за мёртвый селектор, а палитра идёт правилом CSS.
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
                 duration: float) -> list[dict]:
    """Планы камеры на всё аватарное время, со ступенями масштаба.

    Куски с ведущей режутся на планы по паузам речи (`hf_montage`), и каждому
    плану достаётся ступень: соседние отличаются не меньше чем на 8 %, наезд —
    не чаще каждого третьего плана и только там, где окно большое.
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
        plans += [dict(plan, position=position)
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
        at = _q(plan["start"])
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
        reason = _skipped_blocks().get(str(block))
        if reason:
            print(f'{scene["id"]}: накладка {block} снята — {reason}')
            scene.pop("overlay", None)
            continue
        marked.append(scene)
    staged_overlays = 0
    for position, scene in enumerate(marked):
        overlay = scene["overlay"]
        start = _q(scene["startSec"])
        room = duration - start
        if position + 1 < len(marked):
            room = min(room, _q(marked[position + 1]["startSec"]) - start)
        unique, native, canvas = _stage_overlay(
            public, str(overlay["block"]), scene["id"], sdk=sdk,
            text={k: str(v) for k, v in (overlay.get("text") or {}).items()})
        length = round(min(native, room), 4)
        if length < min_card_seconds(native):
            if position + 1 < len(marked) and room < duration - start:
                print(f'{scene["id"]}: накладка {overlay["block"]} снята — до '
                      f"следующей плашки {room:.2f} с, а ей нужно "
                      f"{min_card_seconds(native):g}")
                scene.pop("overlay", None)
                continue
            raise RuntimeError(
                f'{scene["id"]}: накладке {overlay["block"]} нужно '
                f"{min_card_seconds(native):g} с, а до конца ролика "
                f"{duration - start:.2f} — поставь её раньше или возьми короче")
        # Фактура кроет кадр целиком, плашка стоит полосой над титром. Обе
        # приезжают канвасом 1920x1080, и различить их можно только по метке
        # каталога — той же, которой помечены их собственные обработки кадра.
        if str(overlay["block"]) in _texture_blocks():
            scale = OUT_H / canvas[1]
            box = f"left:{-round((canvas[0] * scale - OUT_W) / 2)}px;top:0"
        elif canvas[0] > canvas[1]:
            scale = OUT_W / canvas[0]
            box = f"left:0;top:{_overlay_wide_top(canvas[1] * scale)}px"
        else:
            scale = OUT_W / canvas[0]
            box = "left:0;top:0"
        # Накладке без своей подложки нужен слой читаемости: их проверка
        # контраста меряет пиксели под буквами, а `text-shadow` не
        # засчитывает — на светлом биролле белый текст проваливается. Градиент
        # их же: «Glass without legibility gradient = white-on-white
        # catastrophe over bright video. Always pair them»
        # (talking-head-recut/references/layouts/overlay.html:52-68).
        if _block_backing().get(str(overlay["block"])) == "none" \
                and insert_of(scene):
            body.append(
                f'    <div class="ovl-scrim" id="scrim-{scene["id"]}"'
                f' data-start="{start:.4f}" data-duration="{length:.4f}"'
                f' data-track-index="{TRACK_SCRIM}"></div>')
        body.append(
            f'    <div class="ovl" style="{box}">'
            f'<div data-layout-allow-overflow="true" style="position:absolute;'
            f'left:0;top:0;transform:scale({scale:.4f});transform-origin:0 0">'
            f'<div id="ovl-{scene["id"]}" class="clip"'
            f' data-layout-allow-overflow="true"'
            f' data-composition-id="{unique}"'
            f' data-composition-src="compositions/{unique}.html"'
            f' data-start="{start:.4f}" data-duration="{length:.4f}"'
            f' data-track-index="{TRACK_OVERLAY + staged_overlays % 2}"'
            f' data-width="{canvas[0]}" data-height="{canvas[1]}"></div>'
            f"</div></div>")
        staged_overlays += 1

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
        timeline += [
            f'tl.set({spot}, {{ autoAlpha: 0 }}, 0);',
            f'tl.set({spot}, {{ autoAlpha: 1 }}, {start});',
            f'tl.fromTo({glow}, {{ opacity: 0, scale: 0.82 }}, '
            f'{{ opacity: {ICON_GLOW_PEAK}, scale: 1, duration: {bloom}, '
            f'ease: "power2.out" }}, {start});',
            f'tl.fromTo({plate}, {{ scale: 0, opacity: 0 }}, '
            f'{{ scale: 1, opacity: 1, duration: {bloom}, '
            f'ease: "power3.out" }}, {start});',
            f'tl.set({spot}, {{ autoAlpha: 0 }}, {end});']
        if breathe > 1.0:
            timeline += [
                f'const {phase} = {{ p: 0 }};',
                f'const {phase}_el = document.querySelector({glow});',
                f'tl.to({phase}, {{ p: {round(6.2832 * cycles, 4)}, '
                f'duration: {round(breathe, 4)}, ease: "none", onUpdate: '
                f'() => {{ const s = Math.sin({phase}.p); '
                f'{phase}_el.style.opacity = String({ICON_GLOW_PEAK} + s * 0.09); '
                f'{phase}_el.style.transform = `scale(${{1 + s * 0.05}})`; }} '
                f'}}, {round(start + bloom, 4)});']

    # ── схема ─────────────────────────────────────────────────────────────
    # То, что нельзя снять камерой: цифра, список шагов, связь двух понятий и
    # знак бренда. Каждую форму собирает их же блок, вписанный в вертикаль
    # (`hf_schema`); прежде здесь стоял одинокий значок на белом кружке, и в
    # кадре он читался эмблемой, а не сценой.
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
        body.append(
            f'    <div class="ovl">'
            f'<div id="schema-{scene["id"]}" class="clip"'
            f' data-composition-id="{unique}"'
            f' data-composition-src="compositions/{unique}.html"'
            f' data-start="{start:.4f}" data-duration="{end - start:.4f}"'
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
    videos = "\n".join(
        f'      <video class="clip" id="clip-{index:02d}" src="{clip["file"]}"'
        f' muted playsinline data-layout-allow-overflow="true"'
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

    plans = camera_plans(moments, words, duration)
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
    # Планы камеры и моменты вспышек уезжают на диск: после рендера их меряют
    # по готовому файлу. Правило Юли — «зум проверять числами, а не глазами:
    # спикер сам наклоняется к камере, и на стоп-кадрах это читается как
    # наезд» (broll-zoom-toolkit/README.md, грабля 2).
    (Path(rdir) / "camera.json").write_text(
        json.dumps({"origin": origin, "plans": plans, "flash": flashes},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    for order, hit in enumerate(flashes):
        flash_start = round(hit - FLASH_HIT * FLASH_NATIVE, 4)
        flash_length = min(FLASH_NATIVE, duration - flash_start)
        if flash_start < 0 or flash_length < FLASH_HIT * FLASH_NATIVE + 0.2:
            continue
        unique, _, _ = _stage_overlay(public, FLASH_BLOCK, f"fx{order}")
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
