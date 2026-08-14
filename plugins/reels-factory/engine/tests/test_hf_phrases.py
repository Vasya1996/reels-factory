"""Секунды сцен считает код по фразам озвучки, а не агент.

Прогоны 9 и 10: агент тратил по 30–45 тысяч токенов на ход, перебирая зазоры и
минимальные длительности, и всё равно ошибся на три сотых секунды.
"""
import pytest

from reels_factory.hf_phrases import (
    MIN_SCENE, faceless_phrases, lay_out_scenes, phrase_span, phrase_timeline,
)
from reels_factory.hf_rhythm import MAX_STATIC_SPAN

SCENARIO = {
    "total": 12.0,
    "blocks": [
        {"role": "hook", "start": 0.0, "end": 6.0,
         "speech": "Все продажи сводятся к трём вопросам. Порядок решает всё."},
        {"role": "cta", "start": 6.0, "end": 12.0,
         "speech": "Сохрани это видео. Прогони свой продукт по ним."},
    ],
}


def _words(pairs):
    return [{"start": s, "end": e, "text": t} for t, s, e in pairs]


# слова идут ровно по сценарию — так их и отдаёт синтез
WORDS = _words([
    ("Все", 0.0, 0.4), ("продажи", 0.4, 0.9), ("сводятся", 0.9, 1.5),
    ("к", 1.5, 1.6), ("трём", 1.6, 2.0), ("вопросам.", 2.0, 2.6),
    ("Порядок", 3.2, 3.8), ("решает", 3.8, 4.3), ("всё.", 4.3, 4.8),
    ("Сохрани", 6.2, 6.8), ("это", 6.8, 7.0), ("видео.", 7.0, 7.6),
    ("Прогони", 8.2, 8.8), ("свой", 8.8, 9.1), ("продукт", 9.1, 9.7),
    ("по", 9.7, 9.9), ("ним.", 9.9, 10.4),
])


def test_фразы_режутся_по_пунктуации_и_нумеруются():
    phrases = phrase_timeline(SCENARIO, WORDS)
    assert [p["id"] for p in phrases] == [0, 1, 2, 3]
    assert phrases[0]["text"].startswith("Все продажи")
    assert phrases[1]["text"] == "Порядок решает всё."
    assert phrases[2]["role"] == "cta"


def test_граница_фраз_посередине_паузы():
    """Иначе карточка обрывает слово: пауза 2.6–3.2, стык обязан быть на 2.9."""
    phrases = phrase_timeline(SCENARIO, WORDS)
    assert phrases[0]["end"] == pytest.approx(2.9)
    assert phrases[1]["start"] == pytest.approx(2.9)


def test_фраза_знает_когда_она_звучит():
    phrases = phrase_timeline(SCENARIO, WORDS)
    assert phrases[0]["said"] == [0.0, 2.6]


def test_блок_держит_свои_края():
    phrases = phrase_timeline(SCENARIO, WORDS)
    assert phrases[0]["start"] == 0.0
    assert phrases[-1]["end"] == 12.0


def test_пословный_список_разошёлся_со_сценарием_но_фразы_есть():
    """Сборку из-за расхождения не роняем: план агента от этого не хуже."""
    short = [w for i, w in enumerate(WORDS) if i != 3]
    phrases = phrase_timeline(SCENARIO, short)
    assert len(phrases) == 4


def test_несуществующая_фраза_названа_внятно():
    phrases = phrase_timeline(SCENARIO, WORDS)
    with pytest.raises(RuntimeError, match="фразы 0–3"):
        phrase_span(phrases, 0, 9)


# ---------- раскладка сцен ----------

#: ведущая в кадре весь ролик
CLIPS = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 12.0}]

#: клип кончается на 9.0 — хвост 9–12 идёт без ведущей
CLIPS_TAIL = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 9.0}]


def _scenes(*specs):
    return [{"id": f"s-{i:02d}", "phrases": list(span)}
            for i, span in enumerate(specs, start=1)]


def test_сцена_встаёт_на_названные_фразы():
    phrases = phrase_timeline(SCENARIO, WORDS)
    scenes = lay_out_scenes(_scenes((0, 0), (1, 1), (2, 2), (3, 3)), phrases,
                            duration=12.0)
    assert scenes[1]["startSec"] == pytest.approx(2.9, abs=0.034)
    assert scenes[1]["endSec"] == pytest.approx(6.0, abs=0.034)
    # секунд агент больше не называет — их в плане и не было
    assert "phrases" not in scenes[1]


def test_сцены_выстилают_ролик_целиком():
    """Промежутков не бывает: неназванный кусок — это картинка по умолчанию,
    а «по умолчанию» и давало неподвижные куски."""
    phrases = phrase_timeline(SCENARIO, WORDS)
    scenes = lay_out_scenes(_scenes((0, 1), (2, 3)), phrases, duration=12.0)
    assert scenes[0]["startSec"] == 0.0
    assert scenes[-1]["endSec"] == pytest.approx(12.0, abs=0.001)
    for left, right in zip(scenes, scenes[1:]):
        assert left["endSec"] == right["startSec"]


def test_пропущенная_фраза_возвращается_агенту():
    phrases = phrase_timeline(SCENARIO, WORDS)
    with pytest.raises(RuntimeError, match="пропущены фразы"):
        lay_out_scenes(_scenes((0, 0), (2, 3)), phrases, duration=12.0)


def test_фраза_в_двух_сценах_возвращается_агенту():
    phrases = phrase_timeline(SCENARIO, WORDS)
    with pytest.raises(RuntimeError, match="уже заняты"):
        lay_out_scenes(_scenes((0, 1), (1, 3)), phrases, duration=12.0)


def test_недосказанный_хвост_возвращается_агенту():
    phrases = phrase_timeline(SCENARIO, WORDS)
    with pytest.raises(RuntimeError, match="Хвост без сцены"):
        lay_out_scenes(_scenes((0, 1), (2, 2)), phrases, duration=12.0)


def test_сцена_длиннее_предела_возвращается_агенту():
    phrases = phrase_timeline(SCENARIO, WORDS)
    with pytest.raises(RuntimeError, match=f"предел {MAX_STATIC_SPAN:g}"):
        lay_out_scenes(_scenes((0, 3)), phrases, duration=12.0)


def test_вспышка_дотягивается_за_счёт_соседней():
    """Фраза бывает и в две десятых секунды — сцена на ней читается вспышкой."""
    phrases = phrase_timeline(SCENARIO, WORDS)
    phrases[1]["end"] = phrases[1]["start"] + 0.2
    phrases[2]["start"] = phrases[1]["end"]
    scenes = lay_out_scenes(_scenes((0, 0), (1, 1), (2, 2), (3, 3)), phrases,
                            duration=12.0)
    assert scenes[1]["endSec"] - scenes[1]["startSec"] >= MIN_SCENE - 0.034
    assert scenes[2]["startSec"] == scenes[1]["endSec"]


def test_времена_ложатся_на_сетку_кадров():
    phrases = phrase_timeline(SCENARIO, WORDS)
    scenes = lay_out_scenes(_scenes((0, 1), (2, 3)), phrases, duration=12.0)
    for scene in scenes:
        for field in ("startSec", "endSec"):
            assert abs(scene[field] * 30 - round(scene[field] * 30)) < 1e-6


# ---------- где ведущей нет ----------

def test_фразы_без_ведущей_названы_номерами():
    """Агент не видит секунд, значит про пропуски аватара ему говорят фразами."""
    phrases = phrase_timeline(SCENARIO, WORDS)
    assert faceless_phrases(phrases, CLIPS_TAIL, 12.0) == [3]


def test_без_пропусков_список_пуст():
    phrases = phrase_timeline(SCENARIO, WORDS)
    assert faceless_phrases(phrases, CLIPS, 12.0) == []


def test_список_номеров_вместо_пары_не_роняет_план():
    """Боевой прогон 462a1c62: агент вернул `[6, 7, 8]` на сцену из трёх фраз и
    `[13]` на сцену из одной — то же самое другими словами. Раньше это роняло
    попытку с сообщением «нет поля `phrases`»."""
    phrases = [{"id": index, "role": "hook", "text": f"ф{index}",
                "start": index * 2.0, "end": index * 2.0 + 2.0}
               for index in range(4)]
    scenes = [{"id": "s-01", "phrases": [0, 1], "presenter": "full"},
              {"id": "s-02", "phrases": [2, 3, 3], "presenter": "punch"}]
    placed = lay_out_scenes(scenes, phrases, duration=8.0)
    # Поле снимается при раскладке — сцены получают секунды; проверяем их.
    assert [round(scene["startSec"], 2) for scene in placed] == [0.0, 4.0]

    single = [{"id": "s-01", "phrases": [0, 1], "presenter": "full"},
              {"id": "s-02", "phrases": [2], "presenter": "punch"},
              {"id": "s-03", "phrases": [3], "presenter": "full"}]
    placed = lay_out_scenes(single, phrases, duration=8.0)
    assert [round(scene["startSec"], 2) for scene in placed] == [0.0, 4.0, 6.0]
