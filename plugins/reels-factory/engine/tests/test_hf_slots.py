"""Слоты блока каталога: паспорт для агента и подстановка кодом.

Тесты идут через настоящий мост к их SDK: разбор и правку делает он, и
проверять имеет смысл только то, что получается на выходе целиком.
"""
import re

import pytest

from reels_factory.hf_sdk import sdk_session
from reels_factory.hf_slots import fill_ops, find_slots, passport, prune_timeline

BLOCK = """<!doctype html>
<html><head><title>Заголовок вкладки</title><style>.g99-x{color:red}</style></head>
<body>
  <div id="g99-root" data-composition-id="g99-demo" data-start="0"
       data-width="1080" data-height="1920" data-duration="5">
    <div id="g99-clip" class="clip" data-start="0" data-duration="5">
      <div class="g99-tech"><span class="g99-dash"></span><span class="g99-lbl">Рубрика · Глава</span></div>
      <h1 class="g99-h1">
        <span class="g99-line"><span class="g99-w g99-wa">ПЕРВАЯ</span> <span class="g99-w g99-wa">СТРОКА</span></span>
        <span class="g99-line"><span class="g99-w g99-wa g99-hl"><i></i>ВТОРАЯ СТРОКА</span></span>
      </h1>
      <div class="g99-pill"><span class="g99-idx">01</span><span class="g99-txt">первый пункт</span></div>
      <div class="g99-foot">рукописная ремарка</div>
      <div id="g99-art-slot" class="g99-slot" data-slot="image" data-slot-role="art">
        <span class="g99-sl">Image slot</span></div>
    </div>
  </div>
  <script>window.__timelines["g99-demo"] = tl;</script>
</body></html>"""


@pytest.fixture
def block(tmp_path):
    """Разобранный блок: функция `nodes()` и функция `fill()`."""
    def make(html=BLOCK):
        source = tmp_path / "block.html"
        source.write_text(html, encoding="utf-8")
        return source

    with sdk_session() as sdk:
        state = {"n": 0}

        def nodes(html=BLOCK):
            state["n"] += 1
            name = f"b{state['n']}"
            sdk.open(name, make(html))
            found = sdk.elements(name)
            sdk.close(name)
            return found

        def fill(html=BLOCK, **kwargs):
            state["n"] += 1
            name = f"b{state['n']}"
            sdk.open(name, make(html))
            found = sdk.elements(name)
            sdk.dispatch(name, fill_ops(found, **kwargs))
            out = tmp_path / f"{name}.html"
            sdk.save(name, out)
            sdk.close(name)
            return prune_timeline(out.read_text(encoding="utf-8"), html)

        yield nodes, fill


def test_служебный_текст_страницы_слотом_не_считается(block):
    """`<title>` и `<style>` — тоже текст, но зритель его не видит."""
    nodes, _ = block
    names = [slot.name for slot in find_slots(nodes())]
    assert "Заголовок вкладки" not in " ".join(names)
    assert "title" not in names


def test_строка_с_пословной_анимацией_один_слот(block):
    """Токены слова заполняются целиком строкой, а не по одному."""
    nodes, _ = block
    names = [slot.name for slot in find_slots(nodes())]
    assert "line-1" in names and "line-2" in names
    assert not any(name.startswith("w-") for name in names)


def test_плашка_рубрика_агенту_не_предлагается(block):
    nodes, _ = block
    text = passport(nodes(), name="g99-demo")
    assert "Рубрика · Глава" not in text
    assert "`lbl`" not in text


def test_цифровой_слот_можно_не_заполнять(block):
    nodes, _ = block
    assert "(можно не заполнять)" in passport(nodes(), name="g99-demo")


def test_рубрика_уезжает_вместе_с_обёрткой(block):
    """Убрать одну надпись мало: осталась бы полоска и её отступ."""
    _, fill = block
    out = fill(text={"line-1": "А Б"})
    assert "g99-tech" not in out and "g99-dash" not in out


#: Нижняя плашка перенесённой позиции: «·» стоит РАЗДЕЛИТЕЛЕМ содержания, а
#: не следом нашей плашки-рубрики. Форма — как у девяти `lt-*` каталога
#: (`catalog/registry/blocks/lt-soft-pill/lt-soft-pill.html:84`).
ПЕРЕНЕСЁННАЯ_ПЛАШКА = """<!doctype html>
<html><head><style>.lt-name{color:#000}</style></head>
<body>
  <div id="root" data-composition-id="lt-demo" data-start="0"
       data-width="1920" data-height="1080" data-duration="4.8">
    <div id="lt-clip" class="clip" data-start="0" data-duration="4.8">
      <div id="lt" class="lt">
        <div id="lt-name" class="lt-name">Dr. Maya Chen</div>
        <div id="lt-role" class="lt-role">Host · Neuroscientist</div>
      </div>
    </div>
  </div>
  <script>
    var role = document.getElementById("lt-role");
    window.__timelines["lt-demo"] = tl;
  </script>
</body></html>"""


def test_разделитель_в_перенесённой_позиции_не_считается_рубрикой(block):
    """«Host · Neuroscientist» — вторая строка нижней плашки, а не рубрика.

    Правило `SERVICE_MARK` написано про наши блоки `gNN-*` (там «·» стоит
    только в плашке-рубрике). На девяти `lt-*` оно съедало `#lt-role`: скрипт
    позиции получал на него `null` и на каждом кадре писал «GSAP target null
    not found» — прогон scratchpad/catalog-sweep 05.09.2026, кадр показывал
    плашку с одним словом вместо имени и роли.
    """
    nodes, fill = block
    slots = find_slots(nodes(ПЕРЕНЕСЁННАЯ_ПЛАШКА))
    роль = next(slot for slot in slots if slot.name == "role")
    assert not роль.service, "разделитель содержания принят за плашку-рубрику"
    assert [slot.name for slot in slots if not slot.service] == ["name", "role"]
    out = fill(ПЕРЕНЕСЁННАЯ_ПЛАШКА,
               text={"name": "Артём Крылов", "role": "основатель · продажи"})
    assert 'id="lt-role"' in out and "основатель · продажи" in out
    assert "Neuroscientist" not in out


def test_незаполненный_текст_исчезает_а_не_остаётся_плейсхолдером(block):
    _, fill = block
    out = fill(text={"line-1": "А Б"})
    assert "рукописная ремарка" not in out
    assert "первый пункт" not in out
    # цифра — оформление сцены, её удаление ломало бы раскладку
    assert ">01<" in out


def test_декоративный_слот_в_паспорте_можно_не_заполнять(block):
    """Карточка (`reels.decor_texts`) знает, что «рукописная ремарка» здесь —
    нарисованная надпись, а не заглушка, и паспорт не требует её от агента."""
    nodes, _ = block
    text = passport(nodes(), name="g99-demo", decor={"рукописная ремарка"})
    line = next(l for l in text.splitlines() if "рукописная ремарка" in l)
    assert "можно не заполнять" in line


def test_декоративный_текст_не_считается_обязательным_и_остаётся(block):
    """Отчёт руки B2.5: настоящий SDK-мост удалял «now» и «HF» у
    `v-macos-notification` как незаполненную заглушку. `decor` — тот же список
    `reels.decor_texts`, что читает гейт D22 — говорит `fill_ops` их не
    трогать."""
    _, fill = block
    out = fill(text={"line-1": "А Б"}, decor={"рукописная ремарка"})
    assert "рукописная ремарка" in out


def test_недекоративный_незаполненный_слот_всё_равно_уезжает(block):
    """`decor` защищает только перечисленный текст: слот с другим текстом
    по-прежнему считается незаполненной заглушкой и уезжает из кадра."""
    _, fill = block
    out = fill(text={"line-1": "А Б"}, decor={"совсем другой текст"})
    assert "рукописная ремарка" not in out


def test_подсветка_достаётся_последнему_слову(block):
    _, fill = block
    out = fill(text={"line-2": "РАЗ ДВА ТРИ"})
    assert "РАЗ" in out and "ТРИ" in out
    # пробел между словами — отступом: текстовый узел между спанами их
    # операция вставки положить не даёт, а символ внутри токена попал бы в
    # плашку слова и та стала бы шире слова
    for word in ("РАЗ", "ДВА"):
        assert re.search(rf'margin-right[^>]*>{word}</span>', out)
    assert re.search(r'style="">?<i', out) or "margin-right" not in out.split("ТРИ")[1]
    assert out.count("g99-hl") == 1
    # подсветка — пустой <i> внутри последнего токена; при записи их SDK
    # проставляет ему свою метку, поэтому ищем по концу тега
    assert re.search(r'class="g99-w g99-wa g99-hl"[^>]*><i[^>]*></i>ТРИ', out)


def test_текст_рядом_с_вложенным_элементом_меняется_отдельно(block):
    _, fill = block
    html = BLOCK.replace(
        '<div class="g99-foot">рукописная ремарка</div>',
        '<div class="g99-foot"><span class="g99-sm">сноска</span></div>')
    out = fill(html, text={"line-1": "А", "sm": "мелким"})
    assert ">мелким<" in out


def test_картинка_встаёт_тегом_img_по_расширению(block):
    _, fill = block
    out = fill(media={"art": {"file": ".media/image/a.jpg"}})
    assert re.search(r'<img [^>]*id="g99-art"', out)
    assert 'src=".media/image/a.jpg"' in out
    assert "Image slot" not in out


def test_клип_встаёт_тегом_video_со_смещением(block):
    _, fill = block
    out = fill(media={"art": {"file": "clips/clip-01.mp4", "duration": 3.0,
                              "media_start": 1.5}})
    assert re.search(r'<video [^>]*id="g99-art"', out)
    assert 'data-media-start="1.5000"' in out


def test_пустой_медиаслот_не_остаётся_рамкой(block):
    _, fill = block
    out = fill(text={"line-1": "А"})
    assert "Image slot" not in out and "g99-art-slot" not in out


def test_неизвестное_имя_слота_это_ошибка(block):
    _, fill = block
    with pytest.raises(RuntimeError, match="нет слотов"):
        fill(text={"его-нет": "текст"})


def test_текст_не_попадает_в_пустое_украшение(block):
    """Их setText при единственном дочернем элементе пишет текст внутрь него
    (resolveSingleChildTextTarget, packages/sdk/src/engine/model.ts:338-343):
    на прогоне 13 слова легли внутрь полоски зачёркивания, а заглушка
    «первая формулировка» осталась в кадре."""
    _, fill = block
    html = BLOCK.replace(
        '<div class="g99-foot">рукописная ремарка</div>',
        '<div class="g99-old"><span class="g99-repl">первая формулировка'
        '<span class="g99-strike"></span></span></div>')
    out = fill(html, text={"line-1": "А", "repl": "новые слова"})
    assert "первая формулировка" not in out
    # слова легли в сам слот, а не в полоску; полоска пережила правку пустой
    assert re.search(r'class="g99-repl"[^>]*>новые слова', out)
    assert re.search(r'<span[^>]*class="g99-strike"[^>]*></span>', out)


def test_видео_в_слоте_несёт_класс_clip(block):
    """Без него клип в кадре не появляется вовсе: их `check` сказал это шесть
    раз на прогоне 13 пометкой «к сведению», и мы прошли мимо."""
    _, fill = block
    out = fill(media={"art": {"file": "clips/clip-01.mp4", "duration": 3.0}})
    found = re.search(r'<video [^>]*class="([^"]*)"', out)
    assert found and "clip" in found.group(1).split()


def test_анимация_исчезнувшего_элемента_уходит_из_таймлайна(block):
    """Строка на удалённый селектор пишет «GSAP target not found» покадрово."""
    _, fill = block
    html = BLOCK.replace(
        "<script>window.__timelines",
        '<script>\nfu(".g99-tech",0.0,12);\nfi(".g99-foot",1.0);\n'
        'words(".g99-wa",0.3,0.2);\nwindow.__timelines')
    out = fill(html, text={"line-1": "А Б"})
    assert 'fu(".g99-tech"' not in out          # плашка-рубрика убрана
    assert 'fi(".g99-foot"' not in out          # слот не заполнен
    assert 'words(".g99-wa"' in out             # строка на месте


def test_строку_на_класс_который_рисует_сам_скрипт_не_режут(block):
    """Отчёт B4, живая пересборка: у `v-code-diff` пропала строка
    `return { scene: scene, code: code, gutter: scene.querySelector(".gutter") }`
    — `.gutter` в разметке блока не бывает вовсе, его создаёт сам скрипт, а
    прежнее правило («в разметке нет — значит мёртвая цель») этого не
    различало. Блок падал в рантайме на `parts.code`, и `check --strict`
    возвращал `page_error`.

    Тем же правилом уцелел и шестнадцатеричный цвет: `"#0b0f17"` подходит под
    селектор по id, но в разметке его никогда не было.
    """
    _, fill = block
    html = BLOCK.replace(
        "<script>window.__timelines",
        '<script>\nvar box = { gutter: scene.querySelector(".gutter") };\n'
        'tl.set(".g99-foot", { background: "#0b0f17" });\n'
        'fu(".g99-tech",0.0,12);\nwindow.__timelines')
    out = fill(html, text={"line-1": "А Б"})
    assert '.gutter' in out, "строку про класс из скрипта вырезали"
    assert '"#0b0f17"' not in out, (
        "строка целилась в удалённый .g99-foot — она мёртвая целиком")
    assert 'fu(".g99-tech"' not in out


def _позиция(name: str, subdir: str = "components") -> str:
    from reels_factory.hf_catalog import CATALOG_DIR, REGISTRY_SUBDIR
    return (CATALOG_DIR / REGISTRY_SUBDIR / subdir / name / f"{name}.html"
            ).read_text(encoding="utf-8")


def test_текст_внутри_шаблона_сабкомпозиции_доезжает_до_слотов(block):
    """Разметка портированной позиции лежит внутри `<template>`.

    Наш мост читал её текст голым `document.querySelectorAll` линкдома, а он
    внутрь шаблона не заходит — их же слова, `packages/parsers/src/hfIds.ts:
    136-138`. Каждый узел получал пустой текст, `find_slots` не находил в
    позиции ни одной надписи, и латиница карточки ехала в кадр русского ролика
    нетронутой: `focus-swap.html:189` держит «Shape the idea» литералом.
    Теперь обход тот же, каким ходит их собственный `comp.getElements()`.
    """
    nodes, _ = block
    found = find_slots(nodes(_позиция("focus-swap")))
    assert "Shape the idea" in [slot.placeholder for slot in found]
