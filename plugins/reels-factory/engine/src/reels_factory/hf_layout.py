"""Геометрия вертикального кадра 1080x1920.

Прямоугольники раскладок продублированы из справочных файлов скила
talking-head-recut (таблица composition layouts, колонка portrait). Скил
обновляется отдельно от нас, поэтому значения зафиксированы здесь.

Безопасных зон движок не знает вовсе — это наше знание.
"""
from __future__ import annotations

from reels_factory.config import FPS, OUT_H, OUT_W

VIDEO_RECTS = {
    "overlay": {"left": 0, "top": 0, "width": 1080, "height": 1920},
    "stack": {"left": 0, "top": 0, "width": 1080, "height": 844},
    "split": {"left": 0, "top": 960, "width": 1080, "height": 960},
    "pip": {"left": 690, "top": 28, "width": 360, "height": 203},
}

# Все пять зон скила разрешены: своих ограничений поверх его геометрии
# мы не вводим — они однажды уже зажали карточку в центр кадра.
ALLOWED_ZONES = {"video-overlay", "fullscreen", "lower-third",
                 "side-panel", "whiteboard-area"}

# зоны, где ведущей в кадре нет: проверять их на лицо бессмысленно
FACELESS_ZONES = {"fullscreen"}

# запас вокруг центра лица: 0.6 высоты головы в каждую сторону
FACE_MARGIN = 0.6


def quantize(seconds: float) -> float:
    """Округлить время к сетке кадров: движок иначе добавляет до 1/30 секунды."""
    return round(round(float(seconds) * FPS) / FPS, 3)


def face_box(face: dict | None) -> dict | None:
    if not face:
        return None
    cx, cy, h = float(face["cx"]), float(face["cy"]), float(face["h"])
    margin = h * FACE_MARGIN
    return {"left": cx - margin, "top": cy - margin,
            "width": 2 * margin, "height": 2 * margin}


def moved_face(face: dict | None, video_rect: dict | None) -> dict | None:
    """Лицо в координатах кадра, когда раскладка подвинула окно с видео.

    Видео вписывается в своё окно с сохранением пропорций (object-fit: cover),
    поэтому центр лица и высота головы масштабируются одним коэффициентом.
    """
    if not face or not video_rect:
        return face
    rw, rh = float(video_rect["width"]), float(video_rect["height"])
    # object-fit: cover — вписываем по БОЛЬШЕЙ стороне и обрезаем по краям,
    # поэтому кадр смещён центрирующим отступом, иногда отрицательным
    scale = max(rw / OUT_W, rh / OUT_H)
    offset_x = float(video_rect["left"]) + (rw - OUT_W * scale) / 2
    offset_y = float(video_rect["top"]) + (rh - OUT_H * scale) / 2
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
