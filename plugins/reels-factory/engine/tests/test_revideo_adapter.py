"""Адаптер plan_to_tz: precut-покрытые блоки (insert=true, base чёрный)."""
from reels_factory.revideo_adapter import plan_to_tz


def _timed():
    return {"total": 25.0, "blocks": [
        {"role": "hook", "start": 0.0, "end": 3.0, "speech": "хук"},
        {"role": "development", "start": 3.0, "end": 15.0, "speech": "развитие"},
        {"role": "payoff", "start": 15.0, "end": 22.0, "speech": "настроил один раз и готово"},
        {"role": "cta", "start": 22.0, "end": 25.0, "speech": "подпишись"},
    ]}


def _words():
    # по 2 слова на блок, тайминги ВНУТРИ блоков (с отступом от границ,
    # как у реального транскрипта)
    return [
        {"start": 0.2, "end": 1.4, "text": "хук."},
        {"start": 1.6, "end": 2.7, "text": "внимание."},
        {"start": 3.3, "end": 7.0, "text": "развитие."},
        {"start": 7.4, "end": 14.6, "text": "темы."},
        {"start": 15.3, "end": 18.0, "text": "настроил."},
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
    assert seg["start"] == 3.0 and seg["end"] == 15.0
    eff = seg["effect"]
    assert eff["type"] == "broll" and eff["style"] == "fullscreen"
    assert eff["src"] == "lib_clip.mp4" and eff["src_locked"] is True
    assert eff["broll_query"] == "автоматизация процессов"


def test_внутри_покрытого_блока_нет_bubble_и_pip():
    tz = plan_to_tz(_timed(), _covered_segments(), {}, words=_words())
    for s in tz["segments"]:
        if 3.0 <= float(s["start"]) < 15.0:
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
                   and s["start"] == 3.0 and s["end"] == 15.0 for s in dev)
