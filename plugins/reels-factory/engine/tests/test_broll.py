from reels_factory.broll import (
    FULL, THIRD, SPLIT, THIRD_FRACTION, build_overlay_filter, insert_motion,
)


def test_insert_motion_full_слайд_по_x():
    x, y = insert_motion(FULL, 3.0, 7.0, 1920)
    assert y == "0"
    assert x.startswith("W*")                # заезд с правого края
    assert "pow(1-clip((t-3.000)" in x       # кубический ease входа
    assert "pow(clip((t-6.650)" in x         # выезд начинается за ANIM_S до конца


def test_insert_motion_third_bottom_выдвигается_снизу():
    bh = int(1920 * THIRD_FRACTION) // 2 * 2
    x, y = insert_motion(THIRD, 2.0, 5.0, 1920, pos="bottom")
    assert x == "0"
    assert y.startswith(f"{1920 - bh}+")     # базовая позиция ленты
    assert f"{bh}*pow" in y                  # уезжает на свою высоту вниз


def test_insert_motion_third_top_выдвигается_сверху():
    _, y = insert_motion(THIRD, 2.0, 5.0, 1920, pos="top")
    assert y.startswith("0-")                # уходит за верхний край


def test_insert_motion_split_нижняя_половина():
    half = 1920 // 2 // 2 * 2
    _, y = insert_motion(SPLIT, 2.0, 5.0, 1920)
    assert y.startswith(f"{1920 - half}+")


def test_build_overlay_filter_анимированный_overlay():
    ins = [{"kind": FULL, "start": 3.0, "end": 6.0, "src": "x.mp4"}]
    fc, out = build_overlay_filter(ins, 1080, 1920)
    assert out == "v"
    assert "overlay=x='" in fc               # покадровые координаты, не 0:0
    assert "enable='between(t,3.000,6.000)'" in fc
    assert "fade=t=in" in fc and "alpha=1" in fc
