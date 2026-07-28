"""Геометрия вертикального кадра: сетка кадров, безопасные полосы, лицо."""
import pytest

from reels_factory.hf_layout import (
    ALLOWED_ZONES, FACELESS_ZONES, VIDEO_RECTS, face_box, quantize, violations,
)


def test_раскладки_и_зоны_как_у_скила():
    assert VIDEO_RECTS["overlay"] == {"left": 0, "top": 0, "width": 1080, "height": 1920}
    assert VIDEO_RECTS["stack"]["height"] == 844
    assert len(VIDEO_RECTS) == 4
    # все пять зон скила разрешены, своих ограничений не вводим
    assert ALLOWED_ZONES == {"video-overlay", "fullscreen", "lower-third",
                             "side-panel", "whiteboard-area"}
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
    scale = max(360 / 1080, 203 / 1920)          # вписывание по большей стороне
    assert в_углу["cx"] == pytest.approx(690 + 540 * scale)
    assert в_углу["h"] == pytest.approx(260 * scale)
    # там, где лицо было раньше, теперь ставить карточку можно
    assert violations({"left": 200, "top": 400, "width": 700, "height": 300},
                      в_углу) == []


def test_без_лица_проверка_лица_пропускается():
    assert face_box(None) is None
