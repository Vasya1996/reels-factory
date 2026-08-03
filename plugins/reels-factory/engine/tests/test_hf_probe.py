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


def _rect(left, top, width, height):
    return {"left": left, "top": top, "width": width, "height": height,
            "right": left + width, "bottom": top + height}


def _text(left, top, width, height, text="карточка"):
    return {"selector": "#card-01 .title", "tag": "div", "text": text,
            "rect": _rect(left, top, width, height),
            "elementRect": _rect(left, top, width, height),
            "sourceFile": "index.html"}


def _sample(time, *, video=FULL_FRAME, texts=(), src=("compositions/kicker.html",)):
    return {"time": time, "videoRect": dict(video), "texts": list(texts),
            "clips": [], "compositionSrc": list(src),
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
               _sample(3.0, video=PIP, texts=[_низ_кадра()])]
    assert set(gates_from_report(_report(samples), FACE).values()) == {"PASS"}


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
    samples = [_sample(0.0), _sample(3.0, video=PIP), _sample(6.0)]
    assert gates_from_report(_report(samples), FACE)["D14_presenter_moves"] == "PASS"


def test_дрожание_ниже_порога_за_движение_не_считается():
    """Сдвиг меньше 5% стороны кадра зритель не замечает — это не перестановка."""
    едва = dict(FULL_FRAME, left=FULL_FRAME["left"] + MOVE_FRACTION * 1080 - 1)
    samples = [_sample(0.0), _sample(3.0, video=едва)]
    assert gates_from_report(_report(samples), FACE)[
        "D14_presenter_moves"].startswith("FAIL")


def test_сдвиг_на_порог_засчитывается():
    сдвинута = dict(FULL_FRAME, left=FULL_FRAME["left"] + MOVE_FRACTION * 1080)
    samples = [_sample(0.0), _sample(3.0, video=сдвинута)]
    assert gates_from_report(_report(samples), FACE)["D14_presenter_moves"] == "PASS"


def test_ведущей_нет_нигде_валится():
    спрятана = dict(FULL_FRAME, visible=False)
    samples = [_sample(0.0, video=спрятана), _sample(3.0, video=спрятана)]
    assert gates_from_report(_report(samples), FACE)[
        "D14_presenter_moves"].startswith("FAIL")


# ---------- D15: блоки каталога ----------

def test_композиция_без_блоков_каталога_валится():
    samples = [_sample(0.0, src=()), _sample(3.0, video=PIP, src=())]
    assert gates_from_report(_report(samples), FACE)[
        "D15_catalog_blocks"].startswith("FAIL")


# ---------- недостоверный прогон ----------

def test_замерший_таймлайн_валит_все_гейты():
    """Их sweep_static: перемотка ничего не двинула, значит зелёный — вранью."""
    samples = [_sample(0.0), _sample(3.0, video=PIP)]
    gates = gates_from_report(_report(samples, sweepStatic=True), FACE)
    assert set(gates) == {"D8_face", "D14_presenter_moves", "D15_catalog_blocks"}
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
    report = _report([_sample(0.0), _sample(3.0, video=PIP)])

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
    assert set(probe_gates(tmp_path, face=FACE).values()) == {"PASS"}
