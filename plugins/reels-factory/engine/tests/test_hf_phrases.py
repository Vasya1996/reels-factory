"""Секунды карточек считает код по фразам озвучки, а не агент.

Прогоны 9 и 10: агент тратил по 30–45 тысяч токенов на ход, перебирая зазоры и
минимальные длительности, и всё равно ошибся на три сотых секунды.
"""
import pytest

from reels_factory.hf_phrases import lay_out_cards, phrase_span, phrase_timeline
from reels_factory.hf_rhythm import MAX_STATIC_SPAN, MIN_CARD_GAP

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


# ---------- раскладка карточек ----------

#: ведущая в кадре весь ролик — на такой раскладке правило про куски без неё
#: не срабатывает и не мешает смотреть на остальные правила
CLIPS = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 12.0}]

#: клип кончается на 9.0 — хвост 9–12 идёт без ведущей
CLIPS_TAIL = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 9.0}]


def _cards(*specs):
    return [{"id": f"card-{i:02d}", "phrases": list(span)}
            for i, span in enumerate(specs, start=1)]


def test_карточка_встаёт_на_названные_фразы():
    phrases = phrase_timeline(SCENARIO, WORDS)
    cards = lay_out_cards(_cards((1, 1)), phrases, clips=CLIPS, duration=12.0)
    assert cards[0]["startSec"] == pytest.approx(2.9, abs=0.034)
    assert cards[0]["endSec"] == pytest.approx(6.0, abs=0.034)
    # секунд агент больше не называет — их в плане и не было
    assert "phrases" not in cards[0]


def test_короткая_карточка_дотягивается_до_минимума_блока():
    phrases = phrase_timeline(SCENARIO, WORDS)
    cards = lay_out_cards(_cards((0, 0)), phrases, clips=CLIPS, duration=12.0,
                          minimums={"card-01": 4.5})
    assert cards[0]["endSec"] - cards[0]["startSec"] >= 4.5 - 0.034


def test_блок_не_влезающий_в_свои_фразы_возвращается_агенту():
    """Прогон 12: под блок на 6,5 с агент отдал две фразы на три секунды.
    Растянуть некуда — справа следующая карточка на своей реплике."""
    phrases = phrase_timeline(SCENARIO, WORDS)
    with pytest.raises(RuntimeError, match="больше фраз или возьми блок"):
        lay_out_cards(_cards((0, 0), (1, 1), (3, 3)), phrases, clips=CLIPS_TAIL,
                      duration=12.0, minimums={"card-01": 6.5})


def test_карточка_не_длиннее_предела_неподвижного_куска():
    phrases = phrase_timeline(SCENARIO, WORDS)
    cards = lay_out_cards(_cards((0, 3)), phrases, clips=CLIPS, duration=12.0)
    assert cards[0]["endSec"] - cards[0]["startSec"] <= MAX_STATIC_SPAN + 0.001


def test_зазор_между_карточками_держит_код():
    phrases = phrase_timeline(SCENARIO, WORDS)
    cards = lay_out_cards(_cards((0, 0), (1, 1)), phrases, clips=CLIPS,
                          duration=12.0)
    assert cards[1]["startSec"] - cards[0]["endSec"] >= MIN_CARD_GAP - 0.034


def test_кусок_без_ведущей_закрывается_встык():
    """Клип кончается на 9.0, дальше ведущей нет — до 12.0 обязана стоять сцена."""
    phrases = phrase_timeline(SCENARIO, WORDS)
    cards = lay_out_cards(_cards((0, 0), (3, 3)), phrases, clips=CLIPS_TAIL,
                          duration=12.0)
    assert cards[-1]["endSec"] == pytest.approx(12.0, abs=0.034)


def test_незакрытый_кусок_без_ведущей_называется_ошибкой():
    phrases = phrase_timeline(SCENARIO, WORDS)
    with pytest.raises(RuntimeError, match="без ведущей"):
        lay_out_cards(_cards((0, 0)), phrases, clips=CLIPS_TAIL, duration=12.0)


def test_времена_ложатся_на_сетку_кадров():
    phrases = phrase_timeline(SCENARIO, WORDS)
    cards = lay_out_cards(_cards((0, 0), (3, 3)), phrases, clips=CLIPS_TAIL,
                          duration=12.0)
    for card in cards:
        for field in ("startSec", "endSec"):
            assert abs(card[field] * 30 - round(card[field] * 30)) < 1e-6
