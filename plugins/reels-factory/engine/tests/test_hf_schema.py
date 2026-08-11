"""Схема в кадре: их блок, вписанный в вертикаль нашим кодом."""
import json
import re

import pytest

from reels_factory.hf_schema import (
    FORMS, LIMITS, build, min_seconds, palette_css, port_block,
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
    assert set(FORMS) == {"stat", "list", "link", "brand"}
    assert FORMS["link"] == "hw-pipeline"


def test_цифра_разбирается_на_число_и_суффикс():
    block, config, _, _ = build("stat", {"value": "87%", "label": "дошли"},
                                duration=4.0, colors={})
    assert block == "mk-progress-stat"
    assert config["value"] == 87 and config["suffix"] == "%"
    assert config["max"] == 87        # полоса заполнена целиком


def test_длинная_подпись_режется_по_словам():
    """У их списка и подписи узла стоит `white-space: nowrap`: строка не
    переносится, а уезжает за край кадра, и ни один их гейт этого не видит —
    он меряет рамку элемента, а не текст внутри."""
    _, config, _, _ = build(
        "list", {"items": ["Claude — длинные документы, таблицы и ещё немного"]},
        duration=4.0, colors={})
    assert len(config["rows"][0]["label"]) <= 30
    assert config["rows"][0]["label"].split()[0] == "Claude"


def test_список_не_длиннее_предела():
    _, config, _, _ = build("list", {"items": list("абвгде")},
                            duration=4.0, colors={})
    assert len(config["rows"]) == LIMITS["list"]


def test_узлы_связи_влезают_в_кадр():
    """Их раскладка считает ширину ряда как n·boxW + (n−1)·gap: на их числах
    три узла дают 1340 px при кадре 1080."""
    _, config, _, _ = build("link", {"nodes": ["заявка", "звонок", "сделка"]},
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
    assert min_seconds("link", 3) > min_seconds("link", 2)
    assert min_seconds("stat", 1) == 2.6
