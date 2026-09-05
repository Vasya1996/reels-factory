"""Схема в кадре: их блок, вписанный в вертикаль нашим кодом."""
import json
import re

import pytest

from reels_factory.hf_schema import (
    FORMS, ICONS, LIMITS, SAFE_BOTTOM, build, min_seconds, palette_css,
    port_block,
)

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
