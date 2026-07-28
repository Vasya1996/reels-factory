"""Задание агенту-сборщику композиции.

Монтажные решения принимает скил HeyGen. Наше дело — сообщить то, чего он
знать не может: вертикальный формат, наш стиль, безопасные полосы, где лицо,
какие тайминги истина и ЧТО показывать. Всё числами, без «сделай красиво».
"""
from __future__ import annotations

from pathlib import Path

from reels_factory.config import FPS, OUT_H, OUT_W
from reels_factory.face_detect import free_bands

STYLE_NAME = "minimal"
FONTS = "Montserrat, Inter"


def _window_block(window: dict, text_by_id: dict, faceless: bool = False) -> str:
    timing = window.get("final_timing") or {}
    effect = window.get("effect") or {}
    variables = (effect.get("hyperframes") or {}).get("variables") or {}
    speech = " ".join(text_by_id.get(pid, "") for pid in window.get("phrase_ids") or [])

    lines = [
        f'### Окно `{window.get("id")}` — {timing.get("start")}–{timing.get("end")} с',
        f'- зона-подсказка от плана: `{window.get("zone")}` (можешь выбрать другую)',
        *(["- **ведущей в кадре нет**: зона обязательно `fullscreen`, "
           "интервал закрыт целиком, без дыр"] if faceless else []),
        f'- что звучит: «{speech.strip()}»',
        *(["- субтитры на этом интервале скрыты"]
          if window.get("caption") == "hidden" else []),
    ]
    if effect.get("type") and effect["type"] != "none":
        lines.append(f'- тип вставки: `{effect["type"]}`')
    block = (effect.get("hyperframes") or {}).get("block")
    if block:
        lines.append(f"- готовый блок: `{block}`")
    title = variables.get("title") or effect.get("title")
    if title:
        lines.append(f"- заголовок: «{title}»")
    items = [str(x) for x in (variables.get("items") or []) if isinstance(x, str)]
    if items:
        lines.append("- пункты: " + "; ".join(f"«{i}»" for i in items))
    if effect.get("type") in (None, "none"):
        lines.append("- вставки нет: показывай ведущую, карточку не рисуй")
    return "\n".join(lines)


def write_brief(rdir, plan: dict, *, face: dict | None, duration: float,
                clips: list[dict] | None = None, media: list[dict] | None = None,
                retry_reason: str | None = None) -> Path:
    """Записать BRIEF.md рядом с материалом. Возвращает путь."""
    rdir = Path(rdir)
    rdir.mkdir(parents=True, exist_ok=True)

    text_by_id = {p["id"]: p.get("text", "") for p in plan.get("phrases") or []}
    # «ведущей нет» — свойство блока, а не окна: тот же признак, что у гейта
    faceless_blocks = {b["index"] for b in (plan.get("blocks") or [])
                       if b.get("avatar_required") is False}
    windows = "\n\n".join(
        _window_block(w, text_by_id,
                      faceless=w.get("block_index") in faceless_blocks)
        for w in plan.get("windows") or []) or "Окон нет."

    bands = "\n".join(
        f'- left={b["left"]}, top={b["top"]}, width={b["width"]}, height={b["height"]}'
        for b in free_bands(face)
    ) or "- свободных полос нет: карточки не ставь"

    face_line = (
        f'**Лицо ведущей:** центр ({face["cx"]}, {face["cy"]}), высота головы '
        f'{face["h"]} px. Карточка, стоящая поверх ведущей, лицо не перекрывает. '
        "Полноэкранных карточек это правило не касается — там ведущей нет."
        if face else "Лицо не найдено — считай запретной среднюю треть кадра."
    )

    clips_block = "\n".join(
        f'- `{c["file"]}` — с {c["start"]:g} с, длительность {c["duration"]:g} с'
        for c in (clips or [])
    ) or "Клипов нет."

    media_block = "\n".join(
        f'- `{item["file"]}` → окно `{item["window_id"]}`: {item["what"]}'
        for item in (media or [])
    ) or "Материала нет."

    retry_block = (
        f"\n## Повторная сборка\n\nПрошлая версия не прошла проверку:\n\n"
        f"{retry_reason}\n\nИсправь именно это.\n"
        if retry_reason else ""
    )

    text = f"""# Задание на сборку композиции
{retry_block}
## Формат

**Кадр:** {OUT_W}×{OUT_H} px, {FPS} кадров/сек.
**Стиль:** `{STYLE_NAME}`.
**Шрифты:** {FONTS}.

## Разработчик на сцене

{face_line}

## Свободные полосы под карточку

Полоса — прямоугольник, где карточка гарантированно не прикроет лицо. Агент
выбирает зону, но если её содержимое влезает в полосу — лучше ставить там.

{bands}

## Тайминги и содержание

Все тайминги привязаны к **пословному выравниванию** (точные границы фраз).
Сетка кадров: 1/30 сек (33 мс на кадр). Стоп-кадры выравниваются на сетку.

{windows}

## Клипы с ведущей

(Если есть — это видео, где можно брать фрагменты вместо нарисованной графики.)

{clips_block}

## Материал для карточек

{media_block}

## Вход и выход

**Вход:** Compose из Revideo API → `storyboard.json`, где каждый фрейм это
объект `{{ "id": "...", "timing": {{...}}, "layers": [{{...}}], "contentRect": {{...}} }}`.

**Выход:** Разбор `storyboard.json`, обновление слоёв, пересчёт координат
под новый стиль — всё на месте. Трогай только `layers` и `fill`.

## Правила

**Не запускай:**
- Облачный рендер (`cloud`, `lambda`, `cloudrun`) — локально только.
- Внешние файлы (CDN, урлы) — только встроенные в комплект.
- Трансформации типа `scale`, `rotate` поверх готовых блоков.
- Лавку опция `useCache` для компиляции.

**Встроенные блоки:** Фабрика знает, как рисовать. Если в задаче для окна
указан готовый `hyperframes.block: "..."`, используй именно его.

**Содержание:** Каждый пункт списка и заголовок карточки — из плана, а не
от фантазии. Пусть плана выполняет уменьшение функционала, но истина в нём.
"""
    path = rdir / "BRIEF.md"
    path.write_text(text, encoding="utf-8")
    return path
