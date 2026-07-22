from reels_factory.transitions import build_flash_expr, build_flash_filter


def test_flash_expr_треугольник_вокруг_каждой_точки():
    expr = build_flash_expr([3.0, 15.5])
    assert "abs(t-3.000)" in expr
    assert "abs(t-15.500)" in expr
    assert "max(0," in expr  # вне окна терм равен нулю


def test_flash_filter_пустой_без_времён():
    assert build_flash_filter([]) == ""


def test_flash_filter_обёрнут_в_eq_brightness():
    f = build_flash_filter([2.0])
    assert f.startswith("eq=brightness='")
    assert f.endswith("'")


def test_flash_сила_и_длительность_настраиваются():
    expr = build_flash_expr([1.0], dur=0.5, strength=0.8)
    assert "0.80*" in expr
    assert "/0.250" in expr  # половина длительности — крыло треугольника
