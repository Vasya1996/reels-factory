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
    # duration = реальный конец сегментов, иначе сработает ритм-правило broll-rhythm.
    # ken_burns — разрешённый мягкий дрейф (не резкий зум).
    tz = _tz([_seg(1, 0.0, 3.0), _seg(2, 3.0, 6.0, camera={"type": "ken_burns"})],
             duration=6.0)
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
    # два одинаковых broll fullscreen подряд (разные клипы) — приёмы не чередуются
    e1 = {"type": "broll", "style": "fullscreen", "src": "a.mp4"}
    e2 = {"type": "broll", "style": "fullscreen", "src": "b.mp4"}
    tz = _tz([_seg(1, 0.0, 3.0, effect=e1), _seg(2, 3.0, 6.0, effect=e2)])
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


def test_visual_director_с_подписью_автофикс_на_hidden():
    tz = _tz([_seg(
        1,
        0.0,
        5.0,
        effect={
            "type": "concept_nodes",
            "title": "ОСНОВА",
            "items": ["КОМУ", "ЧТО", "КАК"],
        },
        caption="bottom",
    )], duration=5.0)

    rep = validate_tz(tz, autofix=True)

    assert tz["segments"][0]["caption"] == "hidden"
    assert any(
        issue.rule == "caption-overlay" and issue.level == FIXED
        for issue in rep.issues
    )


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


def test_chat_bubble_убирается_автофиксом():
    tz = _tz([_seg(1, 0.0, 3.0, effect={"type": "chat_bubble", "text": "напиши пост"})])
    rep = validate_tz(tz, autofix=True)
    assert tz["segments"][0]["effect"]["type"] == "none"
    assert any(i.rule == "text-overlay" and i.level == FIXED for i in rep.issues)


# ---- precut-покрытие (covered_ranges) и ритм ----

def _fs(sid, start, end, src="clip.mp4"):
    return _seg(sid, start, end,
                effect={"type": "broll", "style": "fullscreen", "src": src})


def test_precut_блок_полностью_покрыт_ок():
    tz = _tz([_seg(1, 0.0, 3.0), _fs(2, 3.0, 15.0), _seg(3, 15.0, 22.0)],
             duration=22.0)
    rep = validate_tz(tz, covered_ranges=[(3.0, 15.0)])
    assert not any(i.rule.startswith("covered-") for i in rep.issues)


def test_precut_зазор_в_покрытии_это_ошибка():
    tz = _tz([_seg(1, 0.0, 3.0), _fs(2, 5.0, 15.0)], duration=22.0)
    rep = validate_tz(tz, covered_ranges=[(3.0, 15.0)])
    assert any(i.rule == "covered-gap" and i.level == ERROR for i in rep.issues)
    assert not rep.ok


def test_precut_непокрытый_хвост_это_ошибка():
    tz = _tz([_fs(1, 3.0, 12.0)], duration=22.0)
    rep = validate_tz(tz, covered_ranges=[(3.0, 15.0)])
    assert any(i.rule == "covered-gap" and "хвост" in i.message for i in rep.errors)


def test_precut_bubble_внутри_покрытия_это_ошибка():
    eff = {"type": "broll", "style": "fullscreen", "src": "a.mp4",
           "bubble": {"shape": "circle"}}
    tz = _tz([_seg(1, 3.0, 15.0, effect=eff)], duration=22.0)
    rep = validate_tz(tz, covered_ranges=[(3.0, 15.0)])
    assert any(i.rule == "covered-base" for i in rep.errors)


def test_precut_pip_внутри_покрытия_это_ошибка():
    tz = _tz([_fs(1, 3.0, 15.0),
              _seg(2, 5.0, 8.0, effect={"type": "broll", "style": "pip", "src": "b.mp4"})],
             duration=22.0)
    rep = validate_tz(tz, covered_ranges=[(3.0, 15.0)])
    assert any(i.rule == "covered-base" for i in rep.errors)


def test_ритм_ворнинг_дольше_10с_без_broll():
    tz = _tz([_seg(1, 0.0, 12.0), _fs(2, 12.0, 15.0)], duration=15.0)
    rep = validate_tz(tz)
    assert any(i.rule == "broll-rhythm" for i in rep.warns)


def test_ритм_ок_когда_broll_каждые_10с():
    tz = _tz([_seg(1, 0.0, 8.0), _fs(2, 8.0, 11.0), _seg(3, 11.0, 19.0),
              _fs(4, 19.0, 22.0)], duration=22.0)
    rep = validate_tz(tz)
    assert not any(i.rule == "broll-rhythm" for i in rep.warns)


def test_ритм_учитывает_встроенный_visual_state_change():
    tz = _tz([
        _seg(1, 0.0, 8.0),
        _seg(
            2,
            8.0,
            13.0,
            effect={
                "type": "sequence_flow",
                "title": "ПОРЯДОК",
                "items": ["КТО", "ЧТО", "КАК"],
            },
            caption="hidden",
        ),
        _seg(3, 13.0, 21.0),
    ], duration=21.0)

    rep = validate_tz(tz)

    assert not any(issue.rule == "broll-rhythm" for issue in rep.warns)


# ---- новые монтаж-правила: эмодзи, резкие зумы, биролл ≥3с, биролл в хуке ----

def test_эмодзи_запрещены_автофикс():
    tz = _tz([_seg(1, 0.0, 3.0, effect={"type": "emoji_pop_sequence", "items": []})])
    rep = validate_tz(tz, autofix=True)
    assert tz["segments"][0]["effect"]["type"] == "none"
    assert any(i.rule == "emoji-banned" and i.level == FIXED for i in rep.issues)


def test_резкий_зум_ворнинг():
    tz = _tz([_seg(1, 0.0, 3.0, camera={"type": "snap_zoom"})], duration=3.0)
    rep = validate_tz(tz)
    assert any(i.rule == "harsh-zoom" for i in rep.warns)


def test_биролл_короче_3с_ворнинг():
    tz = _tz([_seg(1, 0.0, 2.0, effect={"type": "broll", "style": "fullscreen", "src": "a.mp4"})],
             duration=2.0)
    rep = validate_tz(tz)
    assert any(i.rule == "broll-min-len" for i in rep.warns)


def test_биролл_в_хуке_ворнинг():
    seg = _seg(1, 0.0, 4.0, effect={"type": "broll", "style": "fullscreen", "src": "a.mp4"})
    seg["beat"] = "hook"
    tz = _tz([seg], duration=4.0)
    rep = validate_tz(tz)
    assert any(i.rule == "broll-first-phrase" for i in rep.warns)
