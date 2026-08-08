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


#: Куда уезжают данные титра и движок компонента. Отдельным файлом, а не
#: строками в композиции: их линтер считает физические строки `index.html` и
#: за 300 даёт предупреждение `composition_file_too_large`
#: (packages/lint/src/rules/composition.ts:16,379). В прогоне 13 их вышло 684,
#: из них 608 — этот скрипт и его данные, а под `--strict` предупреждение
#: роняет сборку. Тело `<style>` линтер из счёта выбрасывает
#: (`countStructuralLines`, там же:82-84), поэтому стиль остаётся на месте.
CAPTION_SCRIPT = "captions.js"


def caption_snippet(sdk, public, *, track_index: int, duration: float) -> str:
    """Готовый кусок композиции: стиль, корень и ссылка на движок титра.

    Внешние ссылки компонента (шрифт с Google Fonts, GSAP с CDN) не переносим:
    они запрещены контрактом композиции, GSAP уже подключён локально, а шрифты
    врезает движок.
    """
    public = Path(public)
    path = public / COMPONENT_REL
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
    data = (public / "caption-data.json").read_text(encoding="utf-8")
    body = script.replace(_THEIR_FONT, _OUR_FONT)
    # Тело `<script>…</script>` кладём в файл без обёртки-тега.
    body = re.sub(r"^\s*<script>|</script>\s*$", "", body).strip()
    (public / CAPTION_SCRIPT).write_text(
        f"window.__HF_CAPTION__ = {data};\n{body}\n", encoding="utf-8")
    return (f"    <style>{style.replace(_THEIR_FONT, _OUR_FONT)}</style>\n"
            f"    {root}\n"
            f'    <script src="{CAPTION_SCRIPT}"></script>')


def write_caption_data(public, *, words: list[dict], duration: float,
                       brand: dict | None = None) -> Path:
    """Данные титра в их контракте (`version: 1`, сегменты со словами).

    Титр идёт весь ролик и ни под чем не молчит. Гасить его приходилось, пока
    сцена была непрозрачным блоком со своим текстом: два текста в одном кадре —
    это `content_overlap` и `text_occluded` их же линтера. В слоёном кадре
    своего текста нет ни у вставки, ни у ведущей, а эталонные рилсы держат титр
    непрерывно — «текста в кадре нет ни секунды без».
    """
    kept = [{"text": word["text"], "start": round(float(word["start"]), 3),
             "end": round(float(word["end"]), 3)} for word in words]

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
    # Цвета титра — контракт компонента: brand.primaryColor уходит в
    # --hf-caption-primary (цвет слова), brand.accentColor — в плашку
    # активного слова (caption-highlight.html:91, 260-270). Других цветовых
    # полей у компонента нет. Значения приходят из frame.md.
    if brand:
        payload["brand"] = brand
    target = Path(public) / "caption-data.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    return target
