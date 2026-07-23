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
    assert f.endswith("':eval=frame")


def test_flash_сила_и_длительность_настраиваются():
    expr = build_flash_expr([1.0], dur=0.5, strength=0.8)
    assert "0.80*" in expr
    assert "/0.250" in expr  # половина длительности — крыло треугольника


def test_flash_filter_считается_покадрово():
    # регресс: без eval=frame eq вычисляет выражение один раз при инициализации
    # (t=0 -> ноль) и вспышки не видно вовсе
    assert build_flash_filter([2.0]).endswith(":eval=frame")


import pytest


@pytest.mark.slow
def test_flash_реально_поднимает_яркость(tmp_path):
    import re
    import subprocess
    from reels_factory.config import FFMPEG

    src = tmp_path / "src.mp4"
    subprocess.run([FFMPEG, "-y", "-f", "lavfi",
                    "-i", "color=c=gray:size=320x640:rate=30:duration=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
                   check=True, capture_output=True)
    out = tmp_path / "out.mp4"
    subprocess.run([FFMPEG, "-y", "-i", str(src), "-vf", build_flash_filter([2.0]),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
                   check=True, capture_output=True)

    def yavg_at(f, t):
        s = subprocess.run(
            [FFMPEG, "-ss", str(t), "-i", str(f), "-frames:v", "1",
             "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
             "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
        m = re.search(r"YAVG=(\d+(?:\.\d+)?)", s)
        return float(m.group(1))

    base = yavg_at(out, 0.5)
    peak = yavg_at(out, 2.0)
    assert peak > base + 40, f"вспышки не видно: {base} -> {peak}"
