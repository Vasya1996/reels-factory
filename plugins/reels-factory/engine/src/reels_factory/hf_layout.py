"""Геометрия вертикального кадра 1080x1920.

Прямоугольники раскладок продублированы из справочных файлов скила
talking-head-recut (таблица composition layouts, колонка portrait). Скил
обновляется отдельно от нас, поэтому значения зафиксированы здесь.

Безопасных зон движок не знает вовсе — это наше знание.

Кадр собирается слоями: ведущая — обычный клип, вставка — обычный
`<img>`/`<video>` поверх или под ней. Порядок отрисовки держит CSS `z-index`, а
не `data-track-index`: тот у них «display-only; render never reads it»
(packages/core/src/runtime/timeline.ts:599). Словаря позиций у них нет ни в
`/general-video`, ни в блоках реестра, поэтому конкретные прямоугольники — наши.

Зоны карточек (`ZONE_RECTS`, `ALLOWED_ZONES`, `FACELESS_ZONES`) к слоёному кадру
отношения не имеют и остаются здесь ради консольного маршрута `editplan`.
"""
from __future__ import annotations

from reels_factory.config import FPS, OUT_H, OUT_W

#: Окно ведущей. Числа — их таблица раскладок, колонка portrait, строка
#: «9:16 source video» (references/layouts/{overlay,stack,split,pip}.html).
#: Прежнее значение `pip` было взято из строки «16:9 source» (360x203) — под
#: наши вертикальные клипы оно не годится: клип 1080x1920 в таком окне
#: обрезается до полоски глаз.
VIDEO_RECTS = {
    "full": {"left": 0, "top": 0, "width": 1080, "height": 1920},
    "overlay": {"left": 0, "top": 0, "width": 1080, "height": 1920},
    "stack": {"left": 0, "top": 0, "width": 1080, "height": 844},
    "split": {"left": 0, "top": 960, "width": 1080, "height": 960},
    "pip": {"left": 738, "top": 28, "width": 312, "height": 555},
    "pip-tr": {"left": 738, "top": 28, "width": 312, "height": 555},
    "pip-tl": {"left": 30, "top": 28, "width": 312, "height": 555},
    "pip-br": {"left": 738, "top": 1337, "width": 312, "height": 555},
    "pip-bl": {"left": 30, "top": 1337, "width": 312, "height": 555},
    # Наезд на ведущую: то же окно, увеличенное на 16% и сдвинутое так, чтобы
    # голова осталась в верхней трети. Кадр закрывает целиком — окно больше
    # кадра, лишнее срезает `overflow:hidden` обёртки. В эталонных рилсах такой
    # «поп»-наезд стоит в каждой паузе между сценами; у нас пауза шла одним
    # неподвижным планом, и детектор сцен не видел там ни одной смены.
    "punch": {"left": -87, "top": -170, "width": 1254, "height": 2229},
}

#: Куда садится карточка при каждой из пяти зон скила. Числа — его же таблица
#: (talking-head-recut/SKILL.md:181-187), доли пересчитаны на 1080x1920.
ZONE_RECTS = {
    "fullscreen": {"left": 0, "top": 0, "width": 1080, "height": 1920},
    "video-overlay": {"left": 0, "top": 0, "width": 1080, "height": 1920},
    "whiteboard-area": {"left": 40, "top": 528, "width": 1000, "height": 864},
    "lower-third": {"left": 0, "top": 1344, "width": 1080, "height": 576},
    "side-panel": {"left": 0, "top": 1152, "width": 1080, "height": 768},
}

#: Позиции ведущей, которые агент вправе назвать. `overlay` и `pip` из
#: VIDEO_RECTS сюда не входят: первый повторяет `full`, второй — `pip-tr`, и
#: два имени одного прямоугольника агенту только мешают выбирать.
#: `split` (ведущая в нижней половине) снят. В вертикальном кадре её лицо
#: попадает туда же, где идёт титр: `moved_face` переносит центр лица в 1187 px,
#: полоса титра занимает 1040–1300, и гейт D8 «текст на лице» валится всегда.
#: Прогон 15 упёрся в это на первой же сцене со `split`. Верхняя половина
#: (`stack`) такого не даёт — там лицо уезжает в 169 px.
PRESENTER_POSITIONS = ("full", "punch", "pip-tr", "pip-tl", "pip-br", "pip-bl",
                       "stack", "none")

#: Где встаёт вставка при каждой позиции ведущей.
#:
#: Слои кадра статичны: у элемента один `data-track-index` на весь ролик, и
#: поменять порядок по ходу нечем. Значит вставка и ведущая либо не
#: пересекаются вовсе, либо ведущей в этот момент не видно. Отсюда таблица:
#: под `pip-*` и `none` вставка занимает весь кадр (ведущая лежит выше и
#: остаётся видна поверх неё), под `stack` и `split` — ровно ту половину, где
#: ведущей нет. Под `full` и `punch` места для вставки в кадре нет: она бы
#: закрыла собой ведущую.
INSERT_RECTS = {
    "none": {"left": 0, "top": 0, "width": OUT_W, "height": OUT_H},
    "pip-tr": {"left": 0, "top": 0, "width": OUT_W, "height": OUT_H},
    "pip-tl": {"left": 0, "top": 0, "width": OUT_W, "height": OUT_H},
    "pip-br": {"left": 0, "top": 0, "width": OUT_W, "height": OUT_H},
    "pip-bl": {"left": 0, "top": 0, "width": OUT_W, "height": OUT_H},
    "stack": {"left": 0, "top": 844, "width": OUT_W, "height": OUT_H - 844},
}

#: Позиции, при которых ведущая закрывает кадр целиком.
FULL_FRAME_PRESENTER = {"full", "punch", "overlay"}

#: Место значка в кадре — та же геометрия, что у `.icon-spot` в шаблоне
#: (`templates/reel.html`: left 50%, translateX(-50%), 380x380, top 400).
#: Держим её здесь, чтобы код мог спросить «влезет ли значок», не разбирая CSS.
ICON_RECT = {"left": (OUT_W - 380) // 2, "top": 400, "width": 380,
             "height": 380}


#: Пол высоты свободной зоны под элемент-эффект. Числом ниже эффект в кадре
#: читается полосой, а не сценой: 380 px — это ровно та коробка, в которой код
#: рисует значок (`ICON_RECT`), и меньше него в кадр он не ставит ничего.
EFFECT_MIN_HEIGHT = ICON_RECT["height"]


def effect_rect(presenter: str, *, band_top: int) -> dict | None:
    """Свободный прямоугольник кадра под элемент каталога вида `effect`.

    `None` — свободного места нет, и элемент снимается.

    Зону считает код, а не агент: она выводится из двух вещей, которых в плане
    нет, — из окна ведущей (`VIDEO_RECTS`, положение агент называет, пиксели
    наши) и из верха полосы титра (`band_top`, ниже него идут слова субтитров).
    Арифметика та же, что кладёт вставку и схему: вставка занимает то, что
    осталось от ведущей (`INSERT_RECTS`), схема кончается выше полосы титра
    (`hf_schema.SAFE_BOTTOM`). Эффект держит оба ограничения разом.

    Берётся ЦЕЛЫЙ прямоугольник — тот из двух (над окном ведущей и под ним),
    что выше. Резать зону на части незачем: элемент — это одна сабкомпозиция с
    одной коробкой, и половинки ей всё равно не отдать.
    """
    free = {"left": 0, "top": 0, "width": OUT_W, "height": int(band_top)}
    name = str(presenter or "none")
    if name in FULL_FRAME_PRESENTER:
        return None
    rect = VIDEO_RECTS.get(name) if name != "none" else None
    if rect is not None and _overlap(free, rect):
        above = {"left": 0, "top": 0, "width": OUT_W,
                 "height": max(0, int(rect["top"]))}
        under_top = int(rect["top"]) + int(rect["height"])
        under = {"left": 0, "top": under_top, "width": OUT_W,
                 "height": max(0, int(band_top) - under_top)}
        free = above if above["height"] >= under["height"] else under
    if free["height"] < EFFECT_MIN_HEIGHT:
        return None
    return free


def _overlap(a: dict, b: dict) -> bool:
    return (a["left"] < b["left"] + b["width"]
            and b["left"] < a["left"] + a["width"]
            and a["top"] < b["top"] + b["height"]
            and b["top"] < a["top"] + a["height"])


def icon_fits(presenter: str) -> bool:
    """Не сядет ли значок на ведущую при этой раскладке.

    Значок стоит в верхней трети по центру. При ведущей во весь кадр (`full`,
    `punch`) и в верхней половине (`stack`) это ровно её лицо: подложка со
    свечением закрывает голову, и кадр читается как ошибка сборки. Гейт такого
    не ловит — D8 судит текст на лице, а значок это `<img>`, — поэтому решает
    геометрия здесь.

    В углах (`pip-*`) окно ведущей со значком не пересекается, а при `none`
    ведущей в кадре нет вовсе.
    """
    rect = VIDEO_RECTS.get(str(presenter or "none"))
    return rect is None or not _overlap(ICON_RECT, rect)


def insert_rect(presenter: str) -> dict | None:
    """Прямоугольник вставки под названную позицию ведущей.

    `None` — вставку ставить некуда: ведущая занимает весь кадр.
    """
    return INSERT_RECTS.get(presenter)


def fills_frame(presenter: str, has_insert: bool) -> bool:
    """Не беден ли кадр при этой раскладке.

    Чёрного кадра больше не существует: шаблон несёт фирменный фон из
    frame.md (глоу в тон акцента), и сцена без ведущей и без вставки — это
    законная «фоновая сцена»: фон и крупный титр, так выглядят призыв и
    передышка. Бедным остаётся другое: мелкое окно ведущей (`pip-*`) или
    половина кадра (`stack`) на пустом фоне — там пустота читается дырой,
    а не решением.
    """
    if presenter in FULL_FRAME_PRESENTER or presenter == "none":
        return True
    return has_insert and presenter in INSERT_RECTS


# Все пять зон скила (talking-head-recut/SKILL.md:180-188) разрешены: своих
# ограничений поверх его геометрии мы не вводим — они однажды уже зажали
# карточку в центр кадра. Пиксели зоны выводит сам скил, поэтому дублировать
# его таблицу у себя незачем.
ALLOWED_ZONES = {"video-overlay", "fullscreen", "lower-third",
                 "side-panel", "whiteboard-area"}

# Зоны, закрывающие кадр целиком непрозрачной подложкой: ими и закрывается
# интервал, где аватара нет. `video-overlay` тоже во весь кадр, но по контракту
# прозрачен (SKILL.md:625-648), поэтому чёрный кадр под собой не прячет.
FULL_FRAME_ZONES = {"fullscreen"}

# зоны, где ведущей в кадре нет: проверять их на лицо бессмысленно
FACELESS_ZONES = FULL_FRAME_ZONES

# запас вокруг центра лица: 0.6 высоты головы в каждую сторону
FACE_MARGIN = 0.6


def quantize(seconds: float) -> float:
    """Округлить время к сетке кадров: движок иначе добавляет до 1/30 секунды."""
    return round(round(float(seconds) * FPS) / FPS, 3)


def avatar_gaps(clips: list[dict], duration: float) -> list[tuple[float, float]]:
    """Интервалы, где клипа с ведущей нет — под ними чёрный кадр.

    Ведущую заказывают кусками, там где она нужна по смыслу. Считаем от клипов,
    а не от плана монтажа: клипы это факт, план — чужое мнение. Задание агенту и
    гейт закрытия интервалов берут пропуски отсюда, иначе гейт проверял бы не
    то, о чём просили.
    """
    covered = sorted((float(c["start"]), float(c["start"]) + float(c["duration"]))
                     for c in clips or [])
    gaps, cursor = [], 0.0
    for start, end in covered:
        if start - cursor > 1.0 / FPS:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if duration - cursor > 1.0 / FPS:
        gaps.append((cursor, duration))
    return gaps


def in_avatar_gap(start: float, end: float,
                  gaps: list[tuple[float, float]]) -> bool:
    """Попадает ли кусок на пропуск между островами аватара.

    Допуск в кадр обязателен: границы сцен округлены к сетке кадров, а границы
    островов — нет, и на стыке они расходятся на сотые доли секунды. Без допуска
    сцена, кончающаяся ровно там, где начинается пропуск, считалась бы
    попавшей в него и теряла ведущую целиком.
    """
    frame = 1.0 / FPS
    return any(min(end, gap_end) - max(start, gap_start) > frame
               for gap_start, gap_end in gaps)


def face_box(face: dict | None) -> dict | None:
    if not face:
        return None
    cx, cy, h = float(face["cx"]), float(face["cy"]), float(face["h"])
    margin = h * FACE_MARGIN
    return {"left": cx - margin, "top": cy - margin,
            "width": 2 * margin, "height": 2 * margin}


def moved_face(face: dict | None, video_rect: dict | None,
               fit: tuple[float, float] = (0.5, 0.5)) -> dict | None:
    """Лицо в координатах кадра, когда раскладка подвинула окно с видео.

    Видео вписывается в своё окно с сохранением пропорций (object-fit: cover),
    поэтому центр лица и высота головы масштабируются одним коэффициентом.

    `fit` — доли `object-position`, которыми композиция кадрирует клип
    (`hf_compose.crop_position`). По умолчанию середина, как и у самого cover;
    но композиция сдвигает вырез вверх, чтобы в невысоком окне не срезало
    макушку, и лицо в кадре уезжает следом. Считать его по середине, когда
    вырез сдвинут, значит охранять пустое место: гейт «текст не на лице» ищет
    лицо не там, где оно нарисовано.
    """
    if not face or not video_rect:
        return face
    rw, rh = float(video_rect["width"]), float(video_rect["height"])
    # object-fit: cover — вписываем по БОЛЬШЕЙ стороне и обрезаем по краям,
    # а какую именно часть показать, решает object-position
    scale = max(rw / OUT_W, rh / OUT_H)
    offset_x = float(video_rect["left"]) + (rw - OUT_W * scale) * fit[0]
    offset_y = float(video_rect["top"]) + (rh - OUT_H * scale) * fit[1]
    return {"cx": offset_x + float(face["cx"]) * scale,
            "cy": offset_y + float(face["cy"]) * scale,
            "h": float(face["h"]) * scale}


def _intersects(a: dict, b: dict) -> bool:
    return not (
        a["left"] + a["width"] <= b["left"]
        or b["left"] + b["width"] <= a["left"]
        or a["top"] + a["height"] <= b["top"]
        or b["top"] + b["height"] <= a["top"]
    )


def violations(content_rect: dict, face: dict | None) -> list[str]:
    """Нарушения прямоугольника ВИДИМОГО СОДЕРЖИМОГО. Пусто — всё чисто.

    Правило одно: не перекрывать лицо. Всё остальное — дело скила.
    """
    box = face_box(face)
    if box is not None and _intersects(content_rect, box):
        return ["перекрывает лицо ведущей"]
    return []
