"""Тесты семантического подбора b-roll (Модуль B). CLIP не поднимаем —
эмбеддер запроса мокается, косинус считается по заданным векторам индекса."""
import pytest

from reels_factory import broll_library as lib
from reels_factory import broll_retrieval as R
from reels_factory.broll_retrieval import resolve_broll


# Игрушечный индекс в 3-мерном пространстве (косинус работает на любой размерности).
def _index():
    return {
        "keyboard.mp4": {"embedding": [1.0, 0.0, 0.0], "duration": 12.0, "caption": "клавиатура"},
        "robot.mp4":    {"embedding": [0.0, 1.0, 0.0], "duration": 12.0, "caption": "робот"},
        "short.mp4":    {"embedding": [1.0, 0.0, 0.0], "duration": 1.0,  "caption": "короткий"},
    }


# Запрос -> вектор в том же пространстве.
_Q = {
    "клавиатура": [1.0, 0.0, 0.0],
    "робот":      [0.0, 1.0, 0.0],
    "нечто":      [0.3, 0.3, 0.3],
}


@pytest.fixture(autouse=True)
def _mock_embed(monkeypatch):
    monkeypatch.setattr(lib, "embed_text", lambda q: _Q.get(q, [0.0, 0.0, 0.0]))


def _seg(sid, query, start, end, etype="broll", style="pip"):
    eff = {"type": etype, "broll_query": query, "src": "broll.mp4", "offset": 0.0}
    if etype == "broll":
        eff["style"] = style
    return {"id": sid, "start": start, "end": end, "effect": eff}


def test_подбор_ставит_лучший_клип_по_смыслу():
    tz = {"segments": [_seg(1, "клавиатура", 0.0, 3.0)]}
    res = resolve_broll(tz, index=_index())
    assert tz["segments"][0]["effect"]["src"] == "keyboard.mp4"
    assert res.picks[0].score == pytest.approx(1.0)
    assert not res.picks[0].weak
    assert res.used_clips == ["keyboard.mp4"]


def test_дедуп_не_берёт_клип_дважды():
    tz = {"segments": [_seg(1, "клавиатура", 0.0, 3.0),
                       _seg(2, "клавиатура", 4.0, 7.0)]}
    res = resolve_broll(tz, index=_index())
    # первый забрал keyboard.mp4; второму его уже не отдать (short.mp4 отфильтрован по длине)
    assert tz["segments"][0]["effect"]["src"] == "keyboard.mp4"
    assert res.picks[1].clip != "keyboard.mp4"
    assert res.picks[1].weak is True  # остаётся только robot.mp4 с косинусом 0


def test_порог_помечает_слабый_матч():
    tz = {"segments": [_seg(1, "нечто", 0.0, 3.0)]}
    res = resolve_broll(tz, index=_index(), threshold=0.9)
    assert res.picks[0].weak is True
    assert tz["segments"][0]["effect"]["broll_weak_match"] is True


def test_фолбэк_клип_при_слабом_матче():
    tz = {"segments": [_seg(1, "нечто", 0.0, 3.0)]}
    res = resolve_broll(tz, index=_index(), threshold=0.9, fallback_clip="robot.mp4")
    assert tz["segments"][0]["effect"]["src"] == "robot.mp4"
    assert res.picks[0].weak is True


def test_короткий_клип_отсеивается_по_окну():
    # только short.mp4 совпадает по вектору, но он 1с < окна 3с → не берём
    idx = {"short.mp4": {"embedding": [1.0, 0.0, 0.0], "duration": 1.0}}
    tz = {"segments": [_seg(1, "клавиатура", 0.0, 3.0)]}
    res = resolve_broll(tz, index=idx)
    assert res.picks[0].clip is None
    assert res.picks[0].weak is True


def test_particles_эффект_тоже_получает_src():
    tz = {"segments": [_seg(1, "робот", 0.0, 3.0, etype="broll_bg_particles")]}
    res = resolve_broll(tz, index=_index())
    assert tz["segments"][0]["effect"]["src"] == "robot.mp4"


def test_пустой_индекс_помечает_все_broll_слабыми():
    tz = {"segments": [_seg(1, "клавиатура", 0.0, 3.0)]}
    res = resolve_broll(tz, index={})
    assert tz["segments"][0]["effect"]["broll_weak_match"] is True
    assert any("index.json пуст" in x for x in res.log)


def test_сегменты_без_broll_игнорируются():
    tz = {"segments": [{"id": 1, "start": 0, "end": 3, "effect": {"type": "emoji_pop_sequence"}}]}
    res = resolve_broll(tz, index=_index())
    assert res.picks == []
    assert res.used_clips == []
