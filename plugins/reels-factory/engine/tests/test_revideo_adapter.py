"""Адаптер plan_to_tz: precut-покрытые блоки (insert=true, base чёрный)."""
from reels_factory.revideo_adapter import plan_to_tz


def _timed():
    return {"total": 25.0, "blocks": [
        {"role": "hook", "start": 0.0, "end": 4.0, "speech": "хук"},
        {"role": "development", "start": 4.0, "end": 14.0, "speech": "развитие"},
        {"role": "payoff", "start": 14.0, "end": 22.0, "speech": "настроил один раз и готово"},
        {"role": "cta", "start": 22.0, "end": 25.0, "speech": "подпишись"},
    ]}


def _words():
    # по 2 слова на блок, тайминги ВНУТРИ блоков (с отступом от границ,
    # как у реального транскрипта)
    return [
        {"start": 0.2, "end": 1.8, "text": "хук."},
        {"start": 2.0, "end": 3.7, "text": "внимание."},
        {"start": 4.3, "end": 8.0, "text": "развитие."},
        {"start": 8.4, "end": 13.6, "text": "темы."},
        {"start": 14.3, "end": 18.0, "text": "настроил."},
        {"start": 18.4, "end": 21.6, "text": "готово."},
        {"start": 22.3, "end": 23.5, "text": "подпишись."},
        {"start": 23.8, "end": 24.7, "text": "сейчас."},
    ]


def _covered_segments():
    return [{"role": "development", "insert": True, "offset": 0.0,
             "clip": "lib_clip.mp4", "query": "автоматизация процессов"}]


def test_покрытый_блок_один_fullscreen_на_весь_блок():
    tz = plan_to_tz(_timed(), _covered_segments(), {}, words=_words())
    dev = [s for s in tz["segments"] if s["beat"] == "development"]
    assert len(dev) == 1
    seg = dev[0]
    # границы БЛОКА, не фраз: транскрипт начинается позже границы блока,
    # зазор показал бы чёрный base
    assert seg["start"] == 4.0 and seg["end"] == 14.0
    eff = seg["effect"]
    assert eff["type"] == "broll" and eff["style"] == "fullscreen"
    assert eff["src"] == "lib_clip.mp4" and eff["src_locked"] is True
    assert eff["broll_query"] == "автоматизация процессов"


def test_внутри_покрытого_блока_нет_bubble_и_pip():
    tz = plan_to_tz(_timed(), _covered_segments(), {}, words=_words())
    for s in tz["segments"]:
        if 4.0 <= float(s["start"]) < 14.0:
            eff = s["effect"]
            assert "bubble" not in eff
            assert not (eff.get("type") == "broll" and eff.get("style") == "pip")


def test_без_clip_src_дефолтный_и_не_залочен():
    segs = [{"role": "development", "insert": True, "offset": 2.0}]
    tz = plan_to_tz(_timed(), segs, {}, words=_words())
    dev = [s for s in tz["segments"] if s["beat"] == "development"][0]
    eff = dev["effect"]
    assert eff["src"] == "broll.mp4"
    assert "src_locked" not in eff
    assert eff["offset"] == 2.0


def test_без_insert_блок_остаётся_аватарным():
    segs = [{"role": "development", "offset": 0.0}]  # offset-запись, не покрытие
    tz = plan_to_tz(_timed(), segs, {}, words=_words())
    dev = [s for s in tz["segments"] if s["beat"] == "development"]
    # блок разложен по фразам (не одним fullscreen-сегментом на весь блок)
    assert not any(s["effect"].get("type") == "broll"
                   and s["effect"].get("style") == "fullscreen"
                   and s["start"] == 4.0 and s["end"] == 14.0 for s in dev)


# ---- HyperFrames-триггеры адаптера ----
from reels_factory.revideo_adapter import _stat_from_phrase, _before_after_from_text


def test_stat_from_phrase_ловит_число():
    assert _stat_from_phrase("публикуем 10 статей")["value"] == 10
    assert _stat_from_phrase("нет чисел тут") is None
    assert _stat_from_phrase("число словами десять") is None


def test_before_after_ловит_маркеры():
    ba = _before_after_from_text("было 3 часа стало 1 клик")
    assert ba["before_value"].startswith("3 часа") and ba["after_value"] == "1 клик"
    assert _before_after_from_text("только стало без было") is None


def _timed_stat():
    return {"total": 20.0, "blocks": [
        {"role": "hook", "start": 0.0, "end": 4.0, "speech": "хук"},
        {"role": "development", "start": 4.0, "end": 12.0, "speech": "публикуем 10 статей в день на автопилоте"},
        {"role": "cta", "start": 12.0, "end": 20.0, "speech": "подпишись"},
    ]}


def test_plan_to_tz_эмитит_stat_number_на_цифре():
    words = [
        {"start": 0.3, "end": 3.7, "text": "хук."},
        {"start": 4.3, "end": 7.0, "text": "публикуем 10 статей"},
        {"start": 7.3, "end": 11.6, "text": "в день на автопилоте."},
        {"start": 12.3, "end": 19.6, "text": "подпишись."},
    ]
    tz = plan_to_tz(_timed_stat(), None, {}, words=words)
    hf = [s for s in tz["segments"] if (s["effect"] or {}).get("hyperframes")]
    assert any(h["effect"]["hyperframes"]["block"] == "stat_number" for h in hf)


def test_plan_to_tz_эмитит_before_after_на_маркерах():
    timed = {"total": 20.0, "blocks": [
        {"role": "hook", "start": 0.0, "end": 4.0, "speech": "хук"},
        {"role": "development", "start": 4.0, "end": 12.0, "speech": "было три часа работы стало один клик"},
        {"role": "cta", "start": 12.0, "end": 20.0, "speech": "подпишись"},
    ]}
    words = [
        {"start": 0.3, "end": 3.7, "text": "хук."},
        {"start": 4.3, "end": 7.0, "text": "было три часа работы"},
        {"start": 7.3, "end": 11.6, "text": "стало один клик."},
        {"start": 12.3, "end": 19.6, "text": "подпишись."},
    ]
    tz = plan_to_tz(timed, None, {}, words=words)
    assert any((s["effect"] or {}).get("hyperframes", {}).get("block") == "before_after"
               for s in tz["segments"])
