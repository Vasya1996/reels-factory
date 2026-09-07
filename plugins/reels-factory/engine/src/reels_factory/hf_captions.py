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

Правка их файла первая — имя гарнитуры. Компонент зашивает Montserrat и в CSS,
и в измеритель ширины, а поля под шрифт в его контракте данных нет (читаются
только `brand.primaryColor` и `brand.accentColor`). Кириллицу в проекте несут
только Manrope и Unbounded (`hf_fonts.py:25-45`), поэтому имя подменяется в
обоих местах разом — иначе титр мерил бы одну гарнитуру, а рисовал другую. Эта
подмена безопасна как слепой `replace` над ЛЮБОЙ версией их файла: имя шрифта
— единственное, что она трогает, и оно ничего вокруг не ломает, даже если не
совпадёт ни с чем (тогда титр останется на их гарнитуре, не с ошибкой).

Вторая правка — не такая. `caption_word_range`/`caption_segments` выше уже
считают слова титра, но НЕ то, как компонент их РИСУЕТ: перенос длинного слова
по внутреннему дефису на две строки внутри одной подсветки (`.hl-word` без
`white-space`) и подгонка кегля, которая на полу возвращает размер без
проверки ширины, а измеряет `.hl-word`/`.hl-group` без `letter-spacing`,
padding и gap (`assets/caption-highlight.html`, функции `fitFontSize` и
`hfMakeGroups.fits`) — обе дают обрезанное или разъехавшееся слово в кадре
(`rb0907-ai-employee` 3.48с и 32.3с, `rb0907-university` 45.1с). Слепой
`replace`, как у шрифта, здесь не годится: чинится не имя, а тело функции и
CSS-правило, а их реестр отдаёт файл из ветки `main` и меняет его под нами без
предупреждения (см. `VETTED` ниже) — `replace` над чужим текстом, который мы
не видели, либо молча ничего не сделает при малейшем несовпадении (регресс без
единого сообщения об ошибке), либо разрежет чужой код не по границе.
Единственная безопасная точка для правки такого масштаба — файл, который мы
сами пишем и полностью контролируем: `VETTED`. Поэтому `install()` доверяет
их живой версии только пока она несёт `FIT_MARKER` — метку, что у неё это
исправление уже есть; нет метки — используем `VETTED` вместо их файла целиком,
тем же путём, каким уже подстраховались от подмены движка демкой
(`DATA_HOOK`). Так правка доезжает в сборку всегда: либо в живой версии уже
есть наше исправление, либо сборка берёт файл, где оно точно есть.

Третья правка тем же путём (`CONTRAST_MARKER`) — цвет букв слова, ПОКА оно
на плашке подсветки. `--hf-caption-primary` красит слово всегда, а плашка
`--hf-caption-accent` встаёт под него лишь на время подсветки: их компонент
не сверяет эти два цвета друг с другом, и на светлом акценте (бирюза, жёлтый)
буквы того же белого `primary` падают ниже их порога контраста 3:1 для
крупного текста — их же гейт ловит это только ПОСЛЕ сборки
(`rb0908-ai-employee`, `contrast_aa_failure` четыре раза). Что показать на
плашке взамен, решает `hf_frame.highlight_ink` ДО того, как эти данные сюда
попадут (`write_caption_data`, brand.highlightInk); правка этого файла — не
сам расчёт, а место, где брать этот цвет и на какое ровно время его
подставлять (`hfBuild`, timing тех же тегов `.hl-word-bg`, что уже красят
плашку), — то, что их контракт компонента не предусматривает вовсе.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from reels_factory.config import OUT_H, OUT_W, cli_env
from reels_factory.hyperframes_blocks import _HF_VERSION

COMPONENT = "caption-highlight"

#: Куда `hyperframes add` кладёт компонент (registry-item.json: target).
COMPONENT_REL = Path("compositions") / "components" / f"{COMPONENT}.html"

#: Гарнитура компонента и наша замена. Unbounded есть в весе 800 — ровно том,
#: которым компонент рисует слово.
_THEIR_FONT = "Montserrat"
_OUR_FONT = "Unbounded"

#: Знаки, которые снимаются с КРАЁВ слова титра. Распознавание отдаёт слова
#: вместе с пунктуацией предложения («вопросов,», «всё.», «Кому?»), а титр
#: рисует по одному слову — точка или кавычка висит в кадре отдельным хвостом,
#: и на плашке активного слова это видно сразу. В списке только то, что речь
#: разделяет, а не то, что входит в само слово:
#: — по краям снимаем дефис и апостроф, внутри они остаются, поэтому целы
#:   «по-русски» и «д'Артаньян» (край режем, середину не трогаем);
#: — по той же причине цела запятая дробного «2,5» — она внутри слова;
#: — процента, валют и прочих знаков при числе тут нет: «38%» должно остаться
#:   числом, а не превратиться в «38».
_TRIM_CHARS = "".join((
    ".,;:!?…",        # конец фразы и паузы внутри неё
    "\"'«»„“”‘’`´",   # кавычки всех начертаний и апостроф, прилипший к краю
    "()[]{}",         # скобки, которыми расшифровка обрамляет вставки
    "-–—‑",           # дефис и тире, когда они стоят отдельно от слова
    "*_/\\|~",        # разметочный мусор, доезжающий из выравнивания
))

#: Крючок, за который титр берёт наши слова: движок компонента читает данные из
#: `window.__HF_CAPTION__`, а мы кладём их туда первой строкой `captions.js`.
DATA_HOOK = "__HF_CAPTION__"

#: Метка, что у файла уже есть наша подгонка кегля/переноса слова (см. шапку
#: модуля). Имя переменной из `VETTED`, которую мы сами придумали для этого
#: исправления, — совпасть с чем-то чужим ей неоткуда. Метки нет — файл
#: пришёл из их реестра БЕЗ правки, и `install()` меняет его на `VETTED`
#: целиком, тем же способом, каким уже подстрахованы от демо-подмены движка
#: через `DATA_HOOK`.
FIT_MARKER = "WORD_LETTER_SPACING_EM"

#: Та же метка, тем же способом (см. `FIT_MARKER` выше), для второй правки —
#: цвет букв слова на плашке подсветки выбирается по контрасту с акцентом
#: (`hf_frame.highlight_ink`), а не всегда равен `--hf-caption-primary`:
#: светлый акцент (бирюза, жёлтый) топил белые буквы ниже их порога 3:1
#: (`rb0908-ai-employee`, `contrast_aa_failure`). Имя переменной из `VETTED` —
#: своё, придуманное для этой правки, совпасть ему неоткуда.
CONTRAST_MARKER = "HF_HIGHLIGHT_INK"

#: Проверенная копия компонента. Реестр они отдают из ветки `main`
#: (`packages/cli/src/registry/remote.ts:26-27`), кеш живёт сутки — то есть
#: компонент меняется под нами без предупреждения. 11.08.2026 `add` привёз
#: версию, где движок заменён демонстрацией: свои `WORDS` в коде, `__HF_CAPTION__`
#: не читается вовсе. В кадр поехал их демо-текст («DRAG AND DROP», «JUST CODE»),
#: а страница упала на `appendChild` of null. Копия снята с прогона 26, где титр
#: проверен кадрами.
VETTED = Path(__file__).resolve().parents[2] / "assets" / f"{COMPONENT}.html"


def install(rdir) -> Path:
    """Поставить компонент их же командой из их общего реестра.

    Ставим в отдельную папку без `hyperframes.json`: в папке прогона конфиг
    указывает на наш каталог блоков, а компонент субтитров живёт в общем
    реестре. Без конфига CLI берёт реестр по умолчанию.

    Если привезённая версия не читает наши данные ИЛИ не несёт нашей подгонки
    кегля/переноса слова (`FIT_MARKER`) ИЛИ нашей подгонки цвета букв под
    контраст (`CONTRAST_MARKER`), берём проверенную копию: молча показать
    вместо реплик диктора их демо-текст, обрезанное слово или буквы ниже их
    порога контраста — все три хуже, чем взять файл, который мы сами
    проверили.
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
        encoding="utf-8", errors="replace", env=cli_env())
    if not target.exists():
        raise RuntimeError(
            f"компонент субтитров {COMPONENT} не поставился "
            f"({result.returncode}): {(result.stderr or result.stdout)[:400]}")
    fetched = target.read_text(encoding="utf-8")
    missing_data_hook = DATA_HOOK not in fetched
    missing_fit_patch = FIT_MARKER not in fetched
    missing_contrast_patch = CONTRAST_MARKER not in fetched
    if missing_data_hook or missing_fit_patch or missing_contrast_patch:
        if not VETTED.exists():
            missing = (DATA_HOOK if missing_data_hook
                      else FIT_MARKER if missing_fit_patch else CONTRAST_MARKER)
            raise RuntimeError(
                f"их {COMPONENT} без {missing}, а проверенной копии нет в "
                f"{VETTED} — титр показал бы их демо-текст, обрезанное "
                "слово или буквы ниже порога контраста")
        reason = (f"не читает {DATA_HOOK}" if missing_data_hook
                  else "без нашей подгонки кегля/переноса слова"
                  if missing_fit_patch else "без нашей подгонки цвета букв под контраст")
        print(f"компонент {COMPONENT} из их реестра {reason} — "
              "беру проверенную копию движка")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(VETTED, target)
    return target


def stage(rdir) -> Path:
    """Положить компонент в композицию и вернуть путь к нему."""
    rdir = Path(rdir)
    source = install(rdir)
    target = rdir / "public" / COMPONENT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


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

    Разбор куска — общее место с paste-контрактными позициями каталога
    (`hf_compose.paste_fragment`, работа B1.5): обе стороны вставляют готовый
    чужой компонент литералом в композицию, а не саб-композицией — их полка
    сама велит «paste the markup, CSS and script». Своё у титра — то, что
    действительно отличается от позиции каталога:
    - корень ищем явным `selector="#highlight"`: у компонента корень несёт
      `id`, а не класс первым токеном, конвенции paste-позиций реестра он не
      следует;
    - на корень навешиваются атрибуты ТАЙМЛАЙНА (`data-duration`,
      `data-width/height`, `data-track-index`, `data-layout-allow-caption-
      zone`) — титр один на весь ролик и живёт своей длительностью, а не
      длительностью сцены-хоста, как эффект каталога;
    - движок уезжает ОТДЕЛЬНЫМ файлом (`captions.js`), а не литералом в
      композицию, как у paste-позиций: их линтер считает физические строки
      `index.html` (`composition_file_too_large` за 300), и тело скрипта
      компонента одно даёт 608 строк (прогон 13);
    - тени `getVariables()` и переименования класса под уникальный маунт
      (`paste_effect`) титру не нужны — он встаёт единственный раз, повторных
      копий одной и той же позиции в кадре не бывает.

    Внешние ссылки компонента (шрифт с Google Fonts, GSAP с CDN) не переносим:
    они запрещены контрактом композиции, GSAP уже подключён локально, а шрифты
    врезает движок.
    """
    from reels_factory.hf_compose import paste_fragment

    public = Path(public)
    path = public / COMPONENT_REL
    style, root, script = paste_fragment(sdk, public, path,
                                         selector="#highlight")

    root = re.sub(r'data-duration="[^"]*"', f'data-duration="{duration:.4f}"',
                  root, count=1)
    root = root.replace('data-width="1920"', f'data-width="{OUT_W}"')
    root = root.replace('data-height="1080"', f'data-height="{OUT_H}"')
    # Полосу титра мы сами объявляем запретной их гейтом `--caption-zone` с
    # `severity=error` (`hf_render.py`), а слова титра стоят ровно в ней:
    # отступ 620 px от низа, полоса начинается на 998,4. Без пометки
    # требование невыполнимо по построению — сборка держалась только на том,
    # что гейт снимает один кадр `t = duration`, где последняя группа уже
    # погашена (запас 37 мс на боевых данных). `data-layout-allow-caption-zone`
    # — их штатный выход: сборщик кандидатов ищет его через `closest()` и
    # такой текст не отдаёт вовсе
    # (packages/cli/src/commands/layout-audit.browser.js:108-110,1403 на пине
    # 0.7.84), а сама находка проверяет атрибут ещё раз
    # (packages/cli/src/utils/checkPipeline.ts:265).
    root = root.replace('data-composition-id="caption-highlight"',
                        f'data-composition-id="caption-highlight"'
                        f' data-layout-allow-caption-zone="true"'
                        f' data-track-index="{track_index}"')
    if DATA_HOOK not in script:
        raise RuntimeError(
            f"движок титра не читает {DATA_HOOK}: в кадр поедет его "
            "собственный демо-текст вместо реплик диктора. Проверь "
            f"{COMPONENT} — их реестр отдаёт его из ветки main и меняет без "
            "предупреждения")
    data = (public / "caption-data.json").read_text(encoding="utf-8")
    body = script.replace(_THEIR_FONT, _OUR_FONT)
    # Тело `<script>…</script>` кладём в файл без обёртки-тега.
    body = re.sub(r"^\s*<script[^>]*>|</script>\s*$", "", body).strip()
    (public / CAPTION_SCRIPT).write_text(
        f"window.__HF_CAPTION__ = {data};\n{body}\n", encoding="utf-8")
    # `paste_fragment` уже отдаёт стиль С тегами `<style>…</style>` — второй
    # обёртки поверх, в отличие от прежнего кода, здесь не нужно.
    return (f"    {style.replace(_THEIR_FONT, _OUR_FONT)}\n"
            f"    {root}\n"
            f'    <script src="{CAPTION_SCRIPT}"></script>')


def caption_segments(words: list[dict]) -> list[list[dict]]:
    """Слова титра сегментами — ровно так, как их нарисует движок компонента.

    Одно определение на двоих: данные титра (`write_caption_data`) и мишень
    `caption` у paste-приёма (`hf_compose`) обязаны считать слова одинаково,
    иначе класс ляжет не на то слово. Движок рисует по одному `.hl-word-text`
    на слово в порядке этого списка, сегмент за сегментом, и слов-пустышек в
    нём нет: чистка уже прошла.
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

    # Чистим уже после деления: границу сегмента задаёт пауза между словами, а
    # времена от чистки не меняются. Делай мы наоборот — выброшенное слово-тире
    # склеило бы соседние паузы в одну и переставило границу.
    clean = []
    for segment in segments:
        # Слово из одной пунктуации после чистки пустое: его не рисуют, но
        # соседям времена не пересчитываем — они звучат тогда же, когда и
        # звучали, и подсветка остаётся на своих местах.
        left = [dict(word, text=word["text"].strip(_TRIM_CHARS))
                for word in segment]
        left = [word for word in left if word["text"]]
        if left:
            clean.append(left)
    return clean


def caption_word_range(words: list[dict], start: float, end: float,
                       word: str | None = None) -> tuple:
    """Какие по счёту слова титра звучат между `start` и `end`.

    Отдаёт полуинтервал `[первое, за последним)` в том же счёте, в каком
    движок титра расставляет `.hl-word-text`. Пусто — в эти секунды не звучит
    ни одного слова, и вешать приём не на что.

    `word` сужает интервал до ОДНОГО слова — того, что назвал агент. Одно
    определение на двоих остаётся: сцена и без него уже давала интервал
    словами, а не долями секунды, здесь тот же счёт лишь фильтруется по
    тексту. Совпадение — без учёта регистра и краевой пунктуации, тем же
    `_TRIM_CHARS`, которым уже очищено само слово титра (`caption_segments`
    выше). Первое совпадение внутри интервала и берём — так же поступает их
    собственная позиция `marker-highlight` со своей переменной
    `emphasis_word` («First case-insensitive substring match … receives the
    marker», `marker-highlight/registry-item.json`): выбор из нескольких
    одинаковых слов сцены — не наш произвол, а их же конвенция. Слова нет
    среди звучащих в этот интервал — пустой интервал `(0, 0)`, тот же отказ,
    что и при полном отсутствии титра в сцене.
    """
    flat = [word_ for segment in caption_segments(words) for word_ in segment]
    found = [index for index, word_ in enumerate(flat)
             if start - 0.001 <= word_["start"] < end - 0.001]
    if not found:
        return (0, 0)
    if word is None:
        return (found[0], found[-1] + 1)
    needle = str(word).strip(_TRIM_CHARS).lower()
    matched = [index for index in found
              if flat[index]["text"].strip(_TRIM_CHARS).lower() == needle]
    return (matched[0], matched[0] + 1) if matched else (0, 0)


def caption_scene_words(words: list[dict], start: float,
                        end: float) -> list[str]:
    """Слова титра, которые горят в кадре между `start` и `end`, — по порядку
    и приведённые к сравнению (нижний регистр, без краевой пунктуации).

    Счёт тот же, что у `caption_word_range` выше, и живёт он здесь по той же
    причине: какие слова титра принадлежат сцене, решает одно место. Отдаётся
    текст, а не индексы, — спрашивающему (`hf_gates._element_problems`) нужно
    сравнить слова позиции каталога с тем, что зритель в эту же секунду
    читает в титре.
    """
    flat = [word_ for segment in caption_segments(words) for word_ in segment]
    first, last = caption_word_range(words, start, end)
    return [flat[index]["text"].strip(_TRIM_CHARS).lower()
            for index in range(first, last)]


def write_caption_data(public, *, words: list[dict], duration: float,
                       brand: dict | None = None) -> Path:
    """Данные титра в их контракте (`version: 1`, сегменты со словами).

    Титр идёт весь ролик и ни под чем не молчит. Гасить его приходилось, пока
    сцена была непрозрачным блоком со своим текстом: два текста в одном кадре —
    это `content_overlap` и `text_occluded` их же линтера. В слоёном кадре
    своего текста нет ни у вставки, ни у ведущей, а эталонные рилсы держат титр
    непрерывно — «текста в кадре нет ни секунды без».

    Пунктуацию, с которой слова приходят из распознавания, снимаем с краёв
    (`_TRIM_CHARS`): титр показывает слово по одному, и запятая с точкой висят
    в кадре хвостом.
    """
    clean = caption_segments(words)

    payload = {
        "version": 1,
        "resolution": {"width": OUT_W, "height": OUT_H},
        "segments": [{"start": segment[0]["start"],
                      "text": " ".join(word["text"] for word in segment),
                      "words": segment} for segment in clean],
    }
    # Цвета титра — контракт компонента: brand.primaryColor уходит в
    # --hf-caption-primary (цвет слова), brand.accentColor — в плашку
    # активного слова (caption-highlight.html:91, 260-270). Их контракт этими
    # двумя и исчерпан. brand.highlightInk — третье поле, НАШЕ: буквы слова,
    # ПОКА под ним стоит плашка (`hf_frame.highlight_ink`, вызывающий код в
    # `hf_compose.build_composition`) — их компонент этого не умел, светлый
    # акцент топил белые буквы ниже порога 3:1. Значения приходят из frame.md.
    if brand:
        payload["brand"] = brand
    target = Path(public) / "caption-data.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    return target
