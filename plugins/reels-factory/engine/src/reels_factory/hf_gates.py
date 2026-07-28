"""Проверка раскадровки, которую вернул агент-сборщик.

У скила нет ни безопасных зон, ни понятия лица, ни требования класть тайминги
на сетку кадров. Проверяем сами и до рендера — после рендера чинить дороже.
"""
from __future__ import annotations

from reels_factory.config import FPS
from reels_factory.hf_layout import (
    ALLOWED_ZONES, FACELESS_ZONES, moved_face, quantize, violations,
)


def check_storyboard(storyboard: dict, face: dict | None,
                     faceless_windows: list[dict] | None = None) -> dict:
    """Гейты раскадровки. PASS либо FAIL с перечислением карточек.

    faceless_windows — окна плана, где аватар не заказан. На этих интервалах
    в базе чёрный кадр, и его обязана закрыть полноэкранная карточка. Если
    агент выбрал там другую зону — зритель увидит чёрный экран с плашкой.
    """
    face_bad, grid_bad, zone_bad, shape_bad, cover_bad = [], [], [], [], []

    for card in storyboard.get("cards") or []:
        card_id = card.get("id", "?")

        if card.get("zone") not in ALLOWED_ZONES:
            zone_bad.append(f'{card_id}: зона {card.get("zone")!r} не разрешена')

        for field in ("startSec", "endSec"):
            if field not in card:
                grid_bad.append(f"{card_id}: нет поля {field}")
                continue
            value = float(card[field])
            if abs(value - quantize(value)) > 0.0005:
                grid_bad.append(f"{card_id}: {field}={value} вне сетки кадров")

        rect = card.get("contentRect")
        if not rect:
            shape_bad.append(f"{card_id}: не указан прямоугольник содержимого")
            continue
        # в зоне fullscreen ведущей в кадре нет — проверять её лицо незачем
        if card.get("zone") in FACELESS_ZONES:
            continue
        # лицо живёт внутри видео: если раскладка подвинула или ужала окно,
        # запретный прямоугольник едет вместе с ним
        for problem in violations(rect, moved_face(face, card.get("videoRect"))):
            face_bad.append(f"{card_id}: {problem}")

    frame = 1.0 / FPS
    for window in faceless_windows or []:
        timing = window.get("final_timing") or {}
        start = float(timing.get("start", 0.0))
        end = float(timing.get("end", 0.0))
        # интервал закрывается ЦЕПОЧКОЙ полноэкранных карточек, а не одной:
        # разбить показ на титул и список — нормальное монтажное решение.
        # Допуск в кадр — на зазоры, которые агент оставляет между карточками.
        spans = sorted(
            (float(c.get("startSec", 0)), float(c.get("endSec", 0)))
            for c in storyboard.get("cards") or []
            if c.get("zone") == "fullscreen"
        )
        cursor = start
        for span_start, span_end in spans:
            if span_start <= cursor + frame + 0.001:
                cursor = max(cursor, span_end)
        covered = cursor >= end - frame - 0.001
        if not covered:
            cover_bad.append(
                f'{window["id"]}: интервал {start}–{end} без ведущей не закрыт '
                "полноэкранной карточкой — будет чёрный экран")

    def gate(problems: list[str]) -> str:
        return "PASS" if not problems else "FAIL: " + "; ".join(problems)

    return {"D8_face": gate(face_bad), "D9_frame_grid": gate(grid_bad),
            "D10_zone": gate(zone_bad), "D11_shape": gate(shape_bad),
            "D12_faceless_cover": gate(cover_bad)}
