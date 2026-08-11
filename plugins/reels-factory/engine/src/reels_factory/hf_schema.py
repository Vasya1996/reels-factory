"""Схема в кадре: то, что нельзя снять камерой.

Биролл показывает снятое — действие, предмет, руки. Цифру, список шагов, связь
двух понятий и знак бренда камерой не снять, и раньше на их месте стоял
одинокий значок на белом кружке: в кадре это читалось эмблемой, а не сценой.

Здесь четыре формы, и каждую собирает их же блок:

- `stat`  — крупное число с подписью        (`mk-progress-stat`)
- `list`  — список строк                    (`mk-specs-list`)
- `link`  — два-три слова со стрелкой        (`hw-pipeline`)
- `brand` — знак бренда, один или несколько  (`mk-placeholder-grid`)

Форму и содержимое называет агент; какой блок за ней стоит, как он вписан в
вертикаль и каким шрифтом набран — не его забота, ровно как с бироллами.

**Почему блок правится текстом, а не параметрами.** Их `CONFIG` живёт внутри
IIFE, а рантайм заворачивает скрипт блока во вторую
(`packages/core/src/compiler/compositionScoping.ts:575-577`), поэтому снаружи
до него не дотянуться ни `window.CONFIG`, ни присваиванием после блока —
проверено кадром. Их штатный канал параметров (`data-variable-values` +
`getVariables()`, `core/src/runtime/getVariables.ts:1-22`) эти блоки не
используют. Остаётся один законный путь: править копию блока, как мы уже
правим её ради GSAP и слотов.
"""
from __future__ import annotations

import json
import re

from reels_factory.config import OUT_H, OUT_W

#: Формы схемы и блок под каждую.
FORMS = {
    "stat": "mk-progress-stat",
    "list": "mk-specs-list",
    "link": "hw-pipeline",
    "brand": "mk-placeholder-grid",
}

#: Корень каждого блока — по нему прицеливается правило палитры и шрифта.
_ROOTS = {
    "mk-progress-stat": "mk-ps-root",
    "mk-specs-list": "mk-sl-root",
    "hw-pipeline": "hw-pl-root",
    "mk-placeholder-grid": "mk-pg-root",
}

#: Сколько секунд блоку нужно, чтобы досказать свою анимацию. Числа сняты с их
#: же таймлайнов: у `hw-pipeline` узлы въезжают по 1,2 с каждый, у остальных
#: вход и выход занимают фиксированное время. Сцена короче — блок покажет себя
#: недорисованным, и это хуже, чем не показать вовсе.
_MIN_SECONDS = {
    "stat": lambda n: 2.6,
    "list": lambda n: 0.3 + 0.18 * max(0, n - 1) + 1.45,
    "link": lambda n: 0.3 + 1.2 * max(0, n - 1) + 1.3,
    "brand": lambda n: 1.4,
}

#: Сколько элементов форма выдерживает. Больше — блок не влезает в кадр, и его
#: же раскладка разъезжается (проверено: пять узлов дают ширину 1720 px при
#: кадре 1080).
LIMITS = {"stat": 1, "list": 4, "link": 3, "brand": 3}

_CONFIG_HEAD = re.compile(r"var CONFIG = \{")
_DURATION_ATTR = re.compile(r'data-duration="[\d.]+"')
_DURATION_VAR = re.compile(r"\bDUR = [\d.]+")
_STYLE_END = re.compile(r"</style>")

#: Канвас подменяем сплошной заменой литералов: у всех четырёх блоков каждое
#: вхождение 1920 и 1080 — это канвас (CSS, `data-width/height`, `viewBox` и
#: арифметика центрирования в скрипте), проверено грепом по файлам.
_W_LITERAL = re.compile(r"(?<!\d)1920(?!\d)")
_H_LITERAL = re.compile(r"(?<!\d)1080(?!\d)")


def min_seconds(form: str, items: int) -> float:
    """Минимальная длина сцены под форму с таким числом элементов."""
    rule = _MIN_SECONDS.get(form)
    return rule(items) if rule else 0.0


def _config_end(html: str, start: int) -> int:
    """Конец литерала `CONFIG` — по балансу скобок, а не по отступу."""
    depth = 0
    for index in range(start, len(html)):
        char = html[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    raise RuntimeError("в блоке не закрылся литерал CONFIG")


def port_block(html: str, *, duration: float, config: dict,
               css: str = "", patches: tuple = ()) -> str:
    """Их блок в нашем кадре: вертикаль, длительность, содержимое, палитра.

    `config` дописывается ПОСЛЕ литерала одним `Object.assign` — так работают и
    числа, и списки, и пути к файлам. Цвета сюда класть нельзя: их подстановщик
    слотов вырезает строку с шестнадцатеричным кодом, приняв её за мёртвый
    селектор (`hf_slots._QUOTED_SELECTOR`), — поэтому палитра идёт правилом CSS.
    """
    # Их ширина 1920 становится нашей 1080, их высота 1080 — нашей 1920.
    # Через метку, иначе вторая замена переписала бы результат первой.
    html = _W_LITERAL.sub("\x00", html)
    html = _H_LITERAL.sub(str(OUT_H), html)
    html = html.replace("\x00", str(OUT_W))

    html = _DURATION_ATTR.sub(f'data-duration="{duration:.4f}"', html)
    html = _DURATION_VAR.sub(f"DUR = {duration:.4f}", html)

    match = _CONFIG_HEAD.search(html)
    if not match:
        raise RuntimeError("в блоке нет литерала CONFIG — версия изменилась")
    end = _config_end(html, match.end() - 1)
    payload = json.dumps(config, ensure_ascii=False)
    html = (html[:end] + f"\n        CONFIG = Object.assign(CONFIG, {payload});"
            + html[end:])

    for needle, replacement in patches:
        if needle not in html:
            raise RuntimeError(f"в блоке нет места для правки: {needle!r}")
        html = html.replace(needle, replacement, 1)

    if css:
        html = _STYLE_END.sub(css + "\n    </style>", html, count=1)
    return html


def palette_css(block: str, colors: dict) -> str:
    """Правило палитры и шрифта для корня блока.

    Гарнитуру объявляем ДВАЖДЫ — обычным `font-family` и их токеном. Их же
    врезка шрифтов собирает семейства только из объявлений `font-family`
    (`inject-fonts.cjs:93`), и имя, живущее лишь в переменной, она не увидит:
    тогда кириллица уедет в подменный шрифт, а казахские буквы не отрисуются
    вовсе.
    """
    root = _ROOTS.get(block)
    if not root:
        return ""
    ink = colors.get("ink", "#ffffff")
    accent = colors.get("accent", "#ff5a36")
    return (
        f"\n      #{root} {{ font-family: 'Manrope', sans-serif;"
        f" --mk-font: 'Manrope', sans-serif;"
        f" --hw-font-print: 'Manrope', sans-serif;"
        f" --hw-font-script: 'Unbounded', sans-serif;"
        f" --mk-ink: {ink}; --mk-ink-dim: {ink}b3; --mk-ink-dark: {ink};"
        f" --mk-ink-dim-dark: {ink}b3; --mk-accent: {accent};"
        f" --mk-accent-dark: {accent}; --mk-paper: {ink};"
        f" --hw-ink: {ink}; --hw-accent: {accent}; }}"
    )


def _fit_label(text: str, limit: int) -> str:
    """Строка, которая влезет в свою рамку.

    У их списка и у подписи узла стоит `white-space: nowrap`: длинная строка
    не переносится, а уезжает за край кадра, и ни один их гейт этого не видит —
    он меряет рамку элемента, а не текст внутри. Поэтому режем по словам.
    """
    words = str(text or "").split()
    out: list[str] = []
    for word in words:
        candidate = " ".join(out + [word])
        if len(candidate) > limit and out:
            break
        out.append(word)
    return " ".join(out) or str(text or "")[:limit]


#: Ширина буквы относительно кегля у Manrope — по ней считается, влезет ли
#: подпись в коробку узла. Мерить точнее незачем: числа идут в геометрию блока
#: с запасом.
_GLYPH_RATIO = 0.55


#: Их раскладчик плиток знает только ландшафтные наборы: `2up` это две колонки,
#: `3up` — три. В вертикали нужны строки, а под один знак — вообще одна ячейка;
#: своего набора у них нет, поэтому дописываем три ветки рядом с их же.
#: Пустых ячеек это заодно избегает: цикл у них идёт по прямоугольникам
#: раскладки, а не по картинкам, и лишний прямоугольник рисуется «лункой» с
#: номером — на прогоне это был бы пустой квадрат с цифрой 2.
_GRID_DISPATCH = ('if (layout === "3up") return grid(3, 1);',
                  'if (layout === "1up") return grid(1, 1);\n'
                  '          if (layout === "2down") return grid(1, 2);\n'
                  '          if (layout === "3down") return grid(1, 3);\n'
                  '          if (layout === "3up") return grid(3, 1);')


def build(form: str, content: dict, *, duration: float, colors: dict,
          files: dict | None = None) -> tuple[str, dict, str, tuple]:
    """Что подставить в блок под названную агентом форму.

    Возвращает `(имя блока, CONFIG-довесок, правило CSS, правки текста)`.
    Геометрия считается от кадра: у их блоков она задана числами под ландшафт,
    и в вертикали их раскладка разъезжается.
    """
    block = FORMS[form]
    files = files or {}
    css = palette_css(block, colors)

    if form == "stat":
        value = str(content.get("value") or "").strip()
        number = re.sub(r"[^\d]", "", value) or "0"
        suffix = value[len(number):].strip() or ""
        config = {
            "scheme": "dark", "value": int(number), "suffix": suffix,
            "max": int(number) or 1,
            "label": _fit_label(content.get("label"), 28),
            "caption": "",
            "trackWidth": 620,
            "x": 120, "y": round(OUT_H * 0.34),
        }
        return block, config, css, ()

    if form == "list":
        rows = [{"label": _fit_label(row, 30), "value": ""}
                for row in (content.get("items") or [])[:LIMITS["list"]]]
        config = {"scheme": "dark", "rows": rows, "underline": True,
                  "lineWidth": OUT_W - 240, "scrim": 0,
                  "x": 120, "rowGap": 56}
        return block, config, css, ()

    if form == "link":
        nodes = [_fit_label(node, 14)
                 for node in (content.get("nodes") or [])[:LIMITS["link"]]]
        count = max(1, len(nodes))
        font = 46
        longest = max((len(node) for node in nodes), default=8)
        box = min(360, max(220, round(longest * font * _GLYPH_RATIO) + 60))
        gap = 70
        while count * box + (count - 1) * gap > OUT_W - 80 and box > 180:
            box -= 20
        config = {
            "nodes": [{"label": node} for node in nodes],
            "boxW": box, "boxH": 150, "gap": gap,
            "y": round(OUT_H * 0.42), "fontSize": font,
        }
        return block, config, css, ()

    # brand — знак бренда крупно, несколько знаков столбиком
    cells = [{"src": src, "insideScale": 0.62}
             for src in (content.get("files") or [])[:LIMITS["brand"]]]
    layout = {1: "1up", 2: "2down", 3: "3down"}.get(len(cells), "1up")
    config = {"layout": layout, "cells": cells, "margin": 120, "gap": 40,
              "radius": 40, "kenBurns": False}
    # Их раскладчик считает сетку по своим W/H, а не по корню, поэтому полосу
    # ставим сами: знак бренда живёт в середине кадра, а не во весь рост.
    band = round(OUT_H * (0.30 + 0.14 * len(cells)))
    css += (f"\n      #mk-pg-grid {{ position: absolute; left: 0;"
            f" top: {round((OUT_H - band) / 2)}px; width: {OUT_W}px;"
            f" height: {band}px; }}"
            f"\n      .mk-pg-media {{ object-fit: contain; padding: 48px; }}")
    # Раскладчик считает прямоугольники по своим W/H — это не размер кадра, а
    # размер полосы, в которой стоят плитки. Подмена канваса делает их равными
    # кадру, поэтому высоту возвращаем к полосе.
    return block, config, css, (_GRID_DISPATCH, (f"H = {OUT_H},",
                                                 f"H = {band},"))
