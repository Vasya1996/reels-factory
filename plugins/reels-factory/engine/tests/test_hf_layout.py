"""Геометрия вертикального кадра: сетка кадров, безопасные полосы, лицо."""
import pytest

from reels_factory.config import OUT_H, OUT_W
from reels_factory.hf_layout import (
    ALLOWED_ZONES, EFFECT_MIN_HEIGHT, FACELESS_ZONES, FULL_FRAME_PRESENTER,
    PRESENTER_POSITIONS, VIDEO_RECTS, ZONE_RECTS, _overlap, effect_rect,
    face_box, quantize, violations,
)

#: Тот же верх полосы титра, каким его зовёт сборка (`hf_compose.
#: CAPTION_BAND_TOP - CAPTION_BAND_SAFETY`, 1000 - 20). Число не импортируем
#: из `hf_compose`, чтобы тест геометрии не тянул за собой сборку.
_BAND_TOP = 980


def test_раскладки_и_зоны_как_у_скила():
    assert VIDEO_RECTS["overlay"] == {"left": 0, "top": 0, "width": 1080, "height": 1920}
    assert VIDEO_RECTS["stack"]["height"] == 844
    assert VIDEO_RECTS["split"] == {"left": 0, "top": 960, "width": 1080,
                                    "height": 960}
    # PiP берётся из строки «portrait, 9:16 source» их же таблицы: наши клипы
    # вертикальные, и окно 360x203 (строка 16:9) резало бы кадр до полоски глаз.
    assert VIDEO_RECTS["pip"] == {"left": 738, "top": 28, "width": 312,
                                  "height": 555}
    assert {"pip-tl", "pip-tr", "pip-bl", "pip-br"} <= set(VIDEO_RECTS)
    # все пять зон скила разрешены, своих ограничений не вводим
    assert ALLOWED_ZONES == {"video-overlay", "fullscreen", "lower-third",
                             "side-panel", "whiteboard-area"}
    assert set(ZONE_RECTS) == ALLOWED_ZONES
    assert ZONE_RECTS["lower-third"] == {"left": 0, "top": 1344, "width": 1080,
                                         "height": 576}
    assert FACELESS_ZONES == {"fullscreen"}


@pytest.mark.parametrize("value,expected", [
    (0.0, 0.0), (1.0, 1.0), (13.02, 13.033), (13.017, 13.033),
    (41.508, 41.5), (6.017, 6.033),
])
def test_округление_к_сетке_кадров(value, expected):
    assert quantize(value) == pytest.approx(expected, abs=0.001)


def test_содержимое_под_лицом_чисто():
    face = {"cx": 540, "cy": 520, "h": 260}
    assert violations({"left": 60, "top": 1400, "width": 960, "height": 400}, face) == []


def test_карточка_на_лице_ловится():
    face = {"cx": 540, "cy": 520, "h": 260}
    problems = violations({"left": 200, "top": 400, "width": 700, "height": 300}, face)
    assert any("лицо" in p for p in problems)


def test_нижняя_треть_кадра_разрешена():
    """Раньше её запрещала наша выдуманная полоса интерфейса."""
    face = {"cx": 540, "cy": 520, "h": 260}
    assert violations({"left": 0, "top": 1344, "width": 1080, "height": 576}, face) == []


def test_лицо_едет_вместе_с_окном_видео():
    """Раскладка ужала видео в угол — лицо тоже уехало туда."""
    from reels_factory.hf_layout import moved_face

    face = {"cx": 540, "cy": 520, "h": 260}
    в_углу = moved_face(face, VIDEO_RECTS["pip"])
    scale = max(312 / 1080, 555 / 1920)          # вписывание по большей стороне
    offset = 738 + (312 - 1080 * scale) / 2      # cover обрезает по краям
    assert в_углу["cx"] == pytest.approx(offset + 540 * scale)
    assert в_углу["h"] == pytest.approx(260 * scale)
    # там, где лицо было раньше, теперь ставить карточку можно
    assert violations({"left": 200, "top": 400, "width": 700, "height": 300},
                      в_углу) == []


def test_без_лица_проверка_лица_пропускается():
    assert face_box(None) is None


#: Зафиксированные числа зоны элемента-эффекта при каждой позиции ведущей —
#: те же, что подтвердил живой прогон проверки B2 (`review-b2.md`, раздел D).
_EFFECT_RECTS = {
    "full": None,
    "punch": None,
    "pip-tr": {"left": 0, "top": 583, "width": 1080, "height": 397},
    "pip-tl": {"left": 0, "top": 583, "width": 1080, "height": 397},
    "pip-br": {"left": 0, "top": 0, "width": 1080, "height": 980},
    "pip-bl": {"left": 0, "top": 0, "width": 1080, "height": 980},
    "stack": None,
    "none": {"left": 0, "top": 0, "width": 1080, "height": 980},
}


@pytest.mark.parametrize("presenter", PRESENTER_POSITIONS)
def test_зона_эффекта_числом_по_каждой_позиции(presenter):
    assert effect_rect(presenter, band_top=_BAND_TOP) == _EFFECT_RECTS[presenter]


@pytest.mark.parametrize("presenter", PRESENTER_POSITIONS)
def test_зона_эффекта_не_задевает_ведущую_и_полосу_титра_и_держит_пол(presenter):
    """Свойства, а не числа: должны сойтись при любой будущей правке
    `VIDEO_RECTS`, а не только на сегодняшних восьми позициях."""
    rect = effect_rect(presenter, band_top=_BAND_TOP)
    if presenter in FULL_FRAME_PRESENTER:
        assert rect is None
        return
    if rect is None:
        # Пола не хватило (сегодня — только `stack`, 136 px < EFFECT_MIN_HEIGHT).
        return
    # зона внутри кадра
    assert rect["left"] >= 0 and rect["top"] >= 0
    assert rect["left"] + rect["width"] <= OUT_W
    assert rect["top"] + rect["height"] <= OUT_H
    # зона не заходит на полосу титра
    assert rect["top"] + rect["height"] <= _BAND_TOP
    # зона не пересекает окно ведущей
    window = VIDEO_RECTS.get(presenter)
    if window is not None:
        assert not _overlap(rect, window)
    # ширина и высота не ниже пола значка
    assert rect["width"] >= EFFECT_MIN_HEIGHT
    assert rect["height"] >= EFFECT_MIN_HEIGHT


def test_зона_эффекта_снимается_ниже_пола():
    """`stack` оставляет над окном ведущей 136 px — меньше пола в 380 px
    (коробка значка), зоны для эффекта в кадре нет вовсе."""
    free_height = _BAND_TOP - VIDEO_RECTS["stack"]["height"]
    assert free_height < EFFECT_MIN_HEIGHT
    assert effect_rect("stack", band_top=_BAND_TOP) is None
