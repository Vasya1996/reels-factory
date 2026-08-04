"""Субтитры — их готовым компонентом, а не нашей вёрсткой.

Пословный титр с переезжающей подсветкой у них уже написан: компонент реестра
`caption-highlight` («Red background sweep behind each active word,
TikTok-style»). Он сам разбивает слова на группы до четырёх, сам подгоняет
кегль под ширину кадра, сам строит таймлайн и сам же проверяет себя гейтом.
Ставится командой `npx hyperframes add caption-highlight`, а подключается
вставкой в композицию — так велит их карточка каталога («paste its contents
into your composition», docs/catalog/components/caption-highlight.mdx).

Почему не сабкомпозицией через `data-composition-src`: рантайм переносит в
живой DOM только содержимое `<template>`, а всё, что вне его, включая `<head>`,
выбрасывает (hyperframes-core/references/sub-compositions.md:29-38). Стили
компонента лежат в `<head>` — при таком подключении титр остался бы без
оформления (их же «Pitfall 1», там же:80-96). Вставка сниппетом этой проблемы
не создаёт, а таймлайн компонента движок всё равно перематывает вместе с
главным: соседние таймлайны реестра он ведёт наравне
(`packages/core/src/runtime/player.ts:68-84`).

Единственная правка их файла — имя гарнитуры. Компонент зашивает Montserrat и
в CSS, и в измеритель ширины, а поля под шрифт в его контракте данных нет
(читаются только `brand.primaryColor` и `brand.accentColor`). Кириллицу в
проекте несут только Manrope и Unbounded (`hf_fonts.py:25-45`), поэтому имя
подменяется в обоих местах разом — иначе титр мерил бы одну гарнитуру, а
рисовал другую.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from reels_factory.config import OUT_H, OUT_W
from reels_factory.hyperframes_blocks import _HF_VERSION

COMPONENT = "caption-highlight"

#: Куда `hyperframes add` кладёт компонент (registry-item.json: target).
COMPONENT_REL = Path("compositions") / "components" / f"{COMPONENT}.html"

#: Гарнитура компонента и наша замена. Unbounded есть в весе 800 — ровно том,
#: которым компонент рисует слово.
_THEIR_FONT = "Montserrat"
_OUR_FONT = "Unbounded"

_HEAD_STYLE = re.compile(r"<style>(.*?)</style>", re.S)
_SCRIPT = re.compile(r"<script>\s*\(function \(\).*?</script>", re.S)


def install(rdir) -> Path:
    """Поставить компонент их же командой из их общего реестра.

    Ставим в отдельную папку без `hyperframes.json`: в папке прогона конфиг
    указывает на наш каталог блоков, а компонент субтитров живёт в общем
    реестре. Без конфига CLI берёт реестр по умолчанию.
    """
    rdir = Path(rdir)
    staging = rdir / ".hf-captions"
    target = staging / COMPONENT_REL
    if target.exists():
        return target
    staging.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        f'npx --yes hyperframes@{_HF_VERSION} add {COMPONENT} --no-clipboard',
        cwd=str(staging), shell=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    if not target.exists():
        raise RuntimeError(
            f"компонент субтитров {COMPONENT} не поставился "
            f"({result.returncode}): {(result.stderr or result.stdout)[:400]}")
    return target


def stage(rdir) -> Path:
    """Положить компонент в композицию и вернуть путь к нему."""
    rdir = Path(rdir)
    source = install(rdir)
    target = rdir / "public" / COMPONENT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def _piece(pattern: re.Pattern, html: str, what: str) -> str:
    match = pattern.search(html)
    if not match:
        raise RuntimeError(
            f"в компоненте {COMPONENT} не нашлось {what}; "
            "разметка компонента изменилась — проверь его версию")
    return match.group(1) if match.groups() else match.group(0)


def caption_snippet(sdk, public, *, track_index: int, duration: float) -> str:
    """Готовый кусок композиции: стиль, корень и движок титра.

    Внешние ссылки компонента (шрифт с Google Fonts, GSAP с CDN) не переносим:
    они запрещены контрактом композиции, GSAP уже подключён локально, а шрифты
    врезает движок.
    """
    path = Path(public) / COMPONENT_REL
    html = path.read_text(encoding="utf-8")
    style = _piece(_HEAD_STYLE, html, "блока <style>")
    script = _piece(_SCRIPT, html, "скрипта компонента")
    found = sdk.extract(path, "#highlight")
    if not found:
        raise RuntimeError(
            f"в компоненте {COMPONENT} нет корня #highlight; "
            "разметка компонента изменилась — проверь его версию")
    root = found[0]["outer"]

    root = re.sub(r'data-duration="[^"]*"', f'data-duration="{duration:.4f}"',
                  root, count=1)
    root = root.replace('data-width="1920"', f'data-width="{OUT_W}"')
    root = root.replace('data-height="1080"', f'data-height="{OUT_H}"')
    root = root.replace('data-composition-id="caption-highlight"',
                        f'data-composition-id="caption-highlight"'
                        f' data-track-index="{track_index}"')
    data = (Path(public) / "caption-data.json").read_text(encoding="utf-8")
    return (f"    <style>{style.replace(_THEIR_FONT, _OUR_FONT)}</style>\n"
            f"    {root}\n"
            f"    <script>window.__HF_CAPTION__ = {data};</script>\n"
            f"    {script.replace(_THEIR_FONT, _OUR_FONT)}")


#: Единственная зона их таблицы, которая по контракту оставляет кадр видимым:
#: «full canvas, expects mostly-transparent card» (talking-head-recut/
#: SKILL.md:187). Остальные четыре либо кроют кадр целиком, либо садятся в
#: нижнюю часть — ровно туда, где идёт титр. Под ними титр молчит: иначе он
#: ложится на их текст, и это ровно те `content_overlap` и `text_occluded`,
#: которые находит их же `check`.
CAPTION_ZONE = "video-overlay"


def _muted(card: dict) -> bool:
    """Молчит ли титр под этой карточкой.

    Блок каталога — готовая сцена со своим текстом, где бы он ни стоял, так
    что под ним титр молчит всегда. Из своих карточек агента титр переживает
    только прозрачную `video-overlay`.
    """
    if (card.get("render") or {}).get("kind") == "block":
        return True
    return card.get("zone") != CAPTION_ZONE


def _muted_spans(cards: list[dict]) -> list[tuple[float, float]]:
    return [(float(card["startSec"]), float(card["endSec"]))
            for card in cards if _muted(card)]


def write_caption_data(public, *, words: list[dict], cards: list[dict],
                       duration: float) -> Path:
    """Данные титра в их контракте (`version: 1`, сегменты со словами).

    Слова под непрозрачной карточкой выбрасываем: там своя графика со своим
    текстом, и титр лёг бы поверх неё.
    """
    blocked = _muted_spans(cards)
    kept = []
    for word in words:
        # Слово выбрасываем при ЛЮБОМ пересечении с карточкой, а не по середине.
        # По середине слово на стыке оставалось, компонент держал всю его группу
        # до конца её последнего слова, и титр висел поверх пришедшей сцены —
        # видно на кадре 16,9 с прогона 04.08.
        if any(float(word["start"]) < end and float(word["end"]) > start
               for start, end in blocked):
            continue
        kept.append({"text": word["text"], "start": round(float(word["start"]), 3),
                     "end": round(float(word["end"]), 3)})

    segments, current = [], []
    for word in kept:
        if current and word["start"] - current[-1]["end"] > 0.6:
            segments.append(current)
            current = []
        current.append(word)
    if current:
        segments.append(current)

    payload = {
        "version": 1,
        "resolution": {"width": OUT_W, "height": OUT_H},
        "segments": [{"start": segment[0]["start"],
                      "text": " ".join(word["text"] for word in segment),
                      "words": segment} for segment in segments],
    }
    target = Path(public) / "caption-data.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    return target
