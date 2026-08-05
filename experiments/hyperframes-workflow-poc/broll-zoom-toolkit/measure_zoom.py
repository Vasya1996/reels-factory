# -*- coding: utf-8 -*-
"""Численная проверка зума в готовом ролике.

Подбирает масштаб s, при котором кадр A, увеличенный от центра в s раз, лучше всего
совпадает с кадром B. Сравнение по верхней трети кадра — там статичный интерьер,
а не говорящий человек.

ЗАЧЕМ: глазами зум не проверяется. Спикер сам наклоняется к камере, и на стоп-кадрах
это выглядит как наезд, которого в файле нет. Две версии ролика были сданы с
неработающим зумом именно так.

    python measure_zoom.py video.mp4 --pairs 0.3,3.5 4.5,7.5

Замерять только участки, где в кадре аватар: под b-roll вставками замер бессмыслен.
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


def frame(video, t, size=(540, 960)):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "f.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(video),
                        "-frames:v", "1", "-vf", f"scale={size[0]}:{size[1]}", str(p)], check=True)
        return np.asarray(Image.open(p).convert("L"), dtype=np.float32)


def zoom_center(img, s):
    h, w = img.shape
    ch, cw = int(h / s), int(w / s)
    y0, x0 = (h - ch) // 2, (w - cw) // 2
    crop = Image.fromarray(img[y0:y0 + ch, x0:x0 + cw].astype(np.uint8))
    return np.asarray(crop.resize((w, h), Image.BICUBIC), dtype=np.float32)


def best_scale(video, ta, tb, max_scale=1.30):
    A, B = frame(video, ta), frame(video, tb)
    band = slice(0, A.shape[0] // 3)
    best = None
    for i in range(int((max_scale - 1) * 100) + 1):
        s = 1.0 + i * 0.01
        d = float(np.abs(zoom_center(A, s)[band] - B[band]).mean())
        if best is None or d < best[1]:
            best = (s, d)
    return best


def mean_brightness(video, t):
    """Для проверки вспышек: в момент вспышки средняя яркость подскакивает ~в 2.5 раза."""
    return float(frame(video, t).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--pairs", nargs="+", required=True, help="пары времён вида 0.3,3.5")
    ap.add_argument("--flash-at", nargs="*", default=[], help="моменты вспышек для проверки яркости")
    args = ap.parse_args()

    for pair in args.pairs:
        ta, tb = (float(x) for x in pair.split(","))
        s, d = best_scale(args.video, ta, tb)
        print(f"{ta:6.2f}s -> {tb:6.2f}s : масштаб x{s:.2f} (ошибка {d:.2f})")
    for t in args.flash_at:
        t = float(t)
        print(f"вспышка {t:.2f}s: яркость до {mean_brightness(args.video, t-0.2):.0f}, "
              f"в пике {mean_brightness(args.video, t):.0f}, "
              f"после {mean_brightness(args.video, t+0.2):.0f}")


if __name__ == "__main__":
    main()
