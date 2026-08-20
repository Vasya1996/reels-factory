"""Замер наездов и вспышек по готовому mp4.

Метод её: подобрать масштаб `s`, при котором кадр в начале плана, увеличенный
в `s` раз, лучше всего совпадает с кадром в конце наезда
(`broll-zoom-toolkit/measure_zoom.py`). Отличие одно — увеличиваем не от
центра, а от той же точки, вокруг которой наезжает композиция: у нас это лицо
по замеру `face.json`.

Зачем вообще мерить: «глазами зум не проверяется — спикер сам наклоняется к
камере, и на стоп-кадрах это выглядит как наезд, которого в файле нет. Две
версии ролика были сданы с неработающим зумом именно так»
(`broll-zoom-toolkit/README.md`, грабля 2).
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from reels_factory.config import FFMPEG

#: Размер, до которого ужимаем кадр перед сравнением. Меньше — быстрее и
#: устойчивее к шуму кодека, деталей для оценки масштаба хватает.
PROBE_W, PROBE_H = 540, 960

#: Насколько замер вправе разойтись с заявленным масштабом. Её допуск:
#: «расхождение ≤0.02» (HANDOFF-BROLL-ZOOM-V6.md, критерии приёмки).
ZOOM_TOLERANCE = 0.02

#: Во сколько раз вспышка поднимает среднюю яркость кадра.


def _frame(mp4, at: float):
    """Кадр ролика в оттенках серого.

    Читаем через cv2, а не Pillow: `opencv-python-headless` и так в базовых
    зависимостях движка (его требует детектор лица), а лишняя зависимость
    ради замера — это лишняя зависимость.
    """
    import cv2
    import numpy as np

    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "f.png"
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-ss", f"{max(0.0, at):.3f}",
             "-i", str(mp4), "-frames:v", "1",
             "-vf", f"scale={PROBE_W}:{PROBE_H}", str(shot)], check=True)
        image = cv2.imread(str(shot), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f"кадр {at:.2f} с не прочитался из {mp4}")
    return image.astype(np.float32)


def _zoom_about(img, scale: float, ox: float, oy: float):
    """Увеличить кадр в `scale` раз вокруг точки (ox, oy) в долях кадра."""
    import cv2
    import numpy as np

    height, width = img.shape
    box_h, box_w = int(height / scale), int(width / scale)
    top = int(round((height - box_h) * oy))
    left = int(round((width - box_w) * ox))
    crop = img[top:top + box_h, left:left + box_w]
    grown = cv2.resize(crop, (width, height), interpolation=cv2.INTER_CUBIC)
    return grown.astype(np.float32)


def _origin(origin: str) -> tuple[float, float]:
    try:
        x, y = origin.replace("%", "").split()
        return float(x) / 100.0, float(y) / 100.0
    except Exception:
        return 0.5, 0.38


def best_scale(mp4, first: float, second: float, origin: str,
               top: float = 1.30) -> tuple[float, float]:
    """Масштаб, при котором первый кадр лучше всего ложится на второй.

    Сравниваем верхнюю треть кадра: там интерьер, а не говорящий человек, —
    её же оговорка.
    """
    import numpy as np

    ox, oy = _origin(origin)
    before, after = _frame(mp4, first), _frame(mp4, second)
    band = slice(0, before.shape[0] // 3)
    best = (1.0, float("inf"))
    for step in range(int((top - 1.0) * 100) + 1):
        scale = 1.0 + step * 0.01
        error = float(np.abs(_zoom_about(before, scale, ox, oy)[band]
                             - after[band]).mean())
        if error < best[1]:
            best = (scale, error)
    return best


def _eased_ratio(plan: dict, first: float, second: float) -> float:
    """Во сколько раз кадр вырастет между двумя моментами наезда.

    Сравнивать с `scale_to / scale_from` нельзя: наезд идёт по `power2.out`,
    и к первому замеру кадр уже тронулся. Ждём отношение масштабов ровно в те
    секунды, в которые снимаем.
    """
    ramp = float(plan["ramp"]) or 1.0
    low, high = float(plan["scale_from"]), float(plan["scale_to"])

    def at(moment: float) -> float:
        part = min(1.0, max(0.0, moment / ramp))
        return low + (high - low) * (1.0 - (1.0 - part) ** 2)

    return at(second) / at(first)


def zoom_gates(mp4, camera: dict | None) -> dict[str, str]:
    """D27 — наезды доехали.

    Вспышку здесь судили гейтом `D26_flash`: он требовал прироста яркости в
    1,35 раза. Снят как невыполнимый по построению — на светлом входе прирост
    упирается в потолок 255. Боевой прогон 3ecf2289: вход 184, пик 243, нужно
    было 248. Вспышку рисует их блок, её видно на кадре, а мерить её
    отношением к уже светлой картинке нечем.

    Ключ был `D25` и совпадал с плановым `D25_empty_frame` (hf_gates.py):
    зумовый вердикт мержится после рендера (hf_render.py) и молча затирал
    проверку пустого кадра в общем `gates.json`.

    Меряются только наезды на большом окне ведущей: в углу 18 % прироста дают
    три пикселя, а под полнокадровой вставкой замер бессмыслен вовсе.
    """
    if not camera:
        return {}
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as error:
        # Не «SKIP, и ладно»: без замера наезды никто не проверит, а глазами
        # их проверять нельзя — это ровно та тихая деградация, из-за которой
        # две версии ролика уехали с мёртвым зумом.
        return {"D27_zoom": f"FAIL: замерить нечем ({error})"}

    origin = str(camera.get("origin") or "50% 38%")
    flashes = [float(at) for at in camera.get("flash") or []]
    # Меряем только полнокадровые наезды: `transform-origin` живёт в
    # координатах видео, а его коробка совпадает с кадром лишь при `full` —
    # в `punch` и `stack` точка отсчёта уезжает, и модель замера перестаёт
    # описывать то, что в файле. Вспышка тоже слепит замер: белый кадр
    # совпадает с любым масштабом.
    pushes = [plan for plan in camera.get("plans") or []
              if plan.get("kind") == "push" and plan.get("position") == "full"
              and not any(float(plan["start"]) - 0.3 <= at
                          <= float(plan["start"]) + float(plan["ramp"]) + 0.3
                          for at in flashes)]
    gates: dict[str, str] = {}

    misses = []
    for plan in pushes:
        offset, tail = 0.08, 0.02
        first = float(plan["start"]) + offset
        second = float(plan["start"]) + float(plan["ramp"]) - tail
        if second <= first:
            continue
        measured, _ = best_scale(mp4, first, second, origin)
        wanted = _eased_ratio(plan, offset, float(plan["ramp"]) - tail)
        if abs(measured - wanted) > ZOOM_TOLERANCE:
            misses.append(f'{plan["start"]:.1f} с: ждали x{wanted:.2f}, '
                          f"в файле x{measured:.2f}")
    if not pushes:
        gates["D27_zoom"] = "PASS: полнокадровых наездов, пригодных к замеру, нет"
    elif misses:
        gates["D27_zoom"] = ("FAIL: наезд не доехал — " + "; ".join(misses))
    else:
        gates["D27_zoom"] = f"PASS: наездов {len(pushes)}, все по замеру"

    return gates


def read_camera(rdir) -> dict | None:
    path = Path(rdir) / "camera.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
