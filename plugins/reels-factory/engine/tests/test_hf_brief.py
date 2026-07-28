"""Задание агенту: правила числами и содержание вставок из плана."""
from reels_factory.hf_brief import STYLE_NAME, write_brief

PLAN = {
    "phrases": [{"id": "p1", "text": "первый вопрос кому продаём"}],
    "windows": [{
        "id": "window-000", "coverage": "hyperframes", "zone": "fullscreen",
        "phrase_ids": ["p1"], "final_timing": {"start": 0.0, "end": 6.0},
        "effect": {"type": "chart_bars", "title": "Три вопроса",
                   "hyperframes": {"block": "task_list",
                                   "variables": {"title": "Три вопроса",
                                                 "items": ["Кому продаём"]}}},
    }],
}


def _text(tmp_path, **kw):
    return write_brief(tmp_path, PLAN, face={"cx": 540, "cy": 520, "h": 260},
                       duration=41.5, **kw).read_text(encoding="utf-8")


def test_правила_числами(tmp_path):
    text = _text(tmp_path)
    assert "1080" in text and "1920" in text
    assert STYLE_NAME in text
    assert "Montserrat" in text
    assert "лицо" in text.lower()
    assert "storyboard.json" in text and "contentRect" in text
    assert "1/30" in text


def test_скрытые_субтитры_отмечены(tmp_path):
    plan = {**PLAN, "windows": [{**PLAN["windows"][0], "caption": "hidden"}]}
    text = write_brief(tmp_path, plan, face=None, duration=41.5).read_text(encoding="utf-8")
    assert "субтитры на этом интервале скрыты" in text


def test_расписание_клипов_передано(tmp_path):
    text = _text(tmp_path, clips=[{"file": "clips/clip-00.mp4", "start": 0.0,
                                   "duration": 6.0}])
    assert "clips/clip-00.mp4" in text
    assert "Клипы с ведущей" in text


def test_содержание_вставки_передано(tmp_path):
    text = _text(tmp_path)
    assert "window-000" in text
    assert "Три вопроса" in text
    assert "Кому продаём" in text
    assert "task_list" in text
    assert "первый вопрос кому продаём" in text


def test_свободные_полосы_указаны(tmp_path):
    text = _text(tmp_path)
    assert "свободн" in text.lower()


def test_запреты_прописаны(tmp_path):
    text = _text(tmp_path)
    assert "не запускай" in text.lower()
    assert "внешн" in text.lower()


def test_причина_повтора_попадает_в_задание(tmp_path):
    text = _text(tmp_path, retry_reason="D8_face: card-01 перекрывает лицо")
    assert "перекрывает лицо" in text


def test_материал_перечислен(tmp_path):
    media = [{"file": "media/shot-1.png", "window_id": "window-000",
              "what": "снимок сайта"}]
    text = _text(tmp_path, media=media)
    assert "media/shot-1.png" in text and "снимок сайта" in text
