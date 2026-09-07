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
import subprocess
from pathlib import Path

from reels_factory.config import FPS, OUT_H, OUT_W
from reels_factory.hf_captions import caption_snippet, write_caption_data
from reels_factory.hf_frame import DEFAULTS as FRAME_DEFAULTS, highlight_ink
from reels_factory.hf_layout import (
    FULL_FRAME_PRESENTER, VIDEO_RECTS, avatar_gaps, effect_rect, icon_fits,
    in_avatar_gap, insert_rect, quantize,
)
from reels_factory.hf_media import insert_problem
from reels_factory.hf_montage import (
    PUSH_TO, cut_into_plans, drop_schema, flash_moments, insert_of,
    refill_scene, scene_elements, shot_queries,
    shots_for, split_series, zoom_ladder,
)
from reels_factory.hf_schema import (
    FORMS, SAFE_BOTTOM as SCHEMA_SAFE_BOTTOM, build as schema_build,
    is_elastic as schema_is_elastic, min_seconds as schema_min_seconds,
    frame_variables, overlay_css, palette_css, port_block,
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

#: Первая дорожка слоя читаемости под коробкой схемы, когда под ней лежит
#: настоящая вставка (сток, непредсказуемый по цвету), а не наш управляемый
#: фон (aurora). Тот же `.ovl-scrim`, что у накладок без своей подложки
#: (`TRACK_SCRIM`), но своя полоса дорожек: скрим — обычный `div` с
#: `data-start`, не маунт, и в отличие от самой коробки схемы (маунт,
#: `TRACK_SCHEMA` без ротации — их счётчик плотности маунты пропускает) он
#: ПОПАДАЕТ под `timeline_track_too_dense`, даже когда сами схемные сцены не
#: перекрываются по времени: их линтер считает элементы на дорожке количеством,
#: не пересечением (тот же довод, что у `TRACK_SCRIM` ниже). Полоса 20..28:
#: ниже вставок (`TRACK_INSERT`=3) и схемы (30), свободна.
TRACK_SCHEMA_SCRIM = 20

#: Сколько дорожек схемной полосы резервировать под фактическое число схемных
#: сцен с настоящей вставкой — считается один раз до цикла схемы, тем же
#: приёмом и с тем же запасом, что у `scrim_tracks` накладок ниже.
SCHEMA_SCRIMS_PER_TRACK = INSERTS_PER_TRACK

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
#: y=1127 при двух строках, прогон 23). Плашка любого канваса вписывается по
#: ширине кадра и ставится так, чтобы весь её бокс кончался выше
#: foregroundMaxY: на прежних 640 нижняя треть блока ложилась прямо на слова
#: титра (content_overlap #lt-name против span.hl-word-text). Раньше
#: вертикальная накладка (1080x1920) из этого правила была исключена и
#: вставала во весь кадр как есть — при таком канвасе высота после масштаба
#: по ширине (1920px) сама равна высоте кадра, отступа над полосой не
#: остаётся вовсе, и плашка ложится прямо на слова титра
#: (`spotify-card` #track-name, `content_overlap`, прогон каталога
#: 06.09.2026). Правило теперь одно на оба канваса: не умещается высота —
#: масштаб уменьшается ещё, пока весь бокс не встанет выше полосы, лишнее
#: по ширине уходит в поля по бокам (`_overlay_geometry`).
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


#: Во сколько раз схему можно ужать, оставив её читаемой. Порог — ДОЛЯ от
#: собственного кегля, а не пиксель: пиксельный пол схему завернул бы и без
#: всякого ужатия (у перечисления подпись и так `min(2.6cqw, …)` — 28 px в
#: нашем кадре, `grid-card-assemble.html:376-379`), а вопрос стоит другой —
#: насколько ниже СВОЕГО размера буквам можно опуститься.
#:
#: Долю берём не с потолка и не свою: ровно так ужимает слово титра его же
#: движок — `var minSize = Math.floor(baseFontSize * 0.45)`
#: (`assets/caption-highlight.html:134`), и ниже не идёт «rather than
#: shrinking below legibility» (там же:135-137); при базовом кегле 80 px в
#: нашем кадре (`:401`, `fontScale = min(W, H) / 1080 = 1`, `:276`) это его
#: пол в 36 px. У них самих та же доля чуть строже — 42 из 78
#: (`packages/core/src/text/fitTextFontSize.ts:27-28`). Схема сверстана на
#: полосу `SAFE_BOTTOM`, значит её доля — доля этой полосы.
SCHEMA_MIN_SCALE = 0.45


def schema_zone(presenter: str, *, face: dict | None = None,
                min_height: int | None = None) -> dict | None:
    """Куда встаёт схема при этом положении ведущей и во сколько раз ужимается.

    `{"top", "height", "scale"}` либо `None` — места нет, и схема в такую
    сцену не встаёт.

    До этой функции геометрию схемы считал один `hf_schema.build`, и он не
    знал о ведущей ничего: ни её окна, ни лица. Пять форм центровались в
    полосе `0..SAFE_BOTTOM` и ложились туда же, где при `punch` находится
    лицо — прогон `rb0907-philosophers`, сцена `s-08`, карточка бренда на
    лице ведущей. Знает об этом компоновщик: окно ведущей ставит он
    (`_presenter_move`), наезд считает он же (`camera_plans`), лицо меряет
    `face_detect`. Теперь он это и говорит — одной зоной, тем же
    `hf_layout.effect_rect`, которым в кадр встаёт элемент-эффект.

    `scale` — во сколько раз ужать коробку схемы, чтобы её содержимое (оно
    сверстано на полосу `SCHEMA_SAFE_BOTTOM`) уместилось в зону. Единица —
    зона целая, и разметка выходит знак в знак прежней: так стоят схемы при
    `none` и при нижних уголках, где окно ведущей лежит ниже полосы титра и
    со схемой не спорит вовсе.

    Наезд входит в счёт: при полнокадровой ведущей камера растёт до
    `PUSH_TO` вокруг точки лица (`zoom_origin` целится в неё же), то есть
    голова к концу наезда крупнее ровно во столько же. Это не мелочь, а сам
    дефект: на 27,65 с карточка `s-08` стояла НАД лицом и кадр читался, а на
    28,43 с наезд поднял лицо в неё (`contact-sheet-3.jpg`, кадры 4 и 5).
    Гейт обязан судить худший кадр сцены, а не первый.

    `min_height` — пол зоны; по умолчанию читаемый (`SCHEMA_MIN_SCALE`).
    Ноль спрашивает отказавший гейт, когда ему нужно назвать в тексте, СКОЛЬКО
    места осталось: иначе он мерил бы полосу вторым счётом.
    """
    name = str(presenter or "none")
    if face and name in FULL_FRAME_PRESENTER:
        face = dict(face, h=float(face["h"]) * PUSH_TO)
    if min_height is None:
        min_height = round(SCHEMA_MIN_SCALE * SCHEMA_SAFE_BOTTOM)
    rect = effect_rect(name, band_top=CAPTION_BAND_TOP - CAPTION_BAND_SAFETY,
                       face=face, fit=crop_fractions(face),
                       min_height=min_height)
    if rect is None:
        return None
    return {"top": rect["top"], "height": rect["height"],
            "scale": round(min(1.0, rect["height"] / SCHEMA_SAFE_BOTTOM), 4)}


#: Их «portrait glass card» — плашка, которую их же скил talking-head-recut
#: рисует для вертикального порта («portrait glass card, bottom band»,
#: `references/layouts/overlay.html:38-43`): width 1032 из 1080, левое поле
#: 24px (1032 + 2*24 = 1080). Берём эту долю целью для НАРИСОВАННОГО —
#: landscape-плашка каталога должна занимать в кадре примерно ту же долю
#: ширины, что и их собственная вертикальная карточка, а не долю, оставшуюся
#: случайно от масштаба по канвасу (см. докстринг `_overlay_geometry`).
OVERLAY_CONTENT_MARGIN = 24

#: Пол масштаба, ниже которого плашка нечитаема. Порог не свой: то же число и
#: то же основание, каким уже ужимается схема (`SCHEMA_MIN_SCALE`) и каким их
#: собственный движок титра не даёт словам сжаться меньше 45% базового кегля
#: (`caption-highlight.html:134-137`, цитата и разбор — см. `SCHEMA_MIN_SCALE`
#: выше). Здесь база — родной размер самой плашки (scale=1), а не полоса
#: схемы: `scale` ниже этого порога значит, что плашка ужалась больше чем в
#: два раза от собственного кегля.
OVERLAY_MIN_SCALE = SCHEMA_MIN_SCALE


def _overlay_content_scale(canvas: tuple, band_height: float,
                           content_width: float | None) -> float:
    """Масштаб по ширине — либо по канвасу (как раньше), либо по нарисованному.

    Канвас 1920x1080 не значит, что нарисованное занимает всю его ширину:
    `lt-kicker-name` ставит кикер и имя блоком у левого края, и предыдущий
    расчёт (масштаб по ширине ЦЕЛОГО канваса) держал их такими же мелкими,
    какими они были бы, займи они всю ширину, — 70px кегль на 1080x1920 после
    масштаба 0,5625 давал 39px, 2% высоты кадра (задание, дефект `chat-el.png`
    соседний, `lt-kicker-name` — прогон rb0907-university, кадр 5). Зная
    ширину нарисованного, масштаб считается от НЕЁ: сколько нужно, чтобы
    нарисованное заняло целевую долю кадра (`OVERLAY_CONTENT_MARGIN`), а не
    долю, оставшуюся случайно от пустых полей канваса.

    `content_width` не всегда есть (измеряет `_measured_overlay_content` —
    нужен браузер, а его может не быть на машине прогона): тогда — прежняя
    арифметика, масштаб по ширине канваса целиком, и поведение не меняется ни
    для одного из уже собранных прогонов.

    Итоговый масштаб не бывает МЕНЬШЕ масштаба по канвасу: у плашки, чьё
    нарисованное действительно занимает всю ширину (внутренний `max`
    ничего не меняет — целевая доля кадра (`OUT_W - 2*margin`) для такой
    плашки и так близка к масштабу по канвасу), это не меняет число вовсе.
    """
    scale = OUT_W / canvas[0]
    if content_width:
        target = OUT_W - 2 * OVERLAY_CONTENT_MARGIN
        scale = max(scale, target / float(content_width))
    if canvas[1] * scale > band_height:
        scale = band_height / canvas[1]
    return scale


def _overlay_geometry(block: str, canvas: tuple, *,
                      content_box: dict | None = None
                      ) -> tuple[float, str] | None:
    """Масштаб и место плашки в кадре по её канвасу и (если измерено) по её
    нарисованному содержимому.

    `None` — плашка нечитаема даже после подгонки под зону: снимается с
    причиной, как снимается позиция каталога (`OVERLAY_MIN_SCALE`).

    Фактура кроет кадр целиком, плашка стоит полосой над титром. Обе приезжают
    любым канвасом, и различить их можно только по метке каталога — той же,
    которой помечены их собственные обработки кадра.

    Одна арифметика на все канвасы, а не landscape/portrait разными ветками:
    сперва масштаб по ширине кадра (или по нарисованному — `_overlay_content_
    scale`), как у широкой плашки всегда. Если высота при таком масштабе не
    умещается в зону над полосой титра — масштаб уменьшается ещё, пока весь
    бокс не окажется выше неё; лишнее по ширине уходит в поля по бокам
    поровну. У широкой плашки (1920x1080) высота после масштаба по ширине и
    так меньше зоны — вторая поправка не срабатывает, и число совпадает с
    прежним (без измерения нарисованного). У портретной (1080x1920) высота
    после масштаба по ширине равна высоте кадра — без второй поправки отступа
    над полосой не остаётся вовсе, и плашка ложится прямо на слова титра;
    вторая поправка даёт ей ту же гарантию, что и широкой. Портретный канвас
    (уже вертикальный, как у самого кадра) измеренным содержимым не правим —
    он и так занимает свою ширину настоящей вёрсткой, а не пустым полем сбоку.

    Позиция нарисованного содержимого сдвигает и `left`: центрировать ЦЕЛЫЙ
    канвас, когда масштаб взят по нарисованному (а не по канвасу целиком),
    значит для контента, стоящего не по центру своего канваса (тот же
    `lt-kicker-name`, `left:130px` из 1920), унести его за край кадра — канвас
    после увеличенного масштаба заметно шире кадра, и центр канваса уже не
    там же, где контент. Вместо этого нарисованное ставится тем же полем
    слева, что и цель масштаба (`OVERLAY_CONTENT_MARGIN`) — тем самым полем,
    какое их собственная вертикальная карточка держит от края кадра.

    Одна арифметика на два места: по этому же правилу встаёт и позиция
    каталога, у которой вид в карточке не объявлен, — это сегодняшняя плашка,
    и вести себя она обязана так же.
    """
    if str(block) in _texture_blocks():
        scale = OUT_H / canvas[1]
        return scale, f"left:{-round((canvas[0] * scale - OUT_W) / 2)}px;top:0"
    band_height = CAPTION_BAND_TOP - CAPTION_BAND_SAFETY
    landscape = canvas[0] > canvas[1]
    content_width = (content_box or {}).get("width") if landscape else None
    scale = _overlay_content_scale(canvas, band_height, content_width)
    if scale < OVERLAY_MIN_SCALE:
        return None
    content_left = (content_box or {}).get("left") if landscape else None
    if content_width and content_left is not None:
        left = round(OVERLAY_CONTENT_MARGIN - float(content_left) * scale)
    else:
        left = round((OUT_W - canvas[0] * scale) / 2)
    top = _overlay_wide_top(canvas[1] * scale)
    return scale, f"left:{left}px;top:{top}px"


#: Скрипт замера лежит рядом с движком, как и скрипт пробы (`hf_probe.
#: PROBE_SCRIPT`); при editable-установке путь живой.
_MEASURE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / \
    "measure_block_content.cjs"


def _measured_content_box(path, canvas: tuple) -> dict | None:
    """Ширина нарисованного внутри уже заполненной копии позиции, на её
    родном канвасе — либо `None`, когда измерить нечем.

    Браузер здесь необязателен: нет `node`, нет закреплённого Chrome (тесты,
    чужая машина, сеть не подняла кэш `npx`) — измерение просто не состоялось,
    и `_overlay_geometry` считает по канвасу целиком, как считал до этой
    правки. Плашка не роняется тем, чего нет на машине сборки: измерение —
    улучшение читаемости там, где оно доступно, а не новое обязательное звено
    цепочки — но причина отступления идёт в лог, а не пропадает молча.

    Если же браузер есть, но само измерение сломалось (ненулевой
    `returncode` скрипта, битый JSON в его выводе) — это уже не «браузера
    нет», а регресс в `measure_block_content.cjs`/Chrome/копии позиции.
    Тихий откат на дефектную (без измерения) арифметику здесь вернул бы
    ровно тот дефект, который эта функция чинит, без следа в логе — поэтому
    дальше не `return None`, а `RuntimeError` со `stderr`, тем же приёмом,
    что `hf_probe.run_probe` при своём ненулевом `returncode`.
    """
    if canvas[0] <= canvas[1]:
        return None  # портретный канвас не измеряем — см. _overlay_geometry
    try:
        from reels_factory.hf_probe import _node, chrome_path
        from reels_factory.hyperframes_blocks import _HF_VERSION
    except ImportError as exc:
        print(f"{path}: замер содержимого пропущен — нет движка ({exc})")
        return None
    if not _MEASURE_SCRIPT.exists():
        print(f"{path}: замер содержимого пропущен — "
              f"нет скрипта {_MEASURE_SCRIPT}")
        return None
    try:
        node = _node()
        chrome = chrome_path(_HF_VERSION)
    except RuntimeError as exc:
        print(f"{path}: замер содержимого пропущен — {exc}")
        return None
    if not chrome:
        print(f"{path}: замер содержимого пропущен — Chrome не закреплён")
        return None
    try:
        result = subprocess.run(
            [node, str(_MEASURE_SCRIPT), "--file", str(path),
             "--width", str(canvas[0]), "--height", str(canvas[1]),
             "--chrome", chrome],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"{path}: замер содержимого пропущен — {exc}")
        return None
    if result.returncode != 0:
        raise RuntimeError(
            "замер содержимого не состоялся: "
            f"{(result.stderr or result.stdout or '').strip()[:800]}")
    try:
        box = json.loads((result.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError(
            "замер содержимого вернул не JSON "
            f"({exc}): {(result.stdout or '').strip()[:400]!r}, "
            f"stderr: {(result.stderr or '').strip()[:400]!r}")
    return box if isinstance(box, dict) else None


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
def _skipped_positions() -> dict:
    """Позиции каталога (блоки и компоненты), которые ставить нельзя, и
    причина. План мог назвать такую позицию раньше, чем она попала в этот
    список, — тогда снимаем её на сборке, а не роняем прогон: агент этого не
    исправит."""
    from reels_factory.hf_catalog import skipped_positions
    try:
        return dict(skipped_positions())
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


#: Класс перехода по их правилу выбора — beat-direction.md:64-70, три
#: столбца «shader / CSS / hard cut» по тому, ЧТО делает бит, не по тому,
#: ГДЕ он стоит. Наши пять битов — позиция в рассказе (`hf_montage_skill.py`,
#: «Ритм и биты»), а не тип содержимого, поэтому один в один на их три
#: класса не ложатся — решение по каждому и его основание:
#:
#: - `climax`, `outro` → `zoom-arrival`/`blur-crossfade` (их класс shader).
#:   Прямая цитата, не натяжка: «the hero reveal + the CTA» — их же пример
#:   типового бренд-ролика на 1-2 шейдерных перехода (beat-direction.md:70)
#:   называет ровно эти две позиции.
#:   Настоящий WebGL-шейдер (`@hyperframes/shader-transitions`) сюда не
#:   встаёт, и причина НЕ в асинхронности: в рендере их пакет сам уходит в
#:   отдельную синхронную ветку — `initEngineMode`
#:   (`packages/shader-transitions/src/hyper-shader.ts:886-892` включает её
#:   по `window.__HF_VIRTUAL_TIME__`, :2234-2240 прямо говорит «skip every
#:   GL/canvas/html2canvas branch»), то есть покадровой перемотке он не
#:   мешает. Причина в другом: их шейдерный переход — это подмена ВСЕГО
#:   КАДРА двумя сценами, а наш шов — стык двух планов внутри одной сцены,
#:   поверх которого продолжают идти ведущая и титр.
#:   Оба их пути рендера делают ровно это. Страничный (`--page-side-
#:   compositing`, по умолчанию включён): полнокадровый канвас
#:   `position:fixed; z-index:2147483646` поверх всего
#:   (`engineModePageComposite.ts:136-142`), а текстура каждой сцены — это
#:   `fillRect(bgColor)` на весь кадр плюс сама сцена (:344-350). Узловой
#:   (hf#677): сцены он ищет как `document.querySelectorAll(".scene")`
#:   (`captureHdrStage.ts:231-243`), на кадрах перехода прячет всё, чего нет
#:   в этих двух наборах (`captureHdrFrameShared.ts:237-240`, `hideIds`), и
#:   в выход пишет только смесь двух буферов
#:   (`captureHdrSequentialLoop.ts:135-190`). Третьего слоя ни там, ни там
#:   нет.
#:   У нас на этом шве в кадре ещё три постоянных слоя: окно ведущей
#:   `#video-wrap` (z 20), титр `#highlight` (z 30) и скрим под ним (z 25)
#:   — `templates/reel.html`; а сама вставка занимает не кадр, а
#:   прямоугольник `hf_layout.INSERT_RECTS` (при `stack` — нижние 1076 px).
#:   Проверено настоящим рендером, а не рассуждением: копия сборки
#:   `work/beat-transitions` со сценами на двух планах кульминации и их же
#:   `HyperShader.init({shader: "sdf-iris"})` на шве 31,5666
#:   (`work/shader-climax`, 06.09.2026). Шейдер отработал — чистая
#:   диафрагма со свечением, ни одного чёрного кадра, — но все 0,5 с
#:   перехода ведущей и титра в кадре НЕТ, а биролл растянут во весь кадр
#:   вместо своей нижней половины (кадры 946-954 в
#:   `work/shader-climax/frames`). Чтобы их путь подошёл, композицию
#:   пришлось бы перебрать в полнокадровые `.scene`, а ведущую и титр
#:   продублировать внутрь каждой — это отмена слоёвой модели кадра, а не
#:   подключение перехода.
#:   Взамен — их же честный, чисто-GSAP рецепт без канваса под ту же роль:
#:   `outro` уже стоял на блёр-гашении (их куратный список пяти переходов,
#:   `TRANSITION-REGISTRY.md:75`, назван там `blur-crossfade`); `climax`
#:   получает «Inverse Zoom-Through» (cut-catalog.md:81-113) — их же рецепт
#:   назван ровно под «arrival beats… a payoff line» (:88-91), то есть под
#:   кульминацию буквально, никакого нового пакета не требует.
#: - `point` → `cut-the-curve` (их класс CSS): «Beats that ease from one
#:   composition into the next… Minimal/editorial pacing» — обычная точка
#:   рассказа, таких большинство, ничего не меняем.
#: - `turn` → `cut-the-curve`, тоже CSS, а НЕ shader, хотя их формулировка
#:   «energy shifts» в столбце shader звучит похоже на смену главы. Причина
#:   не брать: turn может стоять один-три раза за ролик
#:   (`hf_montage_skill.py`), а их же лимит на весь ролик — «1-2 shader
#:   transitions… too many flatten their impact» (:70), уже израсходован
#:   climax'ом и outro. Класс держим прежним, вертикальную ось — тоже: она
#:   и была придумана как маркер смены главы внутри CSS-семьи, не как заявка
#:   на шейдер.
#: - `hook` → `hard-cut`. У hook нет входа вовсе (первая сцена), решение
#:   касается только его выхода. Их таблица называет rapid-fire/percussive
#:   контент, а не позицию «открытие», так что буквального попадания нет;
#:   решение опирается на их же ограничение по длительности — «Anytime a
#:   0.3-0.8s transition would feel too slow» (:68) — открытие обязано
#:   отдать кадр сути без разгона на eased-стыке. Раньше hook получал ту же
#:   `cut-the-curve`, что и все точки; отличие внесено этой правкой.
_TRANSITION_CLASS = {
    "hook": "hard-cut",
    "point": "cut-the-curve",
    "turn": "cut-the-curve",
    "climax": "zoom-arrival",
    "outro": "blur-crossfade",
}


def _transition_class(beat: str) -> str:
    """Класс перехода по биту — словарь `_TRANSITION_CLASS`, см. его коммент."""
    return _TRANSITION_CLASS.get(beat, "cut-the-curve")


def _axis(beat: str) -> tuple[str, int]:
    """Ось стыка и знак направления движения — только для `cut-the-curve`.

    Обычные стыки едут влево — одно направление на весь ролик, глаз ведёт
    движение через границу (cut-the-curve: «Same path, same direction»).
    Смена главы (`turn`) — вертикальный вариант: зритель видит, что рассказ
    повернул.
    """
    return ("y", 1) if beat == "turn" else ("x", -1)


def _entry(target: str, beat: str, at: float) -> list[str]:
    """Вход вставки: класс перехода решает бит сцены (`_transition_class`).

    `fromTo`, не `from`: их правило — начальное состояние явно, иначе холодная
    перемотка рисует элемент до входа (transitions/overview.md:22).
    """
    # Позиция твина — время на шкале, значит через `markup_time`. Длительности
    # твинов оставлены как есть: GSAP интерполирует непрерывно.
    at = markup_time(at)
    cls = _transition_class(beat)
    if cls == "blur-crossfade":
        return [f'tl.fromTo({_js(target)}, {{ autoAlpha: 0, '
                f'filter: "blur(20px)" }}, {{ autoAlpha: 1, '
                f'filter: "blur(0px)", duration: 0.6, ease: "sine.inOut" }}, '
                f'{at});']
    if cls == "hard-cut":
        # Их же приём для percussive-стыков: «Hard cut / smash cut: instant»
        # (beat-direction.md:98) — мгновенный `tl.set`, без пути и без
        # гашения: разгонять открытие eased-твином — то, что их правило
        # прямо называет слишком медленным для этого случая.
        return [f'tl.set({_js(target)}, {{ autoAlpha: 1 }}, {at});']
    if cls == "zoom-arrival":
        # «Inverse Zoom-Through», фаза 3: элемент прилетает укрупнённым
        # из-за камеры и втягивается на место (cut-catalog.md:106-109) —
        # blur 20px, не их 10px: наши вставки — полнокадровый биролл, а не
        # текст, и «Full-frame surface… 18-20px» (cut-catalog.md:28-31).
        return [f'tl.fromTo({_js(target)}, {{ scale: 1.25, '
                f'filter: "blur(20px)", autoAlpha: 0.15 }}, '
                f'{{ scale: 1, filter: "blur(0px)", autoAlpha: 1, '
                f'duration: 0.5, ease: "expo.out" }}, {at});']
    axis, sign = _axis(beat)
    return [f'tl.fromTo({_js(target)}, {{ {axis}: {-sign * CUT_TRAVEL}, '
            f'autoAlpha: 0.35 }}, {{ {axis}: 0, autoAlpha: 1, '
            f'duration: {CUT_SECONDS}, ease: "power4.out" }}, {at});']


def _exit(target: str, next_beat: str, at: float) -> list[str]:
    """Выход вставки: класс перехода решает бит сцены (`_transition_class`).

    Гашение короче пути (CUT_FADE < CUT_SECONDS): элемент исчезает, ещё
    разгоняясь, — «the exit's opacity completes at ~25-30% of its travel»
    (cut-catalog.md:145-149). Выход `power4.in` зеркален входу `power4.out`.
    """
    at = markup_time(at)
    cls = _transition_class(next_beat)
    if cls == "blur-crossfade":
        return [f'tl.to({_js(target)}, {{ autoAlpha: 0, duration: 0.5, '
                f'ease: "sine.inOut" }}, {at});']
    if cls == "hard-cut":
        return [f'tl.set({_js(target)}, {{ autoAlpha: 0 }}, {at});']
    if cls == "zoom-arrival":
        # «Inverse Zoom-Through», фаза 1: элемент отступает от камеры,
        # блюрится и гаснет отдельным линейным твином — «Opacity: 1.0 ->
        # 0.15 on none (separate tween)» (cut-catalog.md:97-98).
        return [
            f'tl.to({_js(target)}, {{ scale: 0.8, filter: "blur(20px)", '
            f'duration: 0.2, ease: "power3.in" }}, {at});',
            f'tl.to({_js(target)}, {{ autoAlpha: 0, duration: 0.2, '
            f'ease: "none" }}, {at});']
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

#: Скрипт позиции целиком. Гарнитуру в нём НЕ подменяем: там `font-family`
#: живёт внутри строки JavaScript, а наша замена несёт одинарные кавычки и
#: рвёт её (`caption-camera-follow.html:236` — линейка ширины собирается
#: строкой `'font-family:"Helvetica Neue",…;font-weight:700;'`, после замены
#: строка закрывается на `'Manrope'`, и их же линтер даёт
#: `invalid_inline_script_syntax`: «Unexpected identifier 'Manrope'»,
#: воспроизведено настоящей сборкой 06.09.2026). Кириллице этот скрипт не
#: мешает: он меряет ширину, а рисует буквы всё равно CSS позиции, где замена
#: и нужна.
_SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>.*?</script>", re.I | re.S)
#: Обёртка `<script …>` и `</script>`: снимается, когда тело скрипта
#: уезжает в отдельный файл.
_SCRIPT_BODY = re.compile(r"<script[^>]*>|</script>", re.I)


def _restyle_fonts(html: str) -> str:
    """Наша гарнитура вместо гарнитуры позиции — везде, кроме её скриптов."""
    out: list[str] = []
    last = 0
    for match in _SCRIPT_BLOCK.finditer(html):
        out.append(_FONT_FAMILY.sub(_OUR_STACK, html[last:match.start()]))
        out.append(match.group(0))
        last = match.end()
    out.append(_FONT_FAMILY.sub(_OUR_STACK, html[last:]))
    return "".join(out)

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
                   media: dict | None = None,
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
    from reels_factory.hf_slots import fill_ops, prune_timeline, slot_contract

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
    if (text or words or media) and sdk is not None:
        from reels_factory.hf_slots import text_slot_names

        decor = decor_texts().get(block)
        # Какие у позиции слоты под файл — спрашиваем её собственную разметку
        # (`slot_contract`), а не список имён: позиция полки зовёт слот своим
        # именем (`before`, `card-a`, `subject`), и без разбора контракта файл
        # до неё не доезжал — в кадре оставался пустой макет.
        contract = slot_contract(fixed_stencil)
        sdk.open(unique, source)
        nodes = sdk.elements(unique)
        if words:
            text = dict(zip(text_slot_names(nodes, decor, contract),
                            [str(word) for word in words]))
        sdk.dispatch(unique, fill_ops(nodes, text=text, media=media,
                                      decor=decor, contract=contract))
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
    if not _REGISTRY_MARKER.match(html):
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
        #
        # Блоку маркер их `add` уже написал — но до нашей копии он не
        # доезжает: копия идёт через мост SDK (`sdk.open`/`sdk.save` выше), а
        # тот отдаёт разобранный документ, и комментарий ПЕРЕД `<!doctype
        # html>` теряется. Проверено настоящей сборкой 06.09.2026: первая
        # строка `compositions/message-thread-reveal--s-01.html` —
        # `<!DOCTYPE html>`, и их же `check --strict` даёт
        # `composition_file_too_large` пяти блокам каталога (ai-chat-reveal,
        # chatgpt-exchange, claude-exchange, message-thread-reveal,
        # notes-reveal), хотя на исходнике того же файла правило снято.
        # Поэтому условие не про вид карточки: восстанавливаем метку любому
        # файлу, который её потерял по дороге.
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
    html = _restyle_fonts(html)
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


#: Корневой элемент paste-контрактного примитива: без своего
#: `data-composition-id` и `<template>` — их полка велит вставлять разметку
#: литералом («Paste the markup, CSS and script into a composition»,
#: `registry/components/badge-pop/badge-pop.html:2`). Имя — первый токен
#: `class`, а если класса нет, то `id`: этим же именем скрипт компонента ищет
#: себя (`document.querySelectorAll(".hf-transition-badge-pop")`,
#: `#hf-vignette` в стиле `vignette`).
#:
#: Тег любой, не только `div`: у `icon-swap` корень — `<button
#: class="hf-transition-icon-swap">`, у `panel-reveal` — `<section
#: class="hf-transition-panel-reveal">`, а `vignette` и `grid-pixelate-wipe`
#: держат корень на `id` со `style` вместо класса. Прежнее правило («первый
#: `<div class="…">` файла») ни одну из этих четырёх позиций не находило, и
#: все четыре ушли в `reels.skip` с чужой причиной — «разметка не по
#: контракту полки» (прогон scratchpad/catalog-sweep 05.09.2026).
_PASTE_ROOT_TAG = re.compile(
    r'<(?!/|!)(?!style\b)(?!script\b)(?!html\b)(?!head\b)(?!body\b)'
    r'\w[\w-]*((?:"[^"]*"|\'[^\']*\'|[^>"\'])*)>')
_PASTE_ROOT_NAME = re.compile(r'\b(class|id)="([^"\s]+)')
#: Шапка их файла — длинный `<!-- … -->` с примером использования, и в примере
#: стоит та же разметка, что и в настоящем корне. Ищем корень по тексту без
#: комментариев: у `texture-mask-text` разметки нет вовсе, а класс
#: `hf-texture-text` лежит в шапке — прежний поиск брал его оттуда, отдавал
#: селектор `.hf-texture-text`, и падение приходило уже от их парсера
#: («не нашёлся корень»), то есть с указанием не на ту причину.
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
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


def paste_body(html: str) -> str:
    """Файл позиции без комментариев.

    Шапка их файла — проза, и в ней встречаются те же теги, о которых она
    рассказывает: `bottom-up-letters` пишет «the declaration rides the <style>
    element below». Регэксп стиля хватал этот кусок прозы первым, и в
    композицию уезжал `<style>` с английским абзацем внутри — их `check`
    отвечал `css_parse_error: Unknown word element` (живой прогон
    `work/paste-target`). Разбор — только по телу.
    """
    return _HTML_COMMENT.sub("", html)


def paste_root_name(html: str) -> tuple[str, str] | None:
    """Имя корня paste-примитива: («class»|«id», токен). Нет корня — None.

    Одно место на весь путь: им `paste_fragment` строит селектор для их
    парсера, им же `paste_effect` разводит копии одной позиции по кадру.
    Разойтись двум местам нечем — прежде селектор искали по всему файлу
    (с шапкой-комментарием), а имя для развода — по вырезанному корню, и они
    расходились ровно там, где корень нашёлся в примере из шапки.
    """
    body = paste_body(html)
    for tag in _PASTE_ROOT_TAG.finditer(body):
        found = {kind: name for kind, name
                 in _PASTE_ROOT_NAME.findall(tag.group(1))}
        if "class" in found:
            return "class", found["class"]
        if "id" in found:
            return "id", found["id"]
        # Первый же элемент разметки без class и id корнем не станет: имени,
        # которым его ищет собственный скрипт позиции, у него нет.
        return None
    return None


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

    `selector` — готовый CSS-селектор корня, когда он известен вызывающему:
    так его называет `hf_captions`. Не назван — ищем корень сами
    (`paste_root_name`).
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
        found = paste_root_name(html)
        if not found:
            raise RuntimeError(
                f"в {source} нет своей разметки: позиция — приём поверх "
                "чужих элементов («add class=… to your text elements», её "
                "же шапка), а не самостоятельный кусок кадра, и вставлять "
                "литералом там нечего")
        kind, name = found
        selector = ("." if kind == "class" else "#") + name
    found = sdk.extract(source, selector)
    if not found:
        raise RuntimeError(f"в {source} не нашёлся корень {selector}")
    root = found[0]["outer"]
    body = paste_body(html)
    style_match = _PASTE_STYLE.search(body)
    script_match = _PASTE_SCRIPT.search(body)
    return (style_match.group(0) if style_match else "",
           root,
           script_match.group(0) if script_match else "")


def paste_effect(sdk, public, name: str, *, unique: str,
                 variables: dict) -> tuple:
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

    Имя корня (класс, а у `vignette` и `grid-pixelate-wipe` — id) общее для
    всех копий одной и той же позиции в кадре: без переименования вторая
    копия читала бы значения первой (обе слушают один `querySelectorAll` по
    общему имени). Переименование — тем же приёмом, каким `_stage_overlay`
    переименовывает `data-composition-id`.

    Анимация из комментария «Timeline integration» больше не остаётся в
    комментарии: её разбирает `wire_recipe` и отдаёт строками нашего
    таймлайна — это и есть пятый шаг их контракта («add those calls to your
    timeline», `hyperframes-registry/SKILL.md:81`). Отдаём их вторым
    значением, а не вписываем здесь: секунда сцены известна вызывающему, а
    не куску разметки.
    """
    source = _installed_path(public, name, "component")
    style, root, script = paste_fragment(sdk, public, source)
    found = paste_root_name(root)
    if not found:
        raise RuntimeError(f"корень {name} потерял имя при извлечении")
    token = found[1]
    scoped = f"{token}--{unique}"
    boundary = re.compile(r"(?<![\w-])" + re.escape(token) + r"(?![\w-])")
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
    lines, refused, _ = wire_recipe(
        source.read_text(encoding="utf-8"), unique=unique,
        target=None)
    return f"{style}\n{root}\n{shim}\n{script}", lines, refused



# ── пятый шаг их контракта: рецепт таймлайна в наш таймлайн ────────────────
# Их полка описывает вставку компонента пятью шагами, и пятый звучит так: «If
# the component exposes GSAP timeline integration (see the comment block in the
# snippet), add those calls to your timeline»
# (hyperframes-registry/SKILL.md:81). Четыре первых шага делает `paste_effect`
# (стиль, разметка, скрипт, переменные), пятый не делал никто — позиция
# вставала статичным кадром. Ниже он и живёт.
#
# Формат рецепта у них один на весь реестр, и назван он их же документом
# ремонта каталога: «fold the trailing `Timeline integration:` recipe into a
# real `<script>`»
# (hyperframes-registry/references/component-quality-bar.md:101). То есть
# признак — комментарий, чья строка начинается словами `Timeline integration`;
# всё после неё до конца комментария и есть код для хостового таймлайна.
# Шестнадцати частных случаев тут нет: разбор один, а что из него не уложилось,
# называется дословно причиной отказа.

#: Строка-заголовок рецепта. За ней в том же комментарии идёт сам код.
_RECIPE_HEAD = re.compile(r"^[ \t]*Timeline integration\b[^\n]*\n",
                          re.M | re.I)
#: С чего начинается первая инструкция рецепта. Между заголовком и кодом у
#: части позиций стоит абзац прозы («GAPS is the measured token rhythm …» у
#: `streaming-text`, «footage. Offsets are seconds …» у `sheet-spring-up`), и
#: проза — не инструкция: она несёт и скобки, и точки с запятой, а разбор
#: приклеивал её к первой настоящей инструкции и уносил ту в отказ. Список
#: закрытый и снят с каталога: все 70 рецептов начинаются одним из этих слов.
_RECIPE_CODE_START = re.compile(
    r"^[ \t]*(?://|tl\.|gsap\.|window\.|document\.|(?:const|let|var|function)\s"
    r"|(?:if|for|while)\s*\()", re.M)
#: Класс, который их шапка велит повесить на СВОЙ элемент: «Wrap target text
#: with class="hf-inline-highlight"», «Add class="hf-soft-blur-in" to the
#: element you want to reveal». Другого места, где этот класс назван, у файла
#: нет — ни в реестровой карточке, ни в стиле его от собственных классов не
#: отличить. Шапка — первый комментарий файла: во втором у части позиций стоит
#: пример хостовой композиции с чужими классами (`caption-blend-difference`).
_HEAD_CLASS = re.compile(r'class="([^"]+)"')
#: Имя, объявленное скриптом самой позиции: её API (`attachMotionBlur`) и её
#: же служебные функции. По нему рецепт отличает вызов контракта позиции от
#: демонстрационного твина, который автор написал ради примера.
_SCRIPT_DECL = re.compile(
    r"\bfunction\s+([A-Za-z_$][\w$]*)|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    r"\s*=|\bwindow\.([A-Za-z_$][\w$]*)\s*=")
#: Классы, объявленные стилем позиции: её собственные узлы, которые строит её
#: же скрипт (`.hf-number-wheel-strip`, `.hf-bottom-up-letters-char`).
_STYLE_CLASS = re.compile(r"\.(-?[A-Za-z_][\w-]*)")
#: Имена, которые рецепту разрешено называть, ничего не объявив: наш таймлайн,
#: их рантайм и то, что даёт браузер.
_RECIPE_GLOBALS = frozenset(
    ("tl", "gsap", "window", "document", "Math", "String", "Number", "Array",
     "startTime", "true", "false", "null", "undefined",
     # Ключевые слова самого языка: `if`, `const` и прочие именами не
     # являются, а разбор видит их такими же словами.
     "if", "else", "for", "while", "function", "return", "const", "let",
     "var", "new", "typeof", "in", "of", "this"))
_IDENT = re.compile(r"(?<![\w.$])([A-Za-z_$][\w$]*)")
#: Параметры стрелочной функции и `function (…)`: имена, объявленные
#: самим рецептом на месте.
_ARROW_PARAMS = re.compile(
    r"\(([^()]*)\)\s*=>|\bfunction\s*\w*\s*\(([^()]*)\)")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
#: Цвет, а не селектор. Идентификатор в CSS не может начинаться с цифры
#: (`css-syntax-3`, ident-token), поэтому `'#767676'` селектором не бывает
#: никогда. Без этой оговорки твин рецепта
#: `tl.fromTo(w, { color: '#767676' }, …)` читался чужим селектором и
#: отказывался целиком — а он и есть то единственное, что проявляет слова
#: `streaming-text`.
_COLOR_LITERAL = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def paste_head(html: str) -> str:
    """Шапка их файла — первый комментарий. Нет комментария — пустая строка."""
    found = _HTML_COMMENT.search(html)
    return found.group(0) if found else ""


def paste_attach_classes(html: str) -> list[str]:
    """Классы, которые их шапка велит повесить на элемент ХОСТА.

    Пустой список значит, что позиция самостоятельна: свою разметку она несёт
    сама (`confetti`, `icon-swap`, `grid-pixelate-wipe`), и вешать её не на
    что. Классы с подстановкой в имени (`hf-texture-{name}`) не берём: имя
    выбирает автор из списка в той же шапке, канала такого выбора у плана нет,
    и подставить за автора значит выдумать содержание.
    """
    seen: list[str] = []
    for group in _HEAD_CLASS.findall(paste_head(html)):
        for token in group.split():
            if "{" in token or token in seen:
                continue
            seen.append(token)
    return seen


def paste_own_names(html: str) -> tuple[set, set]:
    """Имена самой позиции: (классы её стиля, имена её скрипта)."""
    body = paste_body(html)
    style = "".join(_PASTE_STYLE.findall(body))
    script = "".join(_PASTE_SCRIPT.findall(body))
    declared = {name for triple in _SCRIPT_DECL.findall(script)
                for name in triple if name}
    return set(_STYLE_CLASS.findall(style)), declared


def _statements(code: str) -> list:
    """Рецепт на инструкции. Проза комментария сюда не доезжает: она не
    кончается `;` и не закрывает блок, и остаток без конца отбрасывается."""
    out, buf, depth, quote = [], [], 0, ""
    index = 0
    while index < len(code):
        char = code[index]
        if quote:
            buf.append(char)
            if char == "\\" and index + 1 < len(code):
                buf.append(code[index + 1])
                index += 2
                continue
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in "\"'":
            quote = char
            buf.append(char)
            index += 1
            continue
        if code.startswith("//", index):
            found = code.find("\n", index)
            if found < 0:
                break
            index = found
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                # Закрывающая скобка, которую никто не открывал, приходит
                # только из прозы их же комментария: сам код рецепта
                # сбалансирован. У `streaming-text` заголовок рецепта уносит
                # «(seconds between», а строкой ниже остаётся «arrive
                # together)» — и счётчик уходил в минус, после чего НИ ОДНА
                # инструкция уже не отрезалась по `;` на нулевой глубине.
                # Весь рецепт пропадал молча, а он — единственное, что
                # проявляет слова позиции (`.w { opacity: 0 }`): в кадре
                # оставался пустой прямоугольник (прогон
                # `exp-beat-direction-2`, вариант Б, 11,4 и 14,3 с).
                # Пересинхронизируемся: собранное до сих пор было прозой.
                buf = []
                index += 1
                continue
            depth -= 1
            # Блок (`if (…) { … }`) кончается закрывающей скобкой, а не `;`.
            # Объектный литерал в конце присваивания — нет: `window.x = {};`
            # закрывается точкой с запятой, и разрыв по `}` оставил бы от него
            # хвост из одного знака.
            if depth == 0 and char == "}" and re.match(
                    r"^\s*(?:if|for|while|function)\b|^\s*\{",
                    "".join(buf)):
                buf.append(char)
                out.append("".join(buf).strip())
                buf = []
                index += 1
                continue
        if char == ";" and depth == 0:
            out.append("".join(buf).strip() + ";")
            buf = []
            index += 1
            continue
        buf.append(char)
        index += 1
    return [one for one in out if one]


def paste_recipe(html: str) -> list:
    """Инструкции из комментария «Timeline integration». Нет его — пусто.

    Проза между заголовком и кодом отрезается по `_RECIPE_CODE_START`: она
    не инструкция, а объяснение автора, и её скобки разбор считал за код.
    """
    for comment in _HTML_COMMENT.findall(html):
        head = _RECIPE_HEAD.search(comment)
        if not head:
            continue
        body = comment[head.end():]
        body = body[:body.rfind("-->")] if "-->" in body else body
        code = _RECIPE_CODE_START.search(body)
        return _statements(body[code.start():] if code else body)
    return []


def _string_literals(text: str) -> list:
    """Строковые литералы инструкции: (начало, конец, кавычка, содержимое)."""
    out, index = [], 0
    while index < len(text):
        char = text[index]
        if char in "\"'":
            end = index + 1
            while end < len(text) and text[end] != char:
                end += 2 if text[end] == "\\" else 1
            out.append((index, end + 1, char, text[index + 1:end]))
            index = end + 1
            continue
        index += 1
    return out


def _resolve_selector(selector: str, *, root, scoped_root: str,
                      attach: list, scoped_attach: str, own: set):
    """Их селектор — в наш. `None` значит, что имя в кадре ничему не отвечает.

    Три случая, и все три — из самого файла: корень позиции (переименован в
    копию), класс из её шапки (висит на нашей мишени) и её собственный класс,
    который строит её же скрипт (живёт ВНУТРИ первых двух, поэтому доезжает
    потомком).
    """
    body = selector.strip()
    first = body.split(",")[0].strip().split()[0]
    match = re.match(r"^([.#])([-\w]+)", first)
    if not match:
        return None
    mark, name = match.group(1), match.group(2)
    tail = body[len(first):]
    if root and name == root[1] \
            and mark == ("." if root[0] == "class" else "#"):
        return mark + scoped_root + tail
    if name in attach:
        return "." + scoped_attach + tail
    if name in own:
        anchor = ("." + scoped_attach if attach
                  else ("." if root and root[0] == "class" else "#")
                  + scoped_root)
        return f"{anchor} {body}"
    return None


def _time_slot(statement: str):
    """Последний аргумент вызова `tl.<метод>(…)` — позиция на шкале."""
    call = re.match(r"^tl\.\w+\s*\(", statement)
    if not call:
        return None
    start = call.end()
    depth, quote, splits = 1, "", [start]
    index = start
    while index < len(statement) and depth:
        char = statement[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if not depth:
                break
        elif char == "," and depth == 1:
            splits.append(index + 1)
        index += 1
    if depth != 0 or len(splits) < 2:
        return None
    # Висячая запятая перед скобкой: последний аргумент пуст, и позиция на
    # шкале — предыдущий (`parallax-zoom` пишет рецепт именно так).
    while len(splits) > 1 and not statement[splits[-1]:index].strip():
        index = splits.pop() - 1
    if len(splits) < 2:
        return None
    return splits[-1], index, statement[splits[-1]:index].strip()


def _declared_name(text: str):
    found = re.match(r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)", text)
    return found.group(1) if found else ""


def wire_recipe(html: str, *, unique: str, target=None):
    """Рецепт позиции — строками нашего таймлайна.

    Отдаёт `(строки, отказы, классы-на-мишень)`. Отказ — дословная инструкция
    их файла, которой в нашем кадре не на что лечь: чужой селектор их примера
    (`#scene-a`), имя, которого никто не объявил (`DATA_DURATION`), их же
    заготовка нашего таймлайна (`const tl = …`). Отказ не роняет позицию: он
    записывается причиной, а остальные строки встают.

    Секунда в рецепте бывает двух видов: `startTime` (плюс смещение) и голое
    число их примера. Голое число — не наша секунда, но РИТМ примера в нём
    настоящий: `3.0` и `3.6` у `grid-pixelate-wipe` значат «накрыть и через
    0,6 с открыть». Поэтому числа пересчитываются от самого раннего из них к
    началу сцены, а не выбрасываются и не берутся как есть.
    """
    statements = paste_recipe(html)
    if not statements:
        return [], [], []
    root = paste_root_name(html)
    attach = paste_attach_classes(html)
    own_classes, own_names = paste_own_names(html)
    scoped_root = f"{root[1]}--{unique}" if root else ""
    scoped_attach = f"{attach[0]}--{unique}" if attach else ""
    kept, refused, declared = [], [], set()
    for statement in statements:
        text = statement
        if re.match(r"^(?:const|let|var)\s+(?:tl|startTime)\b", text) \
                or text.startswith("window.__timelines"):
            refused.append(statement)
            continue
        bad = False
        for start, end, quote, value in reversed(_string_literals(text)):
            if not value.startswith((".", "#")) or _COLOR_LITERAL.match(value):
                continue
            found = _resolve_selector(
                value, root=root, scoped_root=scoped_root, attach=attach,
                scoped_attach=scoped_attach, own=own_classes)
            if found is None:
                # Селектор их примера, а не контракта: он называет элемент
                # ХОСТА, придуманный автором для показа (`#my-box`,
                # `#scene-a`). Подставлять на его место нашу мишень можно
                # только там, где контракт сам просит селектор, — в вызове
                # функции ПОЗИЦИИ с нашим таймлайном аргументом
                # (`attachMotionBlur(sel, tl)`, её же шапка, раздел `API`).
                api = re.match(r"^([A-Za-z_$][\w$]*)\s*\(", text)
                if (target and api and api.group(1) in own_names
                        and re.search(r"(?<![\w.$])tl(?![\w$])", text)):
                    found = target
                else:
                    bad = True
                    break
            text = text[:start] + quote + found + quote + text[end:]
        if bad:
            refused.append(statement)
            continue
        # Имена ищем по коду без строк: внутри литерала стоят их же ключи
        # анимации («power2.out», «--hf-highlight-scale»), и они не имена.
        code = text
        for start, end, _, _ in reversed(_string_literals(code)):
            code = code[:start] + '""' + code[end:]
        params = {one for pair in _ARROW_PARAMS.findall(code)
                  for group in pair
                  for one in re.findall(r"[A-Za-z_$][\w$]*", group)}
        # Имя, которое инструкция сама и объявляет, неизвестным не считаем.
        if _declared_name(text):
            declared.add(_declared_name(text))
        names = {name for name in _IDENT.findall(code)
                 if name not in _RECIPE_GLOBALS and name not in own_names
                 and name not in declared and name not in params
                 and not re.search(r"(?<![\w.$])" + re.escape(name)
                                   + r"\s*:", code)}
        if names:
            refused.append(statement)
            continue
        kept.append((statement, text))
    # Объявление держим только там, где его кто-то читает ниже.
    body = " ".join(text for _, text in kept)
    keep = []
    for statement, text in kept:
        name = _declared_name(text)
        if name and len(re.findall(
                r"(?<![\w.$])" + re.escape(name) + r"(?![\w$])", body)) < 2:
            refused.append(statement)
            continue
        keep.append((statement, text))
    # Инструкция, которая наш таймлайн не называет вовсе, рецептом не была:
    # `tl` в ней либо метод (`tl.to`), либо аргумент их же функции
    # (`attachMotionBlur(sel, tl)`, `motion-blur.html`, раздел `API`).
    if not any(re.search(r"(?<![\w.$])tl(?![\w$])", text)
               for _, text in keep):
        return [], refused + [one for one, _ in keep], attach
    numbers = [float(_time_slot(text)[2]) for _, text in keep
               if _time_slot(text) and _NUMBER.match(_time_slot(text)[2])]
    base = min(numbers) if numbers else 0.0
    lines = []
    for _, text in keep:
        slot = _time_slot(text)
        if slot and _NUMBER.match(slot[2]):
            shift = round(float(slot[2]) - base, 4)
            where = "startTime" if not shift else f"startTime + {shift}"
            text = text[:slot[0]] + " " + where + text[slot[1]:]
        lines.append(text)
    return lines, refused, attach



#: Мишень приёма — наш элемент кадра, на который их шапка велит повесить свой
#: класс. Список закрытый и общий на всех: по нему судит гейт до оплаты
#: (`hf_gates._element_problems`), по нему же сборка ищет селектор, и по нему
#: карточка каталога называет, куда позицию вообще можно поставить.
#:
#: - `self` — у позиции своя разметка, вешать не на что (`confetti`,
#:   `icon-swap`): рецепт целится в её собственный корень;
#: - `presenter` — окно ведущей (`#video-wrap`);
#: - `insert` — вставки сцены, все планы серии разом;
#: - `caption` — ОДНО слово титра, звучащее в этой сцене; какое — называет
#:   элемент полем `word` (их же контракт оборачивает текст, а не строку:
#:   «Wrap target text», `inline-highlight.html:4`);
#: - `schema` — коробка схемы сцены. Ни одна карточка её сегодня не называет:
#:   живой прогон показать её не смог — сцена со схемой в пробе выходит пустой
#:   и БЕЗ приёма тоже (контрольная сборка, `work/paste-target-control`), то
#:   есть дело не в приёме. Мишень остаётся в словаре: путь до неё общий с
#:   `presenter`, а карточка добавится, когда кадр со схемой удастся снять.
PASTE_TARGETS = ("self", "presenter", "insert", "caption", "schema")

#: Куда уезжают скрипты приёмов-декораторов. Отдельным файлом, а не
#: строками композиции, — по той же причине и тем же приёмом, каким
#: уезжает движок титра (`hf_captions.CAPTION_SCRIPT`): их линтер считает
#: физические строки `index.html` и за 300 даёт `composition_file_too_large`
#: (packages/lint/src/rules/composition.ts:16), а под `--strict`
#: предупреждение роняет сборку. Живой прогон на десяти приёмах литералом
#: дал 672 строки.
DECOR_SCRIPT = "paste-decor.js"

#: Внешний скрипт в их рантайме исполняется ДО разбора тела: живой прогон
#: (`work/paste-target`) с пробой в этом самом файле ответил
#: `readyState=loading stage=0 wrap=0 words=0` — на месте нет ещё ни окна
#: ведущей, ни вставок, ни слов титра, и вешать классы не на что. Их
#: собственный движок титра решает это тем же ожиданием —
#: `document.fonts.ready.then(...)` (`assets/caption-highlight.html:506-516`),
#: — и таймлайн регистрирует уже в нём; соседний таймлайн их плеер подхватит
#: и поздний (`packages/core/src/runtime/player.ts:68-84`). Ждём и разбора
#: тела, и шрифтов: одного `fonts.ready` мало, когда шрифты врезаны в файл и
#: промис успевает решиться раньше конца разбора.
DECOR_BOOT = """function ready() {
var fonts = document.fonts && document.fonts.ready
  ? document.fonts.ready : Promise.resolve();
fonts.then(start);
}
if (document.readyState === "loading") {
document.addEventListener("DOMContentLoaded", ready);
} else {
ready();
}
"""


def paste_attach(selector: str, classes: list, *,
                 first=None, last=None) -> str:
    """Скрипт, вешающий классы их шапки на наш элемент.

    Классов два: их собственный (его читает их же CSS и их же скрипт) и наш
    `имя--маунт` — по нему рецепт целится в ЭТУ копию, а не во все сразу.
    Иначе второй такой же приём в другой сцене поехал бы по чужому времени.

    Вешаем скриптом, а не атрибутом разметки, по одной причине: слова титра
    рисует их же движок (`captions.js`) в момент разбора страницы, и в нашей
    разметке их нет вовсе. Скрипт стоит в теле документа после движка титра и
    до нашего таймлайна — к моменту создания твинов узлы на месте, а сама
    навеска происходит один раз при загрузке и от перемотки не зависит.
    """
    slice_from = "0" if first is None else str(int(first))
    slice_to = "undefined" if last is None else str(int(last))
    return ("<script>(function () { Array.prototype.slice.call("
            f"document.querySelectorAll({_js(selector)}), {slice_from}, "
            f"{slice_to}).forEach(function (node) {{ node.classList.add("
            + ", ".join(_js(one) for one in classes)
            + "); }); })();</script>")


def paste_recipe_block(lines: list, at: float) -> list:
    """Рецепт — блоком со своей `startTime`.

    Их рецепты называют секунду именем `startTime` (а `three-orbiting-cards`
    ещё и объявляет его сам). Блок `{ … }` даёт каждому элементу своё
    объявление, не мешая соседям: `const` в JS живёт блоком.
    """
    if not lines:
        return []
    return (["{", f"const startTime = {markup_time(at)};"]
            + list(lines) + ["}"])


def paste_decorator(sdk, public, name: str, *, unique: str, variables: dict,
                    target: dict) -> tuple:
    """Приём их полки поверх НАШЕГО элемента кадра. Пятый шаг их контракта.

    Отдаёт `(стиль, тело скрипта, строки таймлайна, отказы)`.

    Отличие от `paste_effect` одно и оно же — вся суть: у такой позиции своей
    разметки нет («This fragment has no markup of its own», их же
    `bottom-up-letters`), и ставить в кадр нечего. Она декорирует элемент
    ХОСТА: «Wrap target text with class="hf-inline-highlight"»
    (`inline-highlight.html:4`), «call attachMotionBlur() with any element
    animated by your GSAP timeline» (`motion-blur.html:4-5`). Поэтому корень
    не режется вовсе, а класс из шапки вешается на наш элемент
    (`paste_attach`), и рецепт их комментария едет в наш таймлайн
    (`wire_recipe`).

    Класс их шапки НЕ переименовываем, в отличие от корня в `paste_effect`:
    на него смотрит их собственный CSS и их собственный скрипт
    (`document.querySelectorAll(".shimmer-sweep-target")`), и переименование
    погасило бы позицию целиком. Разводит копии второй класс, `имя--маунт`, —
    его знает только рецепт.
    """
    source = _installed_path(public, name, "component")
    html = source.read_text(encoding="utf-8")
    fixed = _rewrite_sibling_assets(
        html, install_dir=source.parent, project_root=Path(public))
    if fixed != html:
        source.write_text(fixed, encoding="utf-8")
        html = fixed
    classes = paste_attach_classes(html)
    lines, refused, _ = wire_recipe(
        html, unique=unique, target=target["selector"])
    if not classes and not lines:
        # Контракт позиции состоит из двух каналов, и хотя бы один обязан
        # сработать: класс в шапке («Add class="…" to the element you want to
        # reveal») или её собственная функция с нашим таймлайном аргументом
        # («API: attachMotionBlur(selector, timeline, options?)»,
        # motion-blur.html). Нет ни того, ни другого — приёма не выйдет.
        raise RuntimeError(
            f"{name}: шапка позиции не называет ни класса для своего элемента "
            "(«class=…»), ни рецепта таймлайна — вешать на мишень нечего")
    body = paste_body(html)
    style = "".join(_PASTE_STYLE.findall(body))
    script = "".join(_PASTE_SCRIPT.findall(body))
    style = _CDN_FONTS.sub("", style)
    style = _FONT_FAMILY.sub(_OUR_STACK, style)
    script = _CDN_GSAP.sub('src="gsap-vendor.min.js"', script)
    rewrite_kw = {"install_dir": source.parent, "project_root": Path(public)}
    style = _rewrite_sibling_assets(style, **rewrite_kw)
    script = _rewrite_sibling_assets(script, **rewrite_kw)
    shim = (" <script>window.__hyperframes = window.__hyperframes || {};"
            " window.__hyperframes.getVariables = function () { return "
            + json.dumps(variables or {}, ensure_ascii=False) +
            "; };</script>")
    attach = (paste_attach(
        target["selector"], classes + [f"{classes[0]}--{unique}"],
        first=target.get("first"), last=target.get("last"))
        if classes else "")
    # Порядок обязателен: сперва классы, потом скрипт позиции. Их скрипты
    # обходят `document.querySelectorAll` СВОЕГО класса один раз на старте
    # (`shimmer-sweep` вставляет маску, `bottom-up-letters` режет текст на
    # буквы) — до навески они не нашли бы ничего.
    # Скрипт отдаём ТЕЛОМ, без тега: он уезжает в отдельный файл, как
    # уже уезжает движок титра (`hf_captions.CAPTION_SCRIPT`). Причина
    # та же и измерена тем же: их линтер считает физические строки
    # `index.html` и за 300 даёт `composition_file_too_large`, а под
    # `--strict` предупреждение роняет сборку
    # (packages/lint/src/rules/composition.ts:16). Живой прогон
    # `work/paste-target` на десяти приёмах дал 672 строки — тело
    # `<style>` их счётчик выбрасывает, а тела скриптов нет.
    code = "\n".join(_SCRIPT_BODY.sub("", one).strip()
                     for one in (attach, shim, script) if one.strip())
    return style, code, lines, refused


def paste_target(card: dict, element: dict) -> tuple:
    """Мишень элемента: `(имя, причина отказа)`. Одно из двух всегда пусто.

    Позиция без `targets` в карточке мишени не знает вовсе — это обычная
    позиция, которая встаёт в кадр сама собой, и пустое имя тут не отказ.

    Мишень одна-единственная в карточке — её и берём: выбора нет, а
    заставлять агента переписывать единственное значение значит просить его
    угадать наше поле. Мишеней несколько — выбирает агент по содержанию
    сцены: подсветить слово или смазать вставку решает смысл, а не код.
    """
    allowed = list(card.get("targets") or [])
    if not allowed:
        return "", ""
    named = str(element.get("target") or "").strip()
    if not named:
        if len(allowed) == 1:
            return allowed[0], ""
        return "", ("мишень не названа: приём вешают на элемент кадра, и эта "
                    "позиция ложится на " + ", ".join(f"`{one}`"
                                                      for one in allowed))
    if named not in allowed:
        return "", (f"мишень {named!r} этой позиции не годится, она ложится "
                    "на " + ", ".join(f"`{one}`" for one in allowed))
    return named, ""


def target_absent(scene: dict, target: str, *, words: list | None = None,
                  word: str | None = None) -> str:
    """Чего сцене не хватает под эту мишень. Пустая строка — всё на месте.

    Спрашивается дважды и одним кодом: гейтом `D36_elements` до заказа
    ведущей и сборкой перед вставкой. Разойтись двум местам нечем, а цена
    расхождения — оплаченный кадр с приёмом, которому не на чем лежать.

    `caption` — единственная мишень уровня слова, а не элемента: их же
    контракт оборачивает ОДНО слово («Wrap target text with class=…»,
    `inline-highlight.html:4`), а не строку целиком. Поэтому здесь спрошено
    не «есть ли титр», а «есть ли в титре этой сцены ИМЕННО это слово» —
    имя называет агент (`word` элемента), счёт делает код
    (`hf_captions.caption_word_range`). `words` — расшифровка ролика; её
    здесь может не быть (гейт D11 после сборки зовёт эту же функцию по
    раскадровке, где расшифровка уже не под рукой) — тогда судить нечем, и
    молчим, как молчали до этой работы.
    """
    from reels_factory.hf_captions import caption_word_range
    from reels_factory.hf_montage import insert_of

    if target == "presenter" and str(scene.get("presenter") or "none") == "none":
        return ("окна ведущей в этой сцене нет (`presenter: \"none\"`), а "
                "приём вешают на него")
    if target == "insert" and not insert_of(scene):
        return "вставки у сцены нет, а приём вешают на неё"
    if target == "schema" and not schema_plan(scene):
        return "схемы у сцены нет, а приём вешают на неё"
    if target == "caption":
        named = str(word or "").strip()
        if not named:
            return ("мишень `caption` ложится на ОДНО слово титра, а какое "
                    "— поле `word` элемента не называет: назови слово, "
                    "которое приём выделит (не строку и не фразу)")
        if words is None:
            return ""
        first, last = caption_word_range(
            words, float(scene["startSec"]), float(scene["endSec"]),
            word=named)
        if first == last:
            return (f"слова {named!r} в титре этой сцены нет: приём "
                    "вешают на слово, которое в неё звучит, а не на любое "
                    "слово ролика")
    return ""


def paste_target_selector(scene: dict, target: str, *, insert_targets: dict,
                          words: list, word: str | None = None) -> dict:
    """Мишень — селектором и, у титра, счётом слов этой сцены.

    Слова титра рисует их движок в момент разбора страницы, все разом на весь
    ролик; сцене принадлежат не все, а те, что в её секунды и звучат. Их
    счёт — арифметика, и делает её код (`hf_captions.caption_word_range`), а
    не агент: границы сцены он и так назвал.

    `caption` сужен до ОДНОГО слова — того, что назвал агент полем `word`
    элемента (`target_absent` тем же кодом уже проверил, что оно в сцене
    звучит). Их контракт оборачивает текст, а не строку («Wrap target text
    with class=…», `inline-highlight.html:4`), и слайс `[i, i+1)` даёт
    ровно один узел `.hl-word-text` вместо всех слов сцены разом.

    `start` в ответе — секунда, на которую вызывающий ставит рецепт: у
    мишени-слова это её СОБСТВЕННАЯ секунда начала (`flat[first]["start"]`),
    не начало сцены. Их же полка вяжет вход слова ровно так, не с 0: разбор
    их движка титра кладёт `FLOW_IN` каждого слова на `w.start`
    (`skills/embedded-captions/modes/standard/_anatomy.md:176-191`), а
    демо-позиция `caption-pill-karaoke` красит слово в момент, отсчитанный
    от его же `word.start`, а не от начала клипа
    (`caption-pill-karaoke.html:365-376`). У остальных мишеней сцена и есть
    их появление — `presenter`/`insert`/`schema` в `target_absent` спрошены
    по сцене целиком, ключ `start` для них не нужен, и вызывающий сам берёт
    начало сцены (`begin`) для них по умолчанию.
    """
    from reels_factory.hf_captions import caption_segments, caption_word_range

    if target == "presenter":
        return {"selector": "#video-wrap"}
    if target == "insert":
        found = insert_targets.get(scene["id"]) or []
        return {"selector": ", ".join(found)} if found else {}
    if target == "schema":
        return {"selector": f'#schema-box-{scene["id"]}'}
    if target == "caption":
        first, last = caption_word_range(
            words, float(scene["startSec"]), float(scene["endSec"]),
            word=word)
        if first == last:
            return {}
        flat = [word_ for segment in caption_segments(words)
               for word_ in segment]
        return {"selector": ".hl-word-text", "first": first, "last": last,
                "start": flat[first]["start"]}
    return {}

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
        if block and block not in found and str(block) not in _skipped_positions():
            found.append(str(block))
        for element in scene_elements(scene):
            name = str(element["name"]).strip()
            if name not in found and name not in _skipped_positions():
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
    reason = _skipped_positions().get(str(block))
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
    reason = _skipped_positions().get(str(name))
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
    # Позиция каталога со слотами под файл забирает кадр сцены себе: файл
    # ложится ВНУТРЬ её слота (`hf_slots.fill_ops`), а рамку, маску и ход
    # рисует сама позиция. Отдельным слоем ту же вставку тогда не ставим —
    # один и тот же клип в кадре дважды читается сбоем сборки, а не монтажом.
    slotted: dict[str, list[str]] = {}
    for scene in scenes:
        if not insert_of(scene):
            continue
        for element in scene_elements(scene):
            slots = (_catalog_cards().get(str(element.get("name") or "").strip())
                     or {}).get("media_slots")
            if slots:
                slotted[str(scene["id"])] = sorted(slots)
                break
    series: dict[str, list[str]] = {}
    for scene in scenes:
        if not insert_of(scene) or str(scene["id"]) in slotted:
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
    #: Сцена -> селекторы её вставок. Мишень `insert` у paste-приёма
    #: (`PASTE_TARGETS`) целится в них же, а не в новый селектор: элемент
    #: один, и второе имя для него разошлось бы с первым.
    insert_targets: dict = {}
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
            # Тот же селектор — мишень `insert` у paste-приёма: элемент,
            # который наш таймлайн уже двигает по x/y, и на который их
            # `attachMotionBlur` ждёт ссылку («any element animated by your
            # GSAP timeline», motion-blur.html:5).
            insert_targets.setdefault(scene["id"], []).append(target)
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
        content_box = _measured_content_box(
            Path(public) / "compositions" / f"{unique}.html", canvas)
        geometry = _overlay_geometry(str(overlay["block"]), canvas,
                                     content_box=content_box)
        if geometry is None:
            print(f'{scene["id"]}: накладка {overlay["block"]} снята — '
                  f"даже подогнанная под зону над титром, она нечитаема "
                  f"(масштаб ниже {OVERLAY_MIN_SCALE})")
            scene.pop("overlay", None)
            continue
        scale, box = geometry
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
        # Хостовый id разведён с id внутри копии — та же причина, что у
        # `common` в цикле элементов сцены (см. её комментарий там же):
        # их `inlineSubCompositions.ts` вклеивает копию в тот же
        # документ, и совпадающий `data-composition-id` путал их
        # скоуп-скрипт при повторном seek.
        body.append(
            f'    <div class="ovl" style="{box}">'
            f'<div data-layout-allow-overflow="true" style="position:absolute;'
            f'left:0;top:0;transform:scale({scale:.4f});transform-origin:0 0">'
            f'<div id="ovl-{scene["id"]}" class="clip"'
            f' data-layout-allow-overflow="true"'
            f' data-composition-id="{unique}-host"'
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
    #: Стили приёмов-декораторов. Уезжают в конец тела, ПОСЛЕ движка титра:
    #: слова титра рисует он, и скрипт позиции, стоящий выше, не нашёл бы
    #: ни одного узла (`paste_decorator`, порядок в её докстринге).
    decorators: list = []
    #: Их же скрипты — одним файлом рядом, а не строками композиции: счётчик
    #: строк их линтера (`composition_file_too_large`) считает `index.html`, и
    #: десять приёмов литералом дают 672 строки при пороге 300.
    decor_code: list = []
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
            # Мишень приёма (`targets` в карточке) — до коробки: она и
            # решает, нужна ли коробка вообще.
            where, refusal = paste_target(card, element)
            if refusal:
                drop_element(storyboard, scene, name, refusal)
                continue
            rect = None
            # Приёму поверх чужого элемента коробка в кадре не нужна: он не
            # встаёт в кадр, а ложится на окно ведущей, вставку, слова титра
            # или схему. Вид `effect` у него от их же карточки реестра, и
            # требовать под него свободную зону значит снять приём там, где он
            # и не занимает места. Мишень `self` — другое дело: у такой
            # позиции разметка своя, и коробка ей нужна.
            if kind == "effect" and where in ("", "self"):
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
            # Слова плана в текстовые переменные позиции. У позиции без слотов
            # разметки текст живёт переменной, её пишет собственный скрипт
            # позиции, и слова агента туда не доезжали вовсе: в кадре стояла
            # английская демо-строка карточки («Get HyperFrames», «This changed
            # how we ship.»). Канал их штатный — `data-variable-values` ниже;
            # какие переменные его принимают и почему не всякая, сказано в
            # `hf_catalog.word_variables`. Названное планом значение сильнее.
            from reels_factory.hf_catalog import (
                number_mirror_variable, number_variables, word_variables,
            )
            named = dict(element.get("variables") or {})
            for key, phrase in zip(word_variables(card), said):
                named.setdefault(key, phrase)
            # Число плана в строковую переменную-зеркало той же позиции: у
            # `conic-progress-ring` видимый счётчик в центре — не `progress`
            # сам, а отдельная строка `label`, и без слова агента она
            # остаётся на умолчании карточки, пока кольцо доезжает до
            # спетого числа (`hf_catalog.number_mirror_variable`, там же —
            # кадр находки). Названное планом слово в `label` сильнее.
            for number_key in number_variables(card):
                value = named.get(number_key)
                if not isinstance(value, (int, float)) or isinstance(
                        value, bool):
                    continue
                mirror_key = number_mirror_variable(card)
                if mirror_key:
                    named.setdefault(mirror_key, str(int(round(value))))
            # Слоты позиции под файл: кадр биролла этой же сцены ложится ВНУТРЬ
            # них. Подавать нечего — позиция снимается с причиной вслух: пустой
            # макет (телефон без экрана, панель «Before» без картинки) хуже
            # отсутствия позиции. До заказа ведущей тот же вопрос уже задан
            # плану гейтом `D36_elements` (`hf_gates._element_problems`).
            slots = sorted(card.get("media_slots") or [])
            files = [(resolved.get(media_key(scene["id"], shot)) or {}).get("file")
                     for shot in range(shots_for(scene))] if slots else []
            from reels_factory.hf_slots import is_slot_file
            files = [one for one in files if one and is_slot_file(one)]
            if card.get("host_slots"):
                drop_element(
                    storyboard, scene, name,
                    "содержимое слотов "
                    + ", ".join(sorted(card["host_slots"]))
                    + " позиция ждёт разметкой из хостовой страницы, а сборка "
                    "ставит её сабкомпозицией — в кадре остался бы серый "
                    "скелет-заглушка")
                continue
            if slots and not files:
                drop_element(
                    storyboard, scene, name,
                    "позиция ждёт картинку в слоты " + ", ".join(slots)
                    + ", а сцене не подобралось ни одного кадра (ролик в такой "
                    "слот их линтер не пускает — `hf_slots._media_child`) — в "
                    "кадре остался бы пустой макет")
                continue
            # Слот под файл бывает двух родов (`hf_catalog.catalog_cards`):
            # узел `data-slot` в разметке — файл встаёт в него `fill_ops`
            # (`supply`); их явный `type: "image"` у переменной —
            # `media_variable_slots` называет, какие из `slots` этого рода, и
            # файл ложится в `data-variable-values` тем же путём, каким туда
            # ложится слово плана (`word_variables`, выше). Один счётчик
            # позиции на оба рода — файлы разбираются по кругу вперемешку, а
            # не с двух отдельных нулей.
            var_slots = set(card.get("media_variable_slots") or [])
            supply = {}
            for position, slot in enumerate(slots):
                file = files[position % len(files)]
                if slot in var_slots:
                    named.setdefault(slot, file)
                else:
                    supply[slot] = {"file": file}
            supply = supply or None
            card_type = str(card.get("type") or "block")
            # Paste-контрактный эффект (`reels.mount`, карточка B1) не
            # монтируется саб-композицией вовсе — своего `data-composition-id`
            # и `<template>` у него нет (`_stage_overlay` на нём даёт
            # `missing_or_empty_sub_composition`, проверено живым
            # `check --strict` на `badge-pop`). Вставляем литералом
            # (`paste_effect`), той же идеей, какой каталог уже вставляет
            # `caption-highlight`.
            mount_kind = str(card.get("mount") or "composition")
            # Переменные позиции, которые решает кадр, а не план: полярность
            # букв под наш тёмный фон (`hf_schema.frame_variables` — там же
            # измерение и цитата автора позиции). Порядок силы снизу вверх:
            # кадр, слова плана (`named` выше), названное агентом.
            named = {**frame_variables(card, colors,
                                       element.get("variables")),
                     **named}
            if named:
                element["variables"] = named
            paste_html = None
            # Приём поверх НАШЕГО элемента: своей разметки у позиции нет, в
            # кадр она не встаёт, а вешается на окно ведущей, вставку, слова
            # титра или схему — пятый шаг их контракта («add those calls to
            # your timeline», hyperframes-registry/SKILL.md:81).
            if where and where != "self":
                lack = target_absent(scene, where, words=words,
                                     word=element.get("word"))
                if lack:
                    drop_element(storyboard, scene, name, lack)
                    continue
                spot = paste_target_selector(
                    scene, where, insert_targets=insert_targets, words=words,
                    word=element.get("word"))
                if not spot:
                    drop_element(
                        storyboard, scene, name,
                        f"мишени `{where}` в этой сцене не нашлось: вешать "
                        "приём не на что")
                    continue
                unique = f"{name}--{scene['id']}"
                try:
                    style, code, lines, refused = paste_decorator(
                        sdk, public, name, unique=unique, variables=named,
                        target=spot)
                except RuntimeError as error:
                    drop_element(storyboard, scene, name, str(error))
                    continue
                if style.strip():
                    decorators.append(style)
                if code.strip():
                    decor_code.append(f"/* {unique} */\n{code}")
                # Старт рецепта — секунда самой мишени, не сцены: у слова
                # титра это `spot["start"]` (`paste_target_selector`, там же
                # обоснование их конвенцией). Сцена ставит его в кадр
                # заранее только для окна ведущей, вставки и схемы — у них
                # появление в сцене и есть её начало (`target_absent` там
                # спрашивает по сцене целиком), и `spot` для них `start` не
                # несёт вовсе. Раньше рецепт ВСЕГДА стартовал с `begin`, и
                # слово, звучащее в середине или в конце сцены, получало
                # вход, отыгравший невидимо до его появления (ревью PR #87,
                # scratchpad review-word-target.md, замечание 1: слово
                # «боль» на 18,36–18,64 с при сцене с 16,0 с — твин
                # заканчивался к 16,9 с, за 1,5 с до слова).
                decor_code += paste_recipe_block(
                    lines, spot.get("start", begin))
                if refused:
                    element["recipeSkipped"] = refused
                staged_elements += 1
                kept.append(element)
                continue
            if kind == "effect" and mount_kind == "paste":
                unique = f"{name}--{scene['id']}"
                try:
                    paste_html, lines, refused = paste_effect(
                        sdk, public, name, unique=unique, variables=named)
                except RuntimeError as error:
                    drop_element(storyboard, scene, name, str(error))
                    continue
                decor_code += paste_recipe_block(lines, begin)
                if refused:
                    element["recipeSkipped"] = refused
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
                #
                # Заливка корня снимается только у `effect`: он ложится
                # коробкой поверх живого кадра, и своя подложка у него — их же
                # нарушенный контракт компонента (`overlay_css`). `scene`
                # держит кадр собой, и красить ему есть что.
                port = {"duration": length,
                       "elastic": not (kind == "scene" and landscape),
                       "height": OUT_H if kind == "scene" else None,
                       "config": {},
                       "css": palette_css(name, colors, root=root)
                       + (overlay_css(root) if kind == "effect" else "")}
                try:
                    unique, _, canvas = _stage_overlay(
                        public, name, scene["id"],
                        sdk=sdk if (said or supply) else None,
                        words=said or None, media=supply, port=port,
                        card_type=card_type)
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
                      + json.dumps(named, ensure_ascii=False)
                      .replace("'", "&#39;")
                      + "'") if named else ""
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
                    content_box = _measured_content_box(
                        Path(public) / "compositions" / f"{unique}.html",
                        canvas)
                    geometry = _overlay_geometry(name, canvas,
                                                 content_box=content_box)
                    if geometry is None:
                        drop_element(
                            storyboard, scene, name,
                            "даже подогнанная под зону над титром, позиция "
                            f"нечитаема (масштаб ниже {OVERLAY_MIN_SCALE})")
                        continue
                    scale, place = geometry
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
    #
    # Плашка читаемости под коробкой — НЕ маунт (см. `TRACK_SCHEMA_SCRIM`), и
    # её считает `timeline_track_too_dense` количеством, а не пересечением:
    # сколько дорожек ей отвести, считаем здесь же, до цикла, тем же приёмом,
    # что у `scrim_tracks` накладок ниже. Условие на `series.get` избыточно
    # шире реального (сцена может ещё потерять схему по времени формы), но
    # лишняя дорожка ничего не стоит — тот же довод, что у накладок.
    schema_scrim_tracks = max(1, -(-sum(
        1 for scene in scenes
        if schema_plan(scene) and series.get(scene["id"]))
        // SCHEMA_SCRIMS_PER_TRACK))
    staged_schema_scrims = 0
    for scene in scenes:
        plan = schema_plan(scene)
        if not plan:
            continue
        start, end = _q(scene["startSec"]), _q(scene["endSec"])
        # Где схеме стоять, решает не она сама, а кадр: окно ведущей, её лицо
        # и полоса титра. Зоны нет — схему снимаем здесь же, как снимаем её
        # по короткой сцене и по неподобравшемуся знаку: до сборки об этом
        # спросил гейт (`hf_gates.schema_position_problems`), но положение
        # ведущей после гейта переписывает код (`pick_position`,
        # `show_ordered_avatar`), и последнее слово за кадром.
        zone = schema_zone(scene.get("presenter"), face=face)
        if zone is None:
            print(f'{scene["id"]}: схема «{plan["form"]}» снята — ведущая '
                  f'`{scene.get("presenter") or "none"}` не оставляет ей '
                  "свободной полосы над титром")
            drop_schema(scenes, scene)
            continue
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
        # Хостовый id разведён с id внутри копии — та же причина, что у
        # `common` в цикле элементов сцены (см. её комментарий там же):
        # их `inlineSubCompositions.ts` вклеивает копию в тот же
        # документ, и совпадающий `data-composition-id` путал их
        # скоуп-скрипт при повторном seek.
        # Коробка схемы несёт своё имя: мишень `schema` у paste-приёма
        # целится в НЕЁ, а не в сам клип-маунт. Причина измерена живым
        # прогоном (`work/paste-target`, первый заход): класс, повешенный на
        # маунт саб-композиции, в кадре не сработал — их рантайм вклеивает
        # содержимое в тот же документ и узел маунта под собой меняет, а
        # твин GSAP держит ссылку на прежний. Обёртка — наша, её их рантайм
        # не трогает.
        # Плашка читаемости — когда под схемой в этой же сцене лежит настоящая
        # вставка (сток, непредсказуемый по цвету), а не наш управляемый фон
        # (aurora выше или подложка `frame.md`). Корень каждой формы —
        # `background: transparent` (комментарий у них самих — «overlays
        # footage or mk-background»), а строки набраны схемой `dark`
        # (`hf_schema.build`): по умолчанию это верный расчёт на тёмный aurora,
        # но вставка кладёт под текст всё что угодно, вплоть до светлого кадра.
        #
        # Job rb0907-philosophers (прод, 07.09.2026), сцена s-07:
        # `presenter: "none"`, вставка приехала (`ins-s-07-0/1`,
        # `INSERT_RECTS["none"]` — на весь кадр), схема `pairs` легла поверх,
        # и их `contrast_aa_failure` замерил 1.54:1 / 2.9:1 / 1.97:1 у
        # «говори честно» / «не делай» / «не манипулируй» (fg вплоть до
        # rgb(233,222,213) на bg вплоть до rgb(207,175,160)) — настоящая
        # нечитаемость, не ложная находка.
        #
        # `mk-specs-list` несёт свой параметр `scrim` ровно под этот случай
        # («0–1 left-edge dark scrim for readability over footage»), но
        # проверено локальным `hyperframes check` на самой этой копии: их
        # градиент (`rgba(0,0,0,.55) 0% … transparent 62%`) гаснет к правому
        # краю колонки и на полной силе (`scrim: 1`) оставляет «говори честно»
        # и «не манипулируй» на 2.15–2.18:1 — блок, для которого он писан,
        # обычно уже теснее нашего `lineWidth`. У остальных четырёх форм
        # (`mk-progress-stat`, `grid-card-assemble`, `hw-pipeline`,
        # `mk-placeholder-grid`) такого параметра нет вовсе. Поэтому плашку
        # кладёт код — единым слоем на все пять форм разом, а не их частичным
        # градиентом одной формы.
        #
        # Этот слой — тот же `.ovl-scrim`, что уже стоит под накладками без
        # своей подложки (см. выше, `_block_backing().get(...) == "none" and
        # insert_of(scene)`), не второй самодельный: инлайновый ровный
        # `rgba(0,0,0,.6)` на самой коробке схемы (прежняя версия правки)
        # красил ЦЕЛУЮ КОРОБКУ `.ovl` весь ролик от t=0 до конца, а не только
        # окно сцены s-07 — коробка несёт `id`, но не `class="clip"` и не
        # `data-start`/`data-duration`, а комментарий двумя экранами ниже в
        # ЭТОЙ ЖЕ функции (`_stage_overlay`, скрим накладки) объясняет ровно
        # почему это ломает: видимость по времени рантайм держит атрибутом
        # `data-start` (`syncTimedElementVisibility`,
        # `packages/core/src/runtime/init.ts:1921-1923`), не классом и не
        # инлайновым `style`. Подтверждено вживую: скан `seek()` по таймлайну
        # собранной копии `rb0907-philosophers` отдавал тёмный фон на КАЖДОЙ
        # из десяти проверенных точек 0..33.9 с из 34.0, включая t=1 с — за
        # 22 секунды до s-07.
        #
        # Своя полоса дорожек `TRACK_SCHEMA_SCRIM`, не дорожка `TRACK_SCRIM`
        # накладок: смешивать два независимых счётчика ротации на одной
        # полосе — повод для `overlapping_clips_same_track`, который проще не
        # допустить отдельной полосой, чем потом считать. Ротация внутри своей
        # полосы — по той же причине, что у накладок: раз линтер считает
        # дорожку количеством элементов, а не их пересечением, четвёртая
        # схема с настоящей вставкой на одной дорожке дала бы предупреждение
        # даже без наложения по времени.
        if series.get(scene["id"]):
            body.append(
                f'    <div class="ovl-scrim clip"'
                f' id="schema-scrim-{scene["id"]}"'
                f' data-start="{at_start:.4f}"'
                f' data-duration="{at_end - at_start:.4f}"'
                f' data-track-index='
                f'"{TRACK_SCHEMA_SCRIM + staged_schema_scrims % schema_scrim_tracks}"'
                f'></div>')
            staged_schema_scrims += 1
        # Место коробки в кадре — от зоны, а не от нуля. Целая зона (`none` и
        # нижние уголки) даёт прежние `left:0;top:0` знак в знак: масштаб
        # ставится только там, где зона короче полосы схемы, и лишнего
        # атрибута в разметке иначе не появляется. Ужимаем ТРАНСФОРМОМ, а не
        # числами внутри блока: числа у пяти форм свои, а трансформ уносит с
        # собой и кегли подписей — ровно ту читаемость, порог которой считает
        # `SCHEMA_MIN_SCALE`. Точка отсчёта — левый верхний угол, поэтому
        # `left` доводит ужатую коробку до середины кадра.
        place = "left:0;top:0"
        if zone["scale"] < 1:
            place = (f'left:{round(OUT_W * (1 - zone["scale"]) / 2)}px;'
                     f'top:{zone["top"]}px;'
                     f'transform:scale({zone["scale"]});'
                     f'transform-origin:0 0')
        body.append(
            f'    <div class="ovl" id="schema-box-{scene["id"]}">'
            f'<div id="schema-{scene["id"]}" class="clip"'
            f' data-composition-id="{unique}-host"'
            f' data-composition-src="compositions/{unique}.html"'
            f' data-start="{markup_time(start):.4f}"'
            f' data-duration="{markup_time(end) - markup_time(start):.4f}"'
            f' data-track-index="{TRACK_SCHEMA}"'
            f' data-width="{OUT_W}" data-height="{height}"'
            f' style="position:absolute;{place};'
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
        # Хостовый id разведён с id внутри копии — та же причина, что у
        # `common` в цикле элементов сцены (см. её комментарий там же):
        # их `inlineSubCompositions.ts` вклеивает копию в тот же
        # документ, и совпадающий `data-composition-id` путал их
        # скоуп-скрипт при повторном seek.
        body.append(
            f'    <div class="fx"><div data-layout-allow-overflow="true"'
            f' style="position:absolute;'
            f'left:{left}px;top:0;transform:scale({scale:.4f});'
            f'transform-origin:0 0">'
            f'<div id="fx-{order}" class="clip"'
            f' data-layout-allow-overflow="true"'
            f' data-composition-id="{unique}-host"'
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
    #
    # `highlightInk` — отдельный от `primaryColor` цвет: буквы слова, пока под
    # ним стоит плашка `accentColor` (`hf_captions.py`, `--hf-caption-
    # highlight-ink`). Светлый акцент (бирюза, жёлтый) с обычным светлым
    # `ink` даёт контраст ниже их порога 3:1 — их же проверка ловит это уже
    # после сборки (`rb0908-ai-employee`, `contrast_aa_failure`). Акцент
    # агента не трогаем, меняем только эти буквы (`hf_frame.highlight_ink`).
    write_caption_data(public, words=words, duration=duration,
                       brand={"primaryColor": colors["ink"],
                              "accentColor": colors["accent"],
                              "highlightInk": highlight_ink(
                                  colors["ink"], colors["accent"], colors["bg"])})
    body.append(caption_snippet(sdk, public, track_index=TRACK_CAPTION,
                                duration=duration))
    # Приёмы-декораторы — последними в теле: их скрипты обходят
    # `document.querySelectorAll` своего класса один раз на старте, и слова
    # титра к этому моменту уже нарисованы движком выше. Порядок внутри файла
    # тот же, в каком приёмы шли по сценам: тень переменных каждого стоит
    # прямо перед его же скриптом.
    body += [f"    {one}" for one in decorators]
    if decor_code:
        # Твины дописываются в КОРНЕВОЙ таймлайн, уже созданный композицией, а
        # не в свой соседний. Два живых прогона (`work/paste-target`):
        # 1. Внешний `<script src>` в их рантайме исполняется ДО разбора тела
        #    (проба в этом же файле: `readyState=loading stage=0 wrap=0
        #    words=0`), поэтому файл ждёт разбора и шрифтов (`DECOR_BOOT`) —
        #    иначе вешать классы не на что и корневой таймлайн отвечает
        #    `GSAP target … not found` по каждому приёму.
        # 2. Свой соседний таймлайн (`window.__timelines["paste-decor"]`) их
        #    плеер не ведёт: он резолвит КОРНЕВОЙ по документу и связывает
        #    только те дочерние, чей ключ отвечает `data-composition-id` в
        #    разметке (`packages/core/src/runtime/init.ts:1562-1581`,
        #    `resolveRootTimelineFromDocument`/`bindRootTimelineIfAvailable`).
        #    Проба показала: ключ в `window.__timelines` есть, а стиль на
        #    мишени так и не появился ни на одной секунде.
        # Дописанные в тот же объект твины плеер отыгрывает на следующем же
        # seek; их же ручка `__hfForceTimelineRebind` (там же:1590) заодно
        # публикует длительность.
        (public / DECOR_SCRIPT).write_text(
            "(function () {\n"
            "function start() {\n"
            'var tl = (window.__timelines || {})["reel"];\n'
            "if (!tl) return;\n"
            + "\n".join(decor_code)
            # Досыпанный твин сам собой не проявится: их плеер перематывает
            # таймлайн по своему расписанию, и один снимок (`snapshot`,
            # `check --at`) успевает перемотаться ДО того, как файл дождался
            # шрифтов. Принудительный перерасчёт на текущей секунде ставит
            # кадр в то состояние, которое эти твины и описывают.
            + "\ntl.render(tl.time(), false, true);\n"
            + "if (window.__hfForceTimelineRebind)"
            " window.__hfForceTimelineRebind();\n}\n"
            + DECOR_BOOT + "})();\n",
            encoding="utf-8")
        body.append(f'    <script src="{DECOR_SCRIPT}"></script>')

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
    _write_caption_overrides(public)

    # Раскадровку переписываем округлённой: гейт сетки кадров должен судить те
    # времена, что реально встали в композицию, а не те, что назвал агент.
    for scene in scenes:
        scene["startSec"] = _q(scene["startSec"])
        scene["endSec"] = _q(scene["endSec"])
    storyboard["scenes"] = scenes
    (rdir / "storyboard.json").write_text(
        json.dumps(storyboard, ensure_ascii=False, indent=1), encoding="utf-8")
    return target


def _write_caption_overrides(public: Path) -> None:
    """Пустая заглушка `caption-overrides.json` рядом с `index.html`.

    Их рантайм титров сам просит этот файл, как только в композиции есть хоть
    один узел `.caption-group` (`applyCaptionOverrides`,
    `packages/core/src/runtime/captionOverrides.ts:104-107` в клоне), и без
    файла `check --strict` даёт `http_error` «404 loading
    caption-overrides.json» плюс `request_failed` — на `index.html`, то есть
    роняет всю сборку, а не одну позицию. Живой прогон 06.09.2026: четыре
    позиции каталога приносят свою разметку титров (`caption-emoji-pop`,
    `caption-neon-accent`, `caption-pill-karaoke`, `caption-weight-shift`) и
    все четыре падали этой парой находок.

    Пишем ровно то и туда, что пишут их собственные скиллы под ту же
    находку — `[]` рядом с проектом (`skills/faceless-explainer/scripts/
    captions.mjs:199-206`, тем же комментарием «silences the captions
    runtime's 404»). Не перезаписываем уже лежащий файл: правки титров,
    сделанные их студией, наши.
    """
    overrides = Path(public) / "caption-overrides.json"
    if not overrides.exists():
        overrides.write_text("[]\n", encoding="utf-8")


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
