"""Схема в кадре: их блок, вписанный в вертикаль нашим кодом."""
import json
import re

import pytest

from reels_factory.hf_schema import (
    FORMS, ICONS, LIMITS, SAFE_BOTTOM, build, date_variables, min_seconds,
    palette_css, port_block,
)
from reels_factory.hf_schema import _is_dateline

#: Скелет их блока — ровно те места, которые правит перенос: канвас в CSS и в
#: data-атрибутах, длительность в двух видах, литерал CONFIG и арифметика
#: центрирования по числам кадра.
BLOCK = """<!doctype html><html><head><style>
      #mk-ps-root { width: 1920px; height: 1080px; --mk-font: "Inter"; }
    </style></head><body>
  <div id="mk-ps-root" data-composition-id="mk-progress-stat"
       data-duration="7" data-width="1920" data-height="1080">
    <div id="mk-ps-num"></div>
  </div>
  <script>
    (function () {
        var CONFIG = {
          value: 22,
          suffix: "",
          label: "Goals reached",
          x: null
        };
        var DUR = 7;
        var left = (1920 - rect.width) / 2;
        var top = (1080 - rect.height) / 2;
    })();
  </script>
</body></html>"""


def _ported(**over):
    args = {"duration": 3.5, "config": {"value": 87, "label": "дошли"},
            "css": ""}
    args.update(over)
    return port_block(BLOCK, **args)


def test_канвас_переворачивается_целиком():
    """У всех четырёх блоков каждое вхождение 1920 и 1080 — это канвас: CSS,
    data-атрибуты, viewBox и арифметика центрирования в скрипте."""
    html = _ported()
    assert "width: 1080px; height: 1920px" in html
    assert 'data-width="1080" data-height="1920"' in html
    assert "(1080 - rect.width)" in html and "(1920 - rect.height)" in html
    assert "1920px" not in html.split("height:")[0]


def test_длительность_равна_сцене():
    html = _ported(duration=4.25)
    assert 'data-duration="4.2500"' in html
    assert "DUR = 4.2500" in html


def test_содержимое_дописывается_после_литерала():
    """Их `CONFIG` живёт внутри IIFE, а рантайм заворачивает скрипт во вторую
    (`compositionScoping.ts:575-577`): снаружи до него не дотянуться ни
    `window.CONFIG`, ни присваиванием после блока — проверено кадром."""
    html = _ported(config={"value": 87, "label": "дошли до конца"})
    assert "CONFIG = Object.assign(CONFIG," in html
    payload = re.search(r"Object\.assign\(CONFIG, (\{.*?\})\);", html, re.S)
    assert json.loads(payload.group(1))["label"] == "дошли до конца"
    # довесок стоит ПОСЛЕ литерала, иначе их же объявление его затрёт
    assert html.index("value: 22") < html.index("Object.assign")


def test_палитра_идёт_правилом_css_а_не_настройкой():
    """`hf_slots.prune_timeline` вырезает строку с шестнадцатеричным кодом,
    приняв её за мёртвый селектор, — цвет в настройках блока молча исчез бы."""
    css = palette_css("mk-progress-stat", {"ink": "#ffffff",
                                           "accent": "#ff5a36"})
    html = _ported(css=css)
    assert "--mk-accent: #ff5a36" in html
    assert "</style>" in html and html.index("--mk-accent") < html.index("</style>")


def test_гарнитура_объявлена_дважды():
    """Их врезка шрифтов собирает семейства только из объявлений `font-family`
    (`inject-fonts.cjs:93`); имя, живущее лишь в их переменной, она не увидит,
    и кириллица уедет в подменный шрифт."""
    css = palette_css("mk-specs-list", {"ink": "#fff", "accent": "#f00"})
    assert "font-family: 'Manrope'" in css
    assert "--mk-font: 'Manrope'" in css


def test_правка_текста_блока_обязана_найти_своё_место():
    with pytest.raises(RuntimeError, match="нет места"):
        _ported(patches=(("такого текста в блоке нет", "…"),))


# ---------- формы ----------

def test_у_каждой_формы_есть_блок():
    assert set(FORMS) == {"metric", "items", "pairs", "steps", "brand"}
    assert FORMS["steps"] == "hw-pipeline"
    assert FORMS["items"] == "grid-card-assemble"


def test_цифра_разбирается_на_число_и_суффикс():
    block, config, _, _ = build("metric", {"value": "87%", "label": "дошли"},
                                duration=4.0, colors={})
    assert block == "mk-progress-stat"
    assert config["value"] == 87 and config["suffix"] == "%"


def test_величина_без_базы_рисуется_без_полосы():
    """Полоса наливается value/max и читается «столько из стольких». Когда
    базы нет, залитая доверху полоса обещает долю, которой не существует, —
    ровно так «три вопроса» превращались в «три из ста»."""
    _, _, css, _ = build("metric", {"value": "250000", "label": "выручка"},
                         duration=4.0, colors={})
    assert "#mk-ps-track { display: none; }" in css
    _, config, css, _ = build("metric", {"value": "8", "base": 10,
                                         "label": "бросают"},
                              duration=4.0, colors={})
    assert config["max"] == 10
    assert "#mk-ps-track { display: none; }" not in css


def test_величина_без_цифры_не_превращается_в_ноль():
    """Их счётчик печатает `Math.round(значение) + суффикс`: «десятки» прежде
    молча становились нулём в кадре."""
    with pytest.raises(ValueError, match="не начинается с цифры"):
        build("metric", {"value": "десятки", "label": "клиентов"},
              duration=4.0, colors={})


def test_длинная_подпись_режется_по_словам():
    """У их списка и подписи узла стоит `white-space: nowrap`: строка не
    переносится, а уезжает за край кадра, и ни один их гейт этого не видит —
    он меряет рамку элемента, а не текст внутри."""
    _, config, _, _ = build(
        "pairs", {"rows": [{"label": "Claude и длинные документы с таблицами",
                            "value": "берёт целиком"}]},
        duration=4.0, colors={})
    assert len(config["rows"][0]["label"]) <= 22
    assert config["rows"][0]["label"].split()[0] == "Claude"


def test_строка_без_значения_не_рисует_пустую_линию():
    """Их блок — «specs checklist», строка это пара «свойство → значение».
    Половина пары оставляла в кадре незаполненную анкету."""
    with pytest.raises(ValueError, match="без значения"):
        build("pairs", {"rows": [{"label": "скрипты", "value": ""}]},
              duration=4.0, colors={})


def test_перечисление_несёт_свои_значки():
    """Их шесть заготовок крутятся по номеру карточки и смысла не несут
    (`grid-card-assemble.html:256`), а их же контракт разрешает положить свои
    карточки в слот (`:45-51`)."""
    block, variables, _, patches = build(
        "items", {"items": [{"label": "три вопроса", "icon": "вопрос"}]},
        duration=4.0, colors={})
    assert block == "grid-card-assemble"
    assert variables["layout"] == "list"
    assert variables["items"] == "ТРИ ВОПРОСА"
    slot = dict(patches)['<div class="gca-stage" data-slot="items" role="list"></div>']
    assert ICONS["вопрос"][0] in slot and "gca-icon" in slot


def test_упругому_блоку_высоту_режут_на_его_корне():
    """Их загрузчик читает `data-height` у корня блока и ею же переписывает и
    атрибут, и инлайновую высоту хоста
    (`packages/core/src/runtime/compositionLoader.ts:516-524`). Пока корень
    говорил 1920, обрезанный до 980 хост распрямлялся обратно во весь кадр, и
    третья карточка ложилась на слова титра (их `content_overlap` на
    `div.gca-label`, рамка 1260..1292 при пороге 980)."""
    elastic = ('<div id="root" data-composition-id="grid-card-assemble"'
               ' data-duration="4.5" data-width="1080" data-height="1920">'
               "</div>")
    html = port_block(elastic, duration=3.0, config={}, elastic=True,
                      height=SAFE_BOTTOM)
    assert f'data-height="{SAFE_BOTTOM}"' in html
    assert 'data-height="1920"' not in html
    # канвас упругому не подменяют: ширину и прочие числа не трогаем
    assert 'data-width="1080"' in html


def test_упругому_блоку_режут_только_корень_а_не_весь_файл():
    """У настоящего блока `data-height` встречается не только на корне:
    `gallery-tunnel.html:68` несёт тот же атрибут ещё раз — в примере
    использования внутри HTML-комментария, ДО настоящего корня. Слепая замена
    по всему файлу переписала бы и его; здесь корень найден отдельно —
    комментарий рядом остаётся как был."""
    elastic = (
        "<!-- copy me:\n"
        '  <div data-composition-id="gt" data-width="1920" data-height="1080">'
        "</div>\n"
        "-->\n"
        '<div id="gt-root" data-composition-id="gt" data-duration="4.5"'
        ' data-width="1080" data-height="1920"></div>'
    )
    html = port_block(elastic, duration=3.0, config={}, elastic=True,
                      height=SAFE_BOTTOM)
    assert 'id="gt-root"' in html
    assert f'data-height="{SAFE_BOTTOM}"></div>' in html.split("-->")[1]
    # вне корня (в комментарии) число осталось нетронутым
    assert 'data-height="1080"' in html.split("-->")[0]


def test_перечисление_не_длиннее_предела():
    _, variables, _, _ = build(
        "items", {"items": [{"label": c, "icon": "цель"} for c in "абвгде"]},
        duration=4.0, colors={})
    assert len(variables["items"].split(",")) == LIMITS["items"]


def test_узлы_связи_влезают_в_кадр():
    """Их раскладка считает ширину ряда как n·boxW + (n−1)·gap: на их числах
    три узла дают 1340 px при кадре 1080."""
    _, config, _, _ = build("steps", {"nodes": ["заявка", "звонок", "сделка"]},
                            duration=5.0, colors={})
    total = 3 * config["boxW"] + 2 * config["gap"]
    assert total <= 1080 - 80


def test_знак_бренда_один_ставится_одной_ячейкой():
    """Их цикл идёт по прямоугольникам раскладки, а не по картинкам: лишний
    прямоугольник рисуется «лункой» с номером — пустым квадратом в кадре."""
    _, config, css, patches = build("brand", {"files": [".media/a.svg"]},
                                    duration=3.0, colors={})
    assert config["layout"] == "1up"
    assert len(config["cells"]) == 1
    assert any("1up" in patch[1] for patch in patches)
    assert "object-fit: contain" in css


def test_форме_нужна_своя_длина():
    """Числа сняты с их таймлайнов: три узла въезжают по 1,2 с каждый."""
    assert min_seconds("steps", 3) > min_seconds("steps", 2)
    assert min_seconds("metric", 1) == 2.6


#: Тот же регексп на твин счёта, что и в проваленном первом расследовании —
#: применяем его и к сырому шаблону, и к патчу, который `build()` в него
#: вписывает: разойдись любой из двух с другим, тест ловит это первым.
_COUNT_TWEEN_RE = re.compile(
    r"v:\s*CONFIG\.value,\s*duration:\s*([\d.]+).*?\n\s*\},\s*\n\s*"
    r"([\d.]+),\s*\n\s*\);", re.S)


def _count_tween(text):
    match = _COUNT_TWEEN_RE.search(text)
    assert match, "твин счёта не найден — сверь регексп со свежим текстом"
    return float(match.group(1)), float(match.group(2))  # duration, start


def _fade_offset(html):
    fade = re.search(r"duration:\s*[\d.]+,\s*ease:\s*\"power2\.in\"\s*\},\s*"
                     r"DUR\s*-\s*([\d.]+)\);", html)
    assert fade, "угасание не найдено — сверь регексп со свежим шаблоном"
    return float(fade.group(1))


def test_счёт_величины_читает_базовые_числа_из_их_шаблона():
    """Их твин считает `CONFIG.value` со стартом 0,5 с и длительностью 1,6 с
    (`mk-progress-stat.html:161-172`), не зная длины сцены — это и была
    причина дефекта rb0907-university (сцена `s-21`, 07.09.2026): твин
    кончается РОВНО на 2,1 с (гарантия GSAP) при ЛЮБОЙ длине сцены, и старый
    пол `metric` (2,6 с) не оставлял между этим мигом и угасанием
    (`DUR - 0,5`) ни одной секунды. Первая правка подняла пол числом (3,1 с)
    — лечила симптом, не причину, и не различала дату (ей отсчёт не нужен
    вовсе) и количество. Правка ниже масштабирует старт и длительность самого
    твина под длину сцены (`_count_timing`), и пол вернулся к 2,6 с. Этот тест
    читает базовые числа прямо из их шаблона, а не дублирует их литералом:
    разойдись шаблон с кодом, тест поймает это первым, а не рендер на проде."""
    from reels_factory.hf_catalog import CATALOG_DIR
    from reels_factory.hf_schema import _COUNT_DURATION_BASE, _COUNT_START_BASE

    html = (CATALOG_DIR / "registry" / "blocks" / "mk-progress-stat"
            / "mk-progress-stat.html").read_text(encoding="utf-8")
    count_duration, count_start = _count_tween(html)
    assert count_duration == _COUNT_DURATION_BASE
    assert count_start == _COUNT_START_BASE


@pytest.mark.parametrize("duration", [2.6, 6.0])
def test_счёт_количества_укладывается_в_долю_сцены_и_держится_до_угасания(duration):
    """Для пола формы (2,6 с) и заметно более длинной сцены (6 с) счёт обязан
    закончиться не позже 40 % длины сцены и оставить хотя бы 0,4 с до
    угасания — тем же приёмом масштабирования, что у их `count-up`
    (`root.dataset.duration`, `count-up.html:222-232`), но без масштабирования
    ВВЕРХ: на 6 с твин остаётся тем же, что и в их шаблоне (2,1 с < 40% от 6),
    длинная сцена просто держит готовое число дольше, а не считает его
    дольше."""
    from reels_factory.hf_catalog import CATALOG_DIR

    html = (CATALOG_DIR / "registry" / "blocks" / "mk-progress-stat"
            / "mk-progress-stat.html").read_text(encoding="utf-8")
    fade_offset = _fade_offset(html)

    _, _, _, patches = build("metric", {"value": "250000", "label": "выручка"},
                             duration=duration, colors={})
    needle, replacement = patches[0]
    count_duration, count_start = _count_tween(replacement)
    count_end = count_start + count_duration

    assert count_end <= 0.4 * duration + 1e-3

    settle_tolerance = 0.05  # тот же допуск, что и в hf_montage.settle_schemas
    fade_start = (duration - settle_tolerance) - fade_offset
    hold = fade_start - count_end
    assert hold >= 0.4, (
        f"при {duration} с счёт кончается на {count_end:.4f}, угасание "
        f"начинается на {fade_start:.4f} — запас {hold:.4f} с меньше 0,4")


def test_build_больше_не_гасит_счёт_у_даты():
    """rb0907-university, сцена `s-21`, 07.09.2026: `value: "23 августа"`,
    первая правка (03.09) снимала твин прямо здесь, патчем `build()`. Корень
    оказался глубже (rb0908-university): дата — неверный блок вообще, не
    только неверный твин внутри него, — и маршрут ушёл в `hf_compose`
    (`_is_dateline` + `date_variables` перед вызовом `schema_build`, мимо
    этой функции целиком): дату там перехватывают ДО `build()` и монтируют
    компонентом `number-pop-in`, а этот файл про неё больше не знает.
    `build()`, вызванный напрямую (как здесь), теперь видит только форму
    количества — муть «дата или количество» из него ушла, и любое значение
    получает обычный счётный твин."""
    _, config, css, patches = build(
        "metric", {"value": "23 августа", "label": "дедлайн приёма заявок"},
        duration=2.6, colors={})
    assert config["value"] == 23 and config["suffix"] == " августа"
    # Полосу гасит `base <= number` (базы нет — `base` по умолчанию 0), не
    # то, что величина похожа на дату: строка не знает о дате ничего.
    assert "#mk-ps-track { display: none; }" in css
    needle, replacement = patches[0]
    assert ("num.textContent = Math.round(CONFIG.value) + CONFIG.suffix;"
            not in replacement)
    assert "tl.to(" in replacement


@pytest.mark.parametrize("value", ["23 августа", "2026 год", "2020 года",
                                    "10:30", "10–20", "12 (протокол № 88)"])
def test_is_dateline_узнаёт_дату_номер_и_время(value):
    """Месяц в любом падеже, «год/года», время, диапазон, «№» — признак
    «когда/который», по которому `hf_compose` решает, маршрутить ли значение
    формы `metric` в `number-pop-in` вместо счётчика. Раньше эти же значения
    проверялись через поведение `build()` — теперь маршрутизация ушла из
    этого файла в `hf_compose`, и `_is_dateline` — то место, которое
    действительно решает."""
    assert _is_dateline(value)


def test_date_variables_режет_значение_на_число_и_хвост():
    """`number-pop-in` печатает число и хвост при нём двумя отдельными
    переменными (`value`, `unit`), а не одной строкой, как счётчик
    (`_metric_parts`, тот же разбор — только суффикс едет не приклеенным к
    числу, а отдельным полем)."""
    assert date_variables("20 августа") == {"value": "20", "unit": "августа"}
    assert date_variables("2026 год") == {"value": "2026", "unit": "год"}


@pytest.mark.parametrize("value", ["100%", "8 из 10", "250 000 ₽", "87%"])
def test_количества_считаются(value):
    """Количество отвечает «сколько» — отсчёт для него честен и остаётся."""
    _, _, _, patches = build("metric", {"value": value, "label": "х"},
                             duration=2.6, colors={})
    needle, replacement = patches[0]
    assert "tl.to(" in replacement


def test_ни_одна_форма_не_заезжает_на_полосу_титра():
    """Ниже 980 идут слова титра. Их проверка перекрытия ловит это через раз
    (на `brand` не поймала вовсе — белая плашка легла на первую строку), значит
    держим черту сами."""
    from reels_factory.hf_schema import SAFE_BOTTOM

    _, config, _, _ = build("metric", {"value": "87%", "label": "дошли"},
                            duration=4.0, colors={})
    assert config["y"] < SAFE_BOTTOM
    _, config, _, _ = build("steps", {"nodes": ["раз", "два"]},
                            duration=5.0, colors={})
    assert config["y"] + config["boxH"] <= SAFE_BOTTOM
    _, _, css, patches = build("brand", {"files": [".media/a.svg"]},
                               duration=3.0, colors={})
    top = int(css.split("top: ")[1].split("px")[0])
    height = int(css.split("height: ")[1].split("px")[0])
    assert top + height <= SAFE_BOTTOM
    assert f"({SAFE_BOTTOM} - colH)" in dict(
        build("pairs", {"rows": [{"label": "раз", "value": "два"}]},
              duration=4.0, colors={})[3])[
        f"Math.round((1920 - colH) / 2)"]


def test_плитка_знака_не_белая():
    """`--mk-paper` — заливка плитки, а не цвет букв: с цветом чернил знак
    ехал на белой плашке во весь свой прямоугольник."""
    _, _, css, _ = build("brand", {"files": [".media/a.svg"]}, duration=3.0,
                         colors={"bg": "#101018", "ink": "#ffffff"})
    assert "--mk-paper: #101018" in css


def test_плитка_карточки_разведена_с_фоном():
    """`--surface` равнялся `bg` знак в знак, и карточка перечисления читалась
    одним контуром. У них плитка отличается от подложки всегда
    (`var(--surface, #141a23)` против `var(--bg, …)`)."""
    from reels_factory.hf_schema import SURFACE_LIFT, _mix

    colors = {"bg": "#1a1210", "ink": "#ffffff", "accent": "#ff5a36"}
    css = palette_css("grid-card-assemble", colors)
    lifted = _mix("#1a1210", "#ffffff", SURFACE_LIFT)
    assert lifted != "#1a1210"
    assert f"--surface: {lifted}" in css


def test_фон_кадра_блоку_схемы_не_отдаётся():
    """`--bg` красит корень их перечисления, и объявленный на сцене токен
    закрыл бы живой фон схемной сцены прямоугольником 1080x980."""
    css = palette_css("grid-card-assemble", {"bg": "#1a1210", "ink": "#ffffff",
                                             "accent": "#ff5a36"})
    assert "--bg:" not in css


def test_смешение_цветов_переживает_мусор():
    """Правило палитры собирается на любых цветах: цвет не в форме `#rrggbb`
    возвращает исходный, а не роняет сборку."""
    from reels_factory.hf_schema import _mix

    assert _mix("#000000", "#ffffff", 0.5) == "#808080"
    assert _mix("не цвет", "#ffffff", 0.5) == "не цвет"


def test_корни_блоков_схемы_прозрачны():
    """Схема стоит на живом фоне сцены (`.aurora` в templates/reel.html), и
    залитый корень блока закрыл бы его прямоугольником во весь кадр. У четырёх
    форм из пяти в их же исходнике стоит голое `background: transparent`;
    пятая (`grid-card-assemble`) красилась по `--bg`, и её копию мы правим."""
    from reels_factory.hf_catalog import CATALOG_DIR

    for block in FORMS.values():
        html = (CATALOG_DIR / "registry" / "blocks" / block
                / f"{block}.html").read_text(encoding="utf-8")
        assert "var(--bg," not in html, block


def test_полярность_букв_позиции_выбирает_кадр_а_не_её_умолчание():
    """Тринадцать позиций каталога дают выбрать полярность своих букв
    переменной `tone` со значениями `ink`/`paper`, и умолчание у всех —
    `ink`, «near-black for light frames» (их же слова, `typewriter.html:20-22`).
    Кадр у нас тёмный (`hf_frame.FRAME_DEFAULTS`, `bg #0b0b0c`), и на живом
    `check --strict` 0.8.27 это давало `contrast_aa_failure` 1.02:1 с
    `fg rgb(24,24,27)` — чёрным по чёрному. Цвет кадра — наша арифметика, в
    плане его нет, поэтому значение выбирает код."""
    from reels_factory.hf_schema import frame_variables

    card = {"variables": {"tone": {"type": "enum", "default": "ink",
                                   "options": ["ink", "paper", "accent"]},
                          "caret": {"type": "enum", "default": "line",
                                    "options": ["line", "block", "none"]}}}
    тёмный = {"bg": "#0b0b0c", "ink": "#ffffff", "accent": "#ff1745"}
    assert frame_variables(card, тёмный) == {"tone": "paper"}
    светлый = {"bg": "#fafafa", "ink": "#111111", "accent": "#ff1745"}
    assert frame_variables(card, светлый) == {"tone": "ink"}


def test_названное_планом_значение_полярности_сильнее_кадра():
    """Агент назвал `tone` сам — код его не перекрывает: выбор плана всегда
    сильнее умолчания, которое подставляем мы."""
    from reels_factory.hf_schema import frame_variables

    card = {"variables": {"tone": {"type": "enum", "default": "ink",
                                   "options": ["ink", "paper", "accent"]}}}
    тёмный = {"bg": "#0b0b0c", "ink": "#ffffff", "accent": "#ff1745"}
    assert frame_variables(card, тёмный, {"tone": "accent"}) == {}


# ---------- кегль pairs и steps растёт от кадра, а не остаётся литералом ----------
#
# Job rb0908-philosophers, 07.09.2026, сцены s-05 (`pairs`, presenter `none`)
# и s-03 (`steps`, `pip-br`): их кегли (46/40 px у `mk-specs-list`, литерал 46
# у `hw-pipeline`) сверстаны под landscape-канвас и не растут ни от чего —
# подмена канваса в `port_block` переписывает только буквальные 1920/1080.
# Строка «да  объяснить честно» при кегле 46 занимала ~443 px из 840
# `lineWidth` (contact-sheet-2/3.jpg, tile-s05.png), а узел «Убеждает» на
# `pip-br` читался пятипроцентной царапиной кадра (tile-s03.png).


def test_кегль_pairs_растёт_от_реального_текста_а_не_от_потолка_символов():
    """Множитель — от самой длинной РЕАЛЬНОЙ строки (job rb0908-philosophers,
    s-05), а не от потолка `PAIRS_LABEL_CHARS`/`PAIRS_VALUE_CHARS` — тот
    запас на редкий случай, не типичная длина. Реальная строка доходит до
    `lineWidth`, а не остаётся на исходной доле."""
    from reels_factory.hf_schema import _PAIRS_ROW_HEIGHT

    _, config, css, patches = build(
        "pairs", {"rows": [{"label": "да", "value": "объяснить честно"},
                           {"label": "нет", "value": "давить на человека"}]},
        duration=4.3, colors={})
    assert "font-size: 80px" in css  # .mk-sl-label, было 46
    assert "font-size: 70px" in css  # .mk-sl-value, было 40
    assert config["rowGap"] == 98  # растёт тем же множителем, не литерал 56
    # Их скрипт центрирует колонку своим же кеглем (46 + отступ подчёркивания
    # + волосяная линия) — литерал обязан расти вместе с текстом, иначе
    # колонка отцентруется по СТАРОЙ, маленькой высоте ряда.
    assert (dict(patches)[_PAIRS_ROW_HEIGHT]
            == "(80 + 22 + (CONFIG.underline ? 2 : 0))")


def test_кегль_pairs_не_ниже_их_исходного_даже_на_потолке_символов():
    """Множитель floor на 1.0 (`max(1.0, ...)`): хуже их дизайна (46/40 px)
    кегль не становится, даже когда реальный текст близок к пределу
    символов и от `lineWidth` расти уже некуда."""
    _, _, css, _ = build(
        "pairs", {"rows": [{"label": "с" * 22, "value": "з" * 26},
                           {"label": "б" * 22, "value": "к" * 26}]},
        duration=4.3, colors={})
    assert "font-size: 46px" in css
    assert "font-size: 40px" in css


def test_кегль_pairs_на_потолке_символов_не_ниже_и_не_выше_их_исходного():
    """На потолке `PAIRS_LABEL_CHARS`/`PAIRS_VALUE_CHARS` разом текст уже при
    ИХ родном кегле (46/40) шире `lineWidth` — это не наша правка внесла
    (`scale_width` считает то же самое отношение и без неё), а свойство
    самого потолка символов: он держит запас на редкий случай, а не гарантию,
    что пара с обоими полями до предела влезет в одну строку без переноса.
    Наш `scale` в этом случае остаётся на 1.0 (не хуже их дизайна) и не
    раздувает то, что и так не помещалось."""
    from reels_factory.hf_schema import PAIRS_LABEL_CHARS, PAIRS_VALUE_CHARS

    _, _, css, _ = build(
        "pairs", {"rows": [{"label": "с" * PAIRS_LABEL_CHARS,
                            "value": "з" * PAIRS_VALUE_CHARS}]},
        duration=4.3, colors={})
    assert "font-size: 46px" in css
    assert "font-size: 40px" in css


def test_кегль_steps_растёт_вместе_с_коробкой():
    """Коробка уже считалась от ширины кадра, кегль — нет (литерал 46): узел
    читался мельче их же дизайна (`hw-pipeline.html:99-106` — коробка 320x170
    держит кегль 56). Кегль и высота коробки теперь — их же доля от новой,
    заполняющей кадр коробки."""
    _, config, _, _ = build("steps", {"nodes": ["раз", "два"]},
                            duration=5.0, colors={})
    assert config["boxW"] == 360  # заполняет безопасную ширину для двух узлов
    assert config["fontSize"] > 46
    assert config["boxH"] > 150


def test_кегль_steps_не_вылезает_за_коробку_на_потолке_символов():
    """На потолке символов (`NODE_CHARS`) кегль обязан ужаться под гарантию
    текста, а не остаться на потолке их пропорции от коробки — иначе подпись
    срежет края (живой прогон правки: «Выполняет» при первой прикидке отступа
    читалось прижатым к обводке узла)."""
    from reels_factory.hf_schema import (
        _GLYPH_RATIO, _NODE_TEXT_PADDING, NODE_CHARS,
    )

    long_word = "б" * NODE_CHARS[2]
    _, config, _, _ = build("steps", {"nodes": [long_word, long_word]},
                            duration=5.0, colors={})
    text_width = len(long_word) * config["fontSize"] * _GLYPH_RATIO
    assert text_width + _NODE_TEXT_PADDING <= config["boxW"]


def test_кегль_steps_не_ниже_читаемого_пола():
    """HyperFrames про видео прямым текстом: «If you're writing a font-size
    under 24px in a video composition, justify it»
    (`hyperframes-ref/skills/hyperframes-creative/references/
    video-composition.md:47`). Три узла с максимумом символов — самый тесный
    случай формы `steps`."""
    from reels_factory.hf_schema import NODE_CHARS, _NODE_MIN_FONT

    long_word = "б" * NODE_CHARS[3]
    _, config, _, _ = build(
        "steps", {"nodes": [long_word, long_word, long_word]},
        duration=6.0, colors={})
    assert config["fontSize"] >= _NODE_MIN_FONT


def test_кегль_steps_считается_от_коробки_после_её_сужения(monkeypatch):
    """При нынешних `LIMITS["steps"]=3`, `gap=70`, `margin=80` цикл
    `while count * box + (count-1) * gap > OUT_W - margin` никогда не
    срабатывает (ревью PR #100, `hf_schema.py:846-856`) — формула деления уже
    вписывает 2-3 узла в ширину кадра. Но `font`/`boxH` считались от `box` ДО
    этого цикла: молчаливый дефект просыпается ровно тогда, когда `box`
    зажат нижним полом 220px при большем счёте узлов, чем сегодняшний потолок
    разрешает. Поднимаем `LIMITS["steps"]` до 5, чтобы цикл сработал по-
    настоящему, и проверяем, что кегль и высота коробки — от ИТОГОВОГО,
    уже суженного `boxW`, а не от 220px, с которых цикл стартовал."""
    from reels_factory.hf_schema import (
        LIMITS, _GLYPH_RATIO, _NODE_BOXH_RATIO, _NODE_FONT_RATIO,
        _NODE_MIN_FONT, _NODE_TEXT_PADDING,
    )

    nodes = ["раз", "два", "три", "штырь", "пять"]
    monkeypatch.setitem(LIMITS, "steps", 5)
    _, config, _, _ = build("steps", {"nodes": nodes}, duration=7.0, colors={})

    def _font_for(box: int) -> int:
        longest = max(len(node) for node in nodes)
        font_by_box = round(box * _NODE_FONT_RATIO)
        font_by_text = int((box - _NODE_TEXT_PADDING) / (longest * _GLYPH_RATIO))
        return max(_NODE_MIN_FONT, min(font_by_box, font_by_text))

    # Пол 220px подняли бы box, если бы не цикл сужения — тест это и ловит:
    # итоговый boxW обязан быть МЕНЬШЕ пола, то есть цикл действительно сузил
    # коробку, а не остался мёртвым кодом, как при нынешних LIMITS.
    box = config["boxW"]
    assert box < 220
    # Кегль — от ИТОГОВОГО, уже суженного box, а не от 220px, с которых
    # цикл стартовал (регрессия порядка расчёта дала бы `_font_for(220)`).
    assert config["fontSize"] == _font_for(box)
    assert config["fontSize"] != _font_for(220)
    # Высота коробки — их же пропорция от ИТОГОВОГО кегля, той же ловушке
    # порядка подвержена симметрично.
    assert config["boxH"] == round(config["fontSize"] * _NODE_BOXH_RATIO)
