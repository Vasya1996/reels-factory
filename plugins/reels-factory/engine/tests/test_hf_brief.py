"""Задание агенту: паспорт по контракту фреймворка, материал и границы.

Пооконной раскадровки здесь больше нет намеренно. Планирование битов —
работа агента через hyperframes-creative; когда мы отдавали ему готовые окна,
он переставал быть режиссёром и просто перекладывал наш чертёж в HTML.
"""
from reels_factory.hf_brief import STYLE_NAME, write_brief

SCENARIO = {
    "total": 41.5,
    "blocks": [
        {"role": "hook", "start": 0.0, "end": 12.22,
         "speech": "Все продажи на свете сводятся к трём вопросам"},
        {"role": "development", "start": 12.22, "end": 23.14,
         "speech": "Первый: кому продаём"},
        {"role": "payoff", "start": 23.14, "end": 34.62,
         "speech": "Третий: как продаём"},
        {"role": "cta", "start": 34.62, "end": 41.5,
         "speech": "Сохрани это видео"},
    ],
}

CLIPS = [{"file": "clips/avatar_0.mp4", "start": 0.0, "duration": 12.22}]


def _text(tmp_path, **kw):
    kw.setdefault("scenario", SCENARIO)
    kw.setdefault("clips", CLIPS)
    return write_brief(tmp_path, face={"cx": 540, "cy": 520, "h": 260},
                       duration=41.5, **kw).read_text(encoding="utf-8")


# ---------- паспорт задания ----------

def test_поля_которые_знает_движок_проставлены(tmp_path):
    text = _text(tmp_path)
    for field in ("flow", "storyboard", "mode", "aspect", "length",
                  "language", "narration", "destination"):
        assert field in text, f"нет поля {field}"
    assert "automation" in text
    assert "autonomous" in text
    assert "1080x1920" in text


def test_смысловые_поля_агент_выводит_сам(tmp_path):
    text = _text(tmp_path)
    # message / angle / audience контракт велит выводить, а не спрашивать:
    # в режиме automation спрашивать не у кого.
    for field in ("message", "angle", "audience"):
        assert field in text, f"нет поля {field}"
    assert "выведи" in text.lower() or "вывести" in text.lower()


def test_язык_можно_задать(tmp_path):
    assert "kk" in _text(tmp_path, language="kk")


# ---------- вход ----------

def test_сценарий_по_блокам_передан(tmp_path):
    text = _text(tmp_path)
    for role in ("hook", "development", "payoff", "cta"):
        assert role in text
    assert "Все продажи на свете" in text
    assert "12.22" in text or "12,22" in text


def test_расписание_клипов_передано(tmp_path):
    text = _text(tmp_path)
    assert "clips/avatar_0.mp4" in text
    assert "12.22" in text or "12,22" in text


def test_материал_перечислен(tmp_path):
    text = _text(tmp_path)
    assert "voice.wav" in text and "words.json" in text
    assert "gsap" in text


# ---------- то, чего в задании быть не должно ----------

def test_пооконной_раскадровки_нет(tmp_path):
    text = _text(tmp_path)
    assert "Что показывать по окнам" not in text
    assert "карточку не рисуй" not in text
    assert "window-000" not in text


def test_каталог_разрешён_и_назван(tmp_path):
    text = _text(tmp_path)
    assert "resolve" in text
    assert "registry" in text


# ---------- границы ----------

def test_правила_числами(tmp_path):
    text = _text(tmp_path)
    assert "1080" in text and "1920" in text
    assert STYLE_NAME in text
    assert "41.5" in text or "41,5" in text


def test_свободные_полосы_указаны(tmp_path):
    assert "left=" in _text(tmp_path)


def test_запреты_прописаны(tmp_path):
    text = _text(tmp_path)
    assert "Внешних ссылок нет" in text
    assert "лицо" in text.lower()


def test_интервалы_без_ведущей_названы(tmp_path):
    # клип только на 0–12.22, значит 12.22–41.5 ведущей в кадре нет
    text = _text(tmp_path)
    assert "без ведущей" in text.lower() or "ведущей в кадре нет" in text.lower()


def test_шрифты_врезает_движок(tmp_path):
    text = _text(tmp_path)
    assert "@font-face" not in text or "движок" in text
    assert "Ссылок на внешние шрифты не пиши" in text


def test_причина_повтора_попадает_в_задание(tmp_path):
    assert "лицо перекрыто" in _text(tmp_path, retry_reason="лицо перекрыто")


def test_что_вернуть_названо(tmp_path):
    text = _text(tmp_path)
    assert "public/index.html" in text
    assert "storyboard.json" in text
    assert "contentRect" in text
