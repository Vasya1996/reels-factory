"""Лицо ведущей: доли кадра из детектора -> пиксели -> свободные полосы."""
import json

from reels_factory.face_detect import face_box_for, free_bands, load_face


def test_доли_превращаются_в_пиксели(tmp_path):
    out = tmp_path / "face.json"
    face = face_box_for("нет.mp4", out, detect=lambda src, fps: [(0.5, 0.3)])
    assert face["cx"] == 540
    assert face["cy"] == 576
    assert face["h"] > 0
    assert json.loads(out.read_text(encoding="utf-8")) == face


def test_без_детекта_якорь_по_умолчанию(tmp_path):
    face = face_box_for("нет.mp4", tmp_path / "face.json", detect=lambda src, fps: [])
    assert face["cx"] == 540
    assert face["cy"] == round(1920 * 0.42)


def test_свободные_полосы_не_пересекают_лицо(tmp_path):
    from reels_factory.hf_layout import violations

    face = face_box_for("нет.mp4", tmp_path / "face.json", detect=lambda src, fps: [])
    bands = free_bands(face)
    assert bands, "должна остаться хотя бы одна свободная полоса"
    for band in bands:
        assert violations(band, face) == []


def test_чтение_отсутствующего_файла(tmp_path):
    assert load_face(tmp_path) is None


def test_без_лица_средняя_треть_запретна():
    """Без детекта считаем среднюю треть кадра занятой ведущей."""
    bands = free_bands(None)
    assert len(bands) == 2
    assert bands[0] == {"left": 0, "top": 0, "width": 1080, "height": 640}
    assert bands[1] == {
        "left": 0, "top": 1280, "width": 1080, "height": 640
    }
