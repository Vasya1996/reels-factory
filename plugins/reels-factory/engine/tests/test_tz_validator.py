"""Тесты валидатора-линтера монтажного tz (Модуль B)."""
from reels_factory.tz_validator import validate_tz, MIN_SHOT, ERROR, WARN, FIXED


def _seg(sid, start, end, effect=None, camera=None, caption="bottom"):
    return {"id": sid, "start": start, "end": end,
            "effect": effect or {"type": "none"},
            "camera": camera or {"type": "hold"}, "caption": caption}


def _tz(segs, duration=30.0, watermark="@julia.agents", captions=None):
    return {"meta": {"duration": duration}, "brand": {"watermark": watermark},
            "captions": captions or {"keywords": []}, "segments": segs}


def test_чистый_tz_без_ошибок():
    tz = _tz([_seg(1, 0.0, 3.0), _seg(2, 3.0, 6.0, camera={"type": "punch"})])
    rep = validate_tz(tz)
    assert rep.ok
    assert not rep.warns


def test_флеш_кадр_между_двумя():
    tz = _tz([_seg(1, 0.0, 3.0), _seg(2, 3.0, 3.5), _seg(3, 3.5, 6.0)])
    rep = validate_tz(tz)
    assert any(i.rule == "flash-frame" and i.seg_id == 2 for i in rep.warns)


def test_повтор_зума():
    tz = _tz([_seg(1, 0.0, 3.0, camera={"type": "punch"}),
              _seg(2, 3.0, 6.0, camera={"type": "punch"})])
    rep = validate_tz(tz)
    assert any(i.rule == "zoom-repeat" for i in rep.warns)


def test_соседние_одинаковые_эффекты():
    e = {"type": "emoji_pop_sequence"}
    tz = _tz([_seg(1, 0.0, 3.0, effect=dict(e)), _seg(2, 3.0, 6.0, effect=dict(e))])
    rep = validate_tz(tz)
    assert any(i.rule == "effect-adjacent" for i in rep.warns)


def test_разные_broll_стили_подряд_ок():
    tz = _tz([_seg(1, 0.0, 3.0, effect={"type": "broll", "style": "pip", "src": "a.mp4"}),
              _seg(2, 3.0, 6.0, effect={"type": "broll", "style": "fullscreen", "src": "b.mp4"})])
    rep = validate_tz(tz)
    assert not any(i.rule == "effect-adjacent" for i in rep.issues)


def test_broll_без_src_это_ошибка():
    tz = _tz([_seg(1, 0.0, 3.0, effect={"type": "broll", "style": "pip", "src": None})])
    rep = validate_tz(tz)
    assert any(i.rule == "broll-src" and i.level == ERROR for i in rep.issues)
    assert not rep.ok


def test_broll_слабый_матч_без_src_это_ворнинг():
    tz = _tz([_seg(1, 0.0, 3.0,
                   effect={"type": "broll", "style": "pip", "src": None, "broll_weak_match": True})])
    rep = validate_tz(tz)
    assert any(i.rule == "broll-src" and i.level == WARN for i in rep.issues)
    assert rep.ok


def test_повтор_клипа():
    tz = _tz([_seg(1, 0.0, 3.0, effect={"type": "broll", "style": "pip", "src": "x.mp4"}),
              _seg(2, 5.0, 8.0, effect={"type": "broll", "style": "pip", "src": "x.mp4"})])
    rep = validate_tz(tz)
    assert any(i.rule == "broll-dup" for i in rep.warns)


def test_клип_короче_окна():
    tz = _tz([_seg(1, 0.0, 5.0, effect={"type": "broll", "style": "fullscreen", "src": "x.mp4"})])
    rep = validate_tz(tz, index={"x.mp4": {"duration": 2.0}})
    assert any(i.rule == "broll-short" for i in rep.warns)


def test_автофикс_длинного_тире():
    tz = _tz([_seg(1, 0.0, 3.0, effect={"type": "chart_bars", "title": "Что можно — закрыть", "src": "x.mp4"})],
             captions={"keywords": ["авто—мат"]})
    rep = validate_tz(tz, autofix=True)
    assert tz["segments"][0]["effect"]["title"] == "Что можно - закрыть"
    assert tz["captions"]["keywords"][0] == "авто-мат"
    assert any(i.level == FIXED for i in rep.issues)


def test_chart_bars_с_подписью_автофикс_на_hidden():
    tz = _tz([_seg(1, 0.0, 4.0,
                   effect={"type": "chart_bars", "title": "T", "items": []}, caption="bottom")])
    rep = validate_tz(tz, autofix=True)
    assert tz["segments"][0]["caption"] == "hidden"
    assert any(i.rule == "caption-overlay" and i.level == FIXED for i in rep.issues)


def test_chart_bars_hidden_без_претензий():
    tz = _tz([_seg(1, 0.0, 4.0,
                   effect={"type": "chart_bars", "title": "T", "items": []}, caption="hidden")])
    rep = validate_tz(tz)
    assert not any(i.rule == "caption-overlay" for i in rep.issues)


def test_broll_fullscreen_с_подписью_допустим():
    # полноэкранное видео субтитры поверх допускает — правило только для chart_bars
    tz = _tz([_seg(1, 0.0, 4.0,
                   effect={"type": "broll", "style": "fullscreen", "src": "x.mp4"}, caption="top")])
    rep = validate_tz(tz)
    assert not any(i.rule == "caption-overlay" for i in rep.issues)


def test_пустой_watermark_ворнинг():
    tz = _tz([_seg(1, 0.0, 3.0)], watermark="")
    rep = validate_tz(tz)
    assert any(i.rule == "brand" for i in rep.warns)


def test_сегмент_за_пределами_ролика():
    tz = _tz([_seg(1, 0.0, 35.0)], duration=30.0)
    rep = validate_tz(tz)
    assert any(i.rule == "timeline" and i.level == ERROR for i in rep.issues)
