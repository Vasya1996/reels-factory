"""Гейты по живой композиции. Отчёт пробы подставляем готовый — без браузера."""
import json

import pytest

from reels_factory.hf_probe import (
    MOVE_FRACTION, gates_from_report, probe_gates, run_probe,
)

FACE = {"cx": 540, "cy": 520, "h": 260}
FULL_FRAME = {"left": 0, "top": 0, "width": 1080, "height": 1920, "visible": True}
# окно ведущей, отодвинутое вправо-вверх: раскладка pip из hf_layout.VIDEO_RECTS
PIP = {"left": 690, "top": 28, "width": 360, "height": 203, "visible": True}
ARCH = {"left": 120, "top": 900, "width": 520, "height": 700, "visible": True}
# наезд: то же полное окно, но заметно крупнее — `punch` из hf_layout.VIDEO_RECTS
PUNCH = {"left": -87, "top": -170, "width": 1254, "height": 2229,
         "visible": True}


def _rect(left, top, width, height):
    return {"left": left, "top": top, "width": width, "height": height,
            "right": left + width, "bottom": top + height}


def _text(left, top, width, height, text="карточка"):
    return {"selector": "#card-01 .title", "tag": "div", "text": text,
            "rect": _rect(left, top, width, height),
            "elementRect": _rect(left, top, width, height),
            "sourceFile": "index.html"}


#: Вставка в кадре: обычный клип с идентификатором `ins-<сцена>`.
INSERT = {"id": "ins-s-01", "visible": True}


def _sample(time, *, video=FULL_FRAME, texts=(), clips=(INSERT,),
            src=("compositions/kicker.html",)):
    return {"time": time, "videoRect": dict(video), "texts": list(texts),
            "clips": [dict(clip) for clip in clips], "compositionSrc": list(src),
            "fingerprint": f"печать-{time}",
            "canvas": {"width": 1080, "height": 1920}}


def _report(samples, **over):
    report = {"duration": 12.0, "sweepStatic": False,
              "compositionSrc": sorted({s for sample in samples
                                        for s in sample["compositionSrc"]}),
              "samples": samples}
    report.update(over)
    return report


# ---------- D8: текст на лице ----------

def _низ_кадра():
    return _text(60, 1400, 960, 400)


def test_чистая_композиция_проходит():
    samples = [_sample(0.0, texts=[_низ_кадра()]),
               _sample(3.0, video=PIP, texts=[_низ_кадра()]),
               _sample(6.0, video=ARCH, texts=[_низ_кадра()])]
    assert all(value.startswith("PASS")
               for value in gates_from_report(_report(samples), FACE).values())


def test_текст_на_лице_валится():
    samples = [_sample(0.0, texts=[_text(300, 300, 500, 300, "ЗАГОЛОВОК")]),
               _sample(3.0, video=PIP)]
    gates = gates_from_report(_report(samples), FACE)
    assert gates["D8_face"].startswith("FAIL")
    assert "ЗАГОЛОВОК" in gates["D8_face"]


def test_лицо_едет_вместе_с_окном_видео():
    """В pip-окне лицо ужимается вправо-вверх — низ кадра перестаёт быть занят.

    Тот же прямоугольник текста, что валит гейт на полном кадре, в уменьшенном
    окне чист: пересчёт лица идёт через hf_layout.moved_face.
    """
    на_лице = _text(300, 300, 500, 300)
    assert gates_from_report(_report([_sample(0.0, texts=[на_лице]),
                                      _sample(3.0, video=PIP)]),
                             FACE)["D8_face"].startswith("FAIL")
    assert gates_from_report(_report([_sample(0.0, video=PIP, texts=[на_лице]),
                                      _sample(3.0)]),
                             FACE)["D8_face"] == "PASS"


def test_без_лица_гейт_не_валит_сборку():
    """face.json может не быть — это не повод объявлять монтаж плохим."""
    gates = gates_from_report(_report([_sample(0.0, texts=[_text(300, 300, 500, 300)]),
                                       _sample(3.0, video=PIP)]), None)
    assert gates["D8_face"].startswith("PASS")


def test_где_ведущей_на_экране_нет_лицо_не_проверяется():
    """Аватар на этот кусок не заказан: движок прячет <video> вне его окна."""
    спрятана = dict(FULL_FRAME, visible=False)
    samples = [_sample(0.0, video=спрятана, texts=[_text(300, 300, 500, 300)]),
               _sample(3.0), _sample(6.0, video=PIP)]
    assert gates_from_report(_report(samples), FACE)["D8_face"] == "PASS"


# ---------- D14: ведущая обязана двигаться ----------

def test_неподвижная_ведущая_валится():
    samples = [_sample(0.0), _sample(3.0), _sample(6.0)]
    assert gates_from_report(_report(samples), FACE)[
        "D14_presenter_moves"].startswith("FAIL")


def test_смена_раскладки_засчитывается():
    """Приёмка требует трёх разных положений, двух мало."""
    двух = [_sample(0.0), _sample(3.0, video=PIP), _sample(6.0)]
    assert gates_from_report(_report(двух), FACE)[
        "D14_presenter_moves"].startswith("FAIL")
    трёх = [*двух, _sample(9.0, video=ARCH)]
    assert gates_from_report(_report(трёх), FACE)[
        "D14_presenter_moves"].startswith("PASS")


def test_дрожание_ниже_порога_за_движение_не_считается():
    """Сдвиг меньше 5% стороны кадра зритель не замечает — это не перестановка."""
    from reels_factory.hf_probe import _distinct_positions

    едва = dict(FULL_FRAME, left=FULL_FRAME["left"] + MOVE_FRACTION * 1080 - 1)
    assert len(_distinct_positions([FULL_FRAME, едва])) == 1


def test_сдвиг_на_порог_засчитывается():
    from reels_factory.hf_probe import _distinct_positions

    сдвинута = dict(FULL_FRAME, left=FULL_FRAME["left"] + MOVE_FRACTION * 1080)
    assert len(_distinct_positions([FULL_FRAME, сдвинута])) == 2


def test_ведущей_нет_нигде_валится():
    спрятана = dict(FULL_FRAME, visible=False)
    samples = [_sample(0.0, video=спрятана), _sample(3.0, video=спрятана)]
    assert gates_from_report(_report(samples), FACE)[
        "D14_presenter_moves"].startswith("FAIL")


def test_планка_считается_от_достижимого():
    """Ни одна вставка и ни одна схема до кадра не дожили — уголок ведущей
    роняет D20 (`fills_frame`), и `positions_for` оставляет ей `full` и
    `punch`. Третьего положения взять неоткуда, и требовать его значит валить
    сборку за невозможное; чинить это агенту нечем. Пол в одно положение при
    этом остаётся: неподвижная ведущая — по-прежнему провал."""
    двух = [_sample(0.0, clips=()), _sample(3.0, video=PUNCH, clips=())]
    assert gates_from_report(_report(двух), FACE)[
        "D14_presenter_moves"].startswith("PASS")

    одного = [_sample(0.0, clips=()), _sample(3.0, clips=())]
    assert gates_from_report(_report(одного), FACE)[
        "D14_presenter_moves"].startswith("FAIL")


def test_вставка_без_ведущей_в_кадре_планку_не_поднимает():
    """Дожившая вставка стоит на сцене без ведущей — уголка она не открывает.

    Прежде хватало одной видимой вставки где угодно по ролику, и планка
    возвращалась к трём. На упавшем прогоне дожила ровно одна, и требовать
    третье окно было неоткуда: `presenter: "none"` — ведущей в этих секундах
    нет, а поверх пустого фона уголок роняет D20.
    """
    порознь = [_sample(0.0, clips=()),
               _sample(3.0, video=dict(FULL_FRAME, visible=False)),
               _sample(6.0, video=PUNCH, clips=())]
    assert gates_from_report(_report(порознь), FACE)[
        "D14_presenter_moves"].startswith("PASS")


def test_вставка_рядом_с_ведущей_планку_поднимает():
    """Вставка и ведущая стоят в кадре одновременно — уголок тут законен, и
    трёх окон ролик действительно позволяет."""
    вместе = [_sample(0.0, clips=()), _sample(3.0, video=PIP)]
    assert gates_from_report(_report(вместе), FACE)[
        "D14_presenter_moves"].startswith("FAIL")


def test_отказ_D14_не_зовёт_агента_в_угол():
    """Текст отказа обращён к коду. Прежний велел «раскидать ведущую по кадру
    — во весь кадр, в угол, в половину», и выполнение этого указания роняло
    следующий гейт: уголок без вставки и без схемы оставляет остальной кадр
    чёрным (`D20_frame_filled`)."""
    вместе = [_sample(0.0, clips=()), _sample(3.0, video=PIP)]
    отказ = gates_from_report(_report(вместе), FACE)["D14_presenter_moves"]
    assert отказ.startswith("FAIL")
    assert "раскидай" not in отказ and "в угол" not in отказ
    assert "вставка или схема" in отказ


# ---------- D15: вставки видны ----------

def test_композиция_без_вставок_валится():
    """Гейт был про блоки каталога, но их в кадре может не быть вовсе. Дыра,
    которую он закрывал, осталась: прогон 03.08 вернул ролик без графики."""
    samples = [_sample(0.0, clips=()), _sample(3.0, video=PIP, clips=())]
    assert gates_from_report(_report(samples), FACE)[
        "D15_inserts_visible"].startswith("FAIL")


def test_объявленная_но_невидимая_вставка_валится():
    """D16 смотрит разметку, здесь — отрисованную композицию: их `check` шесть
    раз сказал, что окно ведущей внутри блока не рисуется, и мы прошли мимо."""
    dead = {"id": "ins-s-01", "visible": False}
    samples = [_sample(0.0, clips=[dead]), _sample(3.0, video=PIP, clips=[dead])]
    assert gates_from_report(_report(samples), FACE)[
        "D15_inserts_visible"].startswith("FAIL")


def test_видимая_вставка_принимается():
    alive = {"id": "ins-s-01", "visible": True}
    samples = [_sample(0.0, clips=[alive]), _sample(3.0, video=PIP, clips=[alive])]
    assert gates_from_report(_report(samples), FACE)[
        "D15_inserts_visible"].startswith("PASS")


# ---------- недостоверный прогон ----------

def test_замерший_таймлайн_валит_все_гейты():
    """Их sweep_static: перемотка ничего не двинула, значит зелёный — вранью."""
    samples = [_sample(0.0), _sample(3.0, video=PIP)]
    gates = gates_from_report(_report(samples, sweepStatic=True), FACE)
    assert set(gates) == {"D8_face", "D14_presenter_moves", "D15_inserts_visible",
                          "D17_service_text", "D26_frame_content"}
    assert all(value.startswith("FAIL") for value in gates.values())


def test_пустая_проба_не_молчит():
    with pytest.raises(RuntimeError, match="ни одной выборки"):
        gates_from_report(_report([]), FACE)


# ---------- запуск ----------

def test_несостоявшаяся_проба_валится_ошибкой(tmp_path):
    """Композиции нет — это ошибка сборки, а не PASS."""
    with pytest.raises(RuntimeError, match="нет композиции"):
        run_probe(tmp_path)


def test_упавший_скрипт_валится_ошибкой(tmp_path, monkeypatch):
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "index.html").write_text("<html></html>", encoding="utf-8")

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "не найден Chrome для headless"

    monkeypatch.setattr("reels_factory.hf_probe.shutil.which", lambda _: "node")
    monkeypatch.setattr("reels_factory.hf_probe.subprocess.run",
                        lambda *a, **k: _Result())
    with pytest.raises(RuntimeError, match="не найден Chrome"):
        run_probe(tmp_path)


def test_гейты_читают_отчёт_с_диска(tmp_path, monkeypatch):
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "index.html").write_text("<html></html>", encoding="utf-8")
    report = _report([_sample(0.0), _sample(3.0, video=PIP),
                      _sample(6.0, video=ARCH)])

    class _Result:
        returncode = 0
        stdout = "2 выборки"
        stderr = ""

    def _run(command, **kwargs):
        out = command[command.index("--out") + 1]
        (tmp_path / out).write_text(json.dumps(report), encoding="utf-8")
        return _Result()

    monkeypatch.setattr("reels_factory.hf_probe.shutil.which", lambda _: "node")
    monkeypatch.setattr("reels_factory.hf_probe.subprocess.run", _run)
    assert all(value.startswith("PASS")
               for value in probe_gates(tmp_path, face=FACE).values())


# ---------- D17: служебных надписей в кадре не бывает ----------
#
# В прогоне 03.08 над карточками стояли плашки-рубрики («продажи · база»,
# «вопрос первый · кому продаём?»), а под фотографией — подпись «фото из
# каталога». Это дефект пайплайна, а не одного прогона, поэтому у него свой
# гейт по живой композиции.

@pytest.mark.parametrize("надпись", [
    "ПРОДАЖИ · БАЗА",
    "ВОПРОС ПЕРВЫЙ · КОМУ ПРОДАЁМ?",
    "фото из каталога",
    "источник · плейсхолдер",
    "B-roll slot",
])
def test_служебная_надпись_заворачивает_сборку(надпись):
    report = _report([_sample(1.0, texts=[_text(60, 200, 900, 120, надпись)])])
    assert gates_from_report(report, FACE)["D17_service_text"].startswith("FAIL")


@pytest.mark.parametrize("надпись", [
    "ВСЕ ПРОДАЖИ СВОДЯТСЯ К ТРЁМ ВОПРОСАМ",
    "02 ЧТО ПРОДАЁМ?",
    "ВСЁ ОСТАЛЬНОЕ — НАДСТРОЙКА",
])
def test_содержательный_заголовок_проходит(надпись):
    """Две удачные карточки прошлого прогона — заголовок без рубрики."""
    report = _report([_sample(1.0, texts=[_text(60, 200, 900, 120, надпись)])])
    assert gates_from_report(report, FACE)["D17_service_text"] == "PASS"


# ---------- D26: в кадре что-то есть ----------
#
# Прогон hf-live2 отдал зрителю 2,7 с фона с титром (25,43–28,13 с): сцена
# потеряла серию, закрыть кадр было нечем, а плановый D25 сказал PASS — он
# судил флаг `needsSchema`, а не отрисованную композицию. Данные на эту
# проверку проба снимала и тогда: одиннадцать выборок подряд с пустым кадром
# лежали в probe.json, и никто их не читал.

def _пусто(time, clips=()):
    """Выборка, в которой ведущей нет и клипа с содержимым тоже."""
    return _sample(time, video=dict(FULL_FRAME, visible=False), clips=clips)


def test_пустой_кадр_в_готовой_композиции_валится():
    samples = [_sample(0.0), *[_пусто(t) for t in (1.0, 1.25, 1.5, 1.75)],
               _sample(2.0)]
    verdict = gates_from_report(_report(samples), FACE)["D26_frame_content"]
    assert verdict.startswith("FAIL")
    assert "1" in verdict


def test_вспышка_и_титр_кадр_не_держат():
    """Ловушка прогона: `fx-0` (накладка вспышки) на пустом кадре стоит
    visible=true, и правило «видно хоть что-нибудь» его бы засчитало."""
    вспышка = ({"id": "fx-0", "visible": True},)
    samples = [_sample(0.0),
               *[_пусто(t, clips=вспышка) for t in (1.0, 1.25, 1.5, 1.75)],
               _sample(2.0)]
    assert gates_from_report(_report(samples), FACE)[
        "D26_frame_content"].startswith("FAIL")


@pytest.mark.parametrize("держит", ["ins-s-07-0", "schema-s-07", "ovl-s-07",
                                    "icon-s-07", "el-s-07-0", "clip-03"])
def test_кадр_держит_любое_из_закрытого_списка(держит):
    клипы = ({"id": держит, "visible": True},)
    samples = [_sample(0.0),
               *[_пусто(t, clips=клипы) for t in (1.0, 1.25, 1.5, 1.75)],
               _sample(2.0)]
    assert gates_from_report(_report(samples), FACE)[
        "D26_frame_content"].startswith("PASS")


def test_стык_клипов_за_пустой_кадр_не_считается():
    """Одна-две выборки без содержимого — это шов между клипами (их сетка
    1/30 с и наш кадр+1), а не дыра, которую видит зритель."""
    samples = [_sample(0.0), _пусто(1.0), _пусто(1.25), _sample(1.5)]
    assert gates_from_report(_report(samples), FACE)[
        "D26_frame_content"].startswith("PASS")
