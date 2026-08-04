"""Задание агенту: паспорт по контракту фреймворка, материал и границы.

Пооконной раскадровки здесь больше нет намеренно. Планирование битов —
работа агента через hyperframes-creative; когда мы отдавали ему готовые окна,
он переставал быть режиссёром и просто перекладывал наш чертёж в HTML.
"""
from reels_factory.hf_brief import FONTS, write_brief

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


# ---------- то, чего в задании быть не должно ----------

def test_пооконной_раскадровки_нет(tmp_path):
    text = _text(tmp_path)
    assert "Что показывать по окнам" not in text
    assert "карточку не рисуй" not in text
    assert "window-000" not in text


def test_паспорта_блоков_в_задании(tmp_path):
    """Блоки описаны слотами прямо в задании: открывать их файлы незачем."""
    text = _text(tmp_path)
    assert "g02-avatar-fullscreen-hook" in text
    assert "`line-1`" in text and "роль presenter" in text
    # Плашка-рубрика блока агенту не предлагается вовсе.
    assert "Рубрика · Глава" not in text


# ---------- границы ----------

def test_правила_числами(tmp_path):
    text = _text(tmp_path)
    assert "1080" in text and "1920" in text
    assert "41.5" in text or "41,5" in text


def test_гарнитуры_наши(tmp_path):
    """Гарнитуры держим сами: другие не несут кириллицу и казахские буквы."""
    assert FONTS in _text(tmp_path)


def test_вёрстку_у_агента_не_просят(tmp_path):
    """Изготовление ушло коду целиком: разметки в ответе агента больше нет."""
    text = _text(tmp_path)
    assert "public/cards/" not in text
    assert "data-anim" not in text
    assert "Не пиши HTML" in text


def test_интервалы_без_ведущей_названы(tmp_path):
    # клип только на 0–12.22, значит 12.22–41.5 ведущей в кадре нет
    text = _text(tmp_path)
    assert "без ведущей" in text.lower() or "ведущей в кадре нет" in text.lower()


def test_причина_повтора_попадает_в_задание(tmp_path):
    assert "лицо перекрыто" in _text(tmp_path, retry_reason="лицо перекрыто")


def test_что_вернуть_названо(tmp_path):
    text = _text(tmp_path)
    assert "storyboard.json" in text
    # Композицию собирает код — просить её у агента больше нельзя.
    assert "public/index.html" not in text
    assert "catalogGaps" in text


def test_у_агента_просят_только_карточки(tmp_path):
    """Шапку схемы заполняет код: решений в ней нет, а разойтись есть где —
    на Sonnet агент отдал videoTrack списком и потерял попытку."""
    text = _text(tmp_path)
    assert '"cards"' in text
    assert "contentHints" in text and '"intent"' in text
    assert '"videoTrack"' not in text and '"schemaVersion": 3,' not in text
    # Поля, которые мы просили сверх схемы, противоречили videoTrack.bounds.
    assert "contentRect" not in text and "videoRect" not in text


def test_вставки_названы_обязательными(tmp_path):
    text = _text(tmp_path)
    assert "не меньше двух" in text
    assert "`media`" in text


def test_субтитры_снимаются_с_агента(tmp_path):
    text = _text(tmp_path)
    assert "Субтитры" in text
    assert "в карточки не превращай" in text


def test_плотность_карточек_по_их_формуле(tmp_path):
    assert "плотност" in _text(tmp_path).lower()


def test_положение_ведущей_обязано_меняться(tmp_path):
    text = _text(tmp_path).lower()
    assert "положение ведущей" in text
    assert "не меньше трёх раз" in text


def test_зазор_между_карточками_назван_числом(tmp_path):
    """Карточки впритык детектор видит одной склейкой — планка не берётся."""
    text = _text(tmp_path)
    assert "зазор" in text and "0.8 с" in text


def test_пробел_каталога_записывается_а_не_закрывается_вёрсткой(tmp_path):
    text = _text(tmp_path)
    assert "пробел каталога" in text.lower()
    assert "catalogGaps" in text


def test_служебные_надписи_запрещены(tmp_path):
    text = _text(tmp_path)
    assert "Служебных надписей на экране не бывает" in text
    assert "фото из каталога" in text


def test_число_карточек_дано_числами(tmp_path):
    """Sonnet сдал 11 карточек при потолке 10: формулу считаем за него."""
    text = _text(tmp_path)
    assert "от 5 до 10" in text


def test_лишняя_работа_запрещена_явно(tmp_path):
    """16 минут на план — это чтение их справочников и попытки собрать самому."""
    text = _text(tmp_path)
    assert "Чего не делать" in text
    assert "hyperframes check" in text
    assert "справочники по темам" in text
