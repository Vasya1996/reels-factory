"""Отсев вставок: их поиск ранжирует, мы только вычёркиваем негодных."""
import pytest

from reels_factory import hf_media
from reels_factory.hf_media import (
    _claim, candidate_problem, resolve_all, scan_ocr_rows,
)

FULL = {"left": 0, "top": 0, "width": 1080, "height": 1920}


def _cand(id_: str, width=1200, height=1800, **over):
    cand = {"id": id_, "url": f"https://cdn/{id_}.jpg",
            "width": width, "height": height, "is_transparent": False}
    cand.update(over)
    return cand


# ---------- отсев по метаданным ----------

def test_прозрачный_кандидат_вычёркивается():
    assert "прозрачный" in candidate_problem(
        _cand("a", is_transparent=True), FULL)


def test_мелкий_кандидат_вычёркивается():
    assert "мелкий" in candidate_problem(_cand("a", 200, 300), FULL)


def test_растяжение_в_мыло_вычёркивается():
    """Прогон 15: файл 500x281 закрывал кадр 1080x1920 — растяжение в 6,8 раза."""
    assert "мыло" in candidate_problem(_cand("a", 500, 281), FULL)


def test_кандидат_без_размеров_судится_после_скачивания():
    assert candidate_problem(_cand("a", width=None, height=None), FULL) is None


def test_большой_кандидат_проходит():
    assert candidate_problem(_cand("a", 2048, 1365), FULL) is None


# ---------- выбор кандидата ----------

def test_берётся_первый_годный_в_их_порядке():
    """Ранжирование — их; мы не пересортировываем, только вычёркиваем."""
    picked = _claim({"rect": FULL}, [_cand("мелкий", 300, 200), _cand("б"),
                                     _cand("в")], set())
    assert picked["id"] == "б"


def test_занятый_снимок_не_ставится_дважды():
    """Прогон 15: один файл под двумя именами в двух сценах."""
    picked = _claim({"rect": FULL}, [_cand("а"), _cand("б")], {"а"})
    assert picked["id"] == "б"


def test_запасной_круг_снимает_вето_растяжения():
    """Сцене без ведущей вставка обязательна: мыло лучше чёрного кадра."""
    candidates = [_cand("а", 500, 281)]
    assert _claim({"rect": FULL}, candidates, set()) is None
    assert _claim({"rect": FULL}, candidates, set(),
                  relaxed=True)["id"] == "а"


def test_запасной_круг_не_берёт_прозрачное_и_совсем_мелкое():
    candidates = [_cand("а", is_transparent=True), _cand("б", 150, 100)]
    assert _claim({"rect": FULL}, candidates, set(), relaxed=True) is None


# ---------- OCR ----------

_TSV_HEAD = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
             "left\ttop\twidth\theight\tconf\ttext")


def _tsv(*rows):
    return "\n".join([_TSV_HEAD, *rows])


def _row(text, conf=90.0, height=100):
    return f"5\t1\t1\t1\t1\t1\t10\t10\t200\t{height}\t{conf}\t{text}"


def test_водяной_знак_ловится_по_словарю():
    """Кадры прогона 15: сетка dreamstime поперёк снимка."""
    verdict = scan_ocr_rows(_tsv(_row("dreamstime.com", conf=55, height=20)),
                            1365)
    assert verdict and "водяной знак" in verdict


def test_крупный_текст_на_фотографии_ловится():
    verdict = scan_ocr_rows(
        _tsv(_row("Success"), _row("Mindset")), 1000)
    assert verdict and "читаемый текст" in verdict


def test_мелкая_вывеска_на_фоне_не_считается_текстом():
    verdict = scan_ocr_rows(
        _tsv(_row("кафе", height=15), _row("выход", height=12)), 1000)
    assert verdict is None


def test_неуверенное_распознавание_не_считается():
    verdict = scan_ocr_rows(
        _tsv(_row("шум", conf=30.0), _row("помехи", conf=12.0)), 1000)
    assert verdict is None


def test_одно_слово_не_приговор():
    assert scan_ocr_rows(_tsv(_row("Open")), 1000) is None


# ---------- подбор целиком, без сети ----------

def _wire(monkeypatch, catalog, bad_files=()):
    """Поиск и заморозка без сети: каталог задан словарём intent -> кандидаты."""
    monkeypatch.setattr(hf_media, "search_assets",
                        lambda intent, **kw: catalog.get(intent, []))
    monkeypatch.setattr(
        hf_media, "ingest",
        lambda public, url, **kw: {"ok": True,
                                   "path": ".media/images/"
                                           + url.rsplit("/", 1)[-1]})
    monkeypatch.setattr(hf_media, "insert_problem",
                        lambda path, rect=None: "мыло"
                        if any(bad in str(path) for bad in bad_files) else None)
    monkeypatch.setattr(hf_media, "text_problem", lambda path: None)
    monkeypatch.setattr(hf_media.Path, "exists", lambda self: True)


def _request(key, intent, required=False):
    return {"key": key, "type": "image", "intent": intent, "rect": FULL,
            "required": required}


def test_негодный_файл_заменяется_следующим_кандидатом(monkeypatch, tmp_path):
    _wire(monkeypatch,
          {"стол": [_cand("плохой"), _cand("хороший")]},
          bad_files=("плохой",))
    found = resolve_all(tmp_path, [_request("s-01", "стол")])
    assert found["s-01"]["file"].endswith("хороший.jpg")


def test_две_сцены_не_получают_один_снимок(monkeypatch, tmp_path):
    _wire(monkeypatch, {"стол": [_cand("общий"), _cand("второй")],
                        "стол крупнее": [_cand("общий"), _cand("третий")]})
    found = resolve_all(tmp_path, [_request("s-01", "стол"),
                                   _request("s-02", "стол крупнее")])
    assert found["s-01"]["file"].endswith("общий.jpg")
    assert found["s-02"]["file"].endswith("третий.jpg")


def test_пустой_каталог_отдаёт_ошибку_а_не_падает(monkeypatch, tmp_path):
    _wire(monkeypatch, {})
    found = resolve_all(tmp_path, [_request("s-01", "не найдётся")])
    assert "error" in found["s-01"]
