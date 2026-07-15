"""Тесты сборки рилса (compose).

Fast: build_video_filter/build_audio_filter/concat-фильтры — чистые строки
filter_complex (без ffmpeg), проверка подстрок.
Slow: интеграционный прогон из синтетики (testsrc/sine) — split и fullscreen,
1080x1920, T≈6.5с. transcribe подменяется через DI (transcribe_fn).
"""
import json
import subprocess
from pathlib import Path

import pytest

from reels_factory.config import FFMPEG
from reels_factory.compose import (
    build_video_filter, build_audio_filter, build_concat_filter, build_voice_concat_filter,
    retime_scenario, assemble, plan_broll_cuts, build_broll_concat_filter, build_punch_filter,
    _slow_src_dur, build_caption_fixes, apply_caption_fixes, _atempo_chain,
    TOP_H, BOT_H, BROLL_VOLUME, WHOOSH_VOLUME, HOOK_PAUSE_S,
)
from reels_factory.verify import _mean_volume
from reels_factory.render import probe_wh, media_dur


def _labels_used_once(fc):
    """Каждая промежуточная метка [name] графа потребляется ровно один раз."""
    import re as _re
    from collections import Counter
    toks = _re.findall(r"\[([a-z][\w]*)\]", fc)  # без сырых входов вида 1:a
    counts = Counter(toks)
    return {name: c for name, c in counts.items() if name != "mix"}


def _scenario():
    return {
        "theme": "кофе",
        "blocks": [
            {"role": "hook", "start": 0.0, "end": 3.0, "speech": "а"},
            {"role": "development", "start": 3.0, "end": 15.0, "speech": "в"},
            {"role": "payoff", "start": 15.0, "end": 22.0, "speech": "г"},
            {"role": "cta", "start": 22.0, "end": 25.0, "speech": "пиши кофе"},
        ],
    }


# --- видео-фильтр ---

def test_build_video_filter_split_vstack():
    fc = build_video_filter("split")
    assert "vstack" in fc
    assert f"scale=1080:{TOP_H}:force_original_aspect_ratio=increase" in fc
    assert f"crop=1080:{TOP_H}" in fc
    assert f"scale=1080:{BOT_H}:force_original_aspect_ratio=increase" in fc
    assert f"crop=1080:{BOT_H}" in fc
    assert "fps=30" in fc
    assert fc.endswith("[v]")


def test_build_video_filter_fullscreen_на_весь_кадр():
    fc = build_video_filter("fullscreen")
    assert "vstack" not in fc
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in fc
    assert "crop=1080:1920" in fc
    assert fc.endswith("[v]")


def test_build_punch_filter_наезд_на_окне():
    parts, out = build_punch_filter("base", [(5.0, 2.0)])
    fc = ";".join(parts)
    assert "split=2" in fc
    assert "crop=iw/1.12:ih/1.12" in fc
    assert "scale=1080:1920" in fc
    assert "between(t,5.0,7.0)" in fc
    assert out == "pw0"


def test_build_video_filter_панч_окно_прокинуто():
    fc = build_video_filter("fullscreen", punch_windows=[(4.0, 1.5)])
    assert "crop=iw/1.12:ih/1.12" in fc
    assert "between(t,4.0,5.5)" in fc
    assert fc.endswith("[v]")


# --- аудио-фильтр ---

def test_build_audio_filter_без_видеоряда_только_голос():
    fc = build_audio_filter(include_game=False)
    assert "sidechaincompress" not in fc
    assert fc == "[0:a]aresample=48000[mix]"


def test_build_audio_filter_постоянный_слой_без_дакинга():
    fc = build_audio_filter(include_game=True)
    assert "sidechaincompress" not in fc  # дакинга нет
    assert f"[1:a]volume={BROLL_VOLUME},aresample=48000[bed]" in fc  # постоянный слой
    assert "amix=inputs=2:normalize=0[mixraw]" in fc  # голос + видеоряд
    assert "alimiter=limit=0.95[mix]" in fc
    assert fc.endswith("[mix]")


def test_build_audio_filter_с_whoosh_входы_и_громкость():
    fc = build_audio_filter(include_game=True, whoosh_delays_ms=[500, 2000])
    assert f"[2:a]volume={WHOOSH_VOLUME},adelay=500:all=1" in fc
    assert f"[3:a]volume={WHOOSH_VOLUME},adelay=2000:all=1" in fc
    # a0 + w0 + w1 + bed = 4 дорожки
    assert "amix=inputs=4:normalize=0[mixraw]" in fc


def test_build_audio_filter_каждая_метка_потребляется_ровно_один_раз():
    fc = build_audio_filter(include_game=True, whoosh_delays_ms=[500, 3000])
    counts = _labels_used_once(fc)
    bad = {name: c for name, c in counts.items() if c != 2}
    assert bad == {}, f"метки с некорректным числом упоминаний: {bad}"


# --- ретайминг ---

def test_retime_накопительный_start_и_пауза_хука():
    sc = _scenario()
    frag_durs = [2.0, 3.0, 4.0, 1.0]
    timed = retime_scenario(sc, frag_durs)
    b = timed["blocks"]
    assert b[0]["start"] == 0.0
    assert b[0]["end"] == 2.0 + HOOK_PAUSE_S      # frag + пауза хука
    assert b[1]["start"] == 2.0 + HOOK_PAUSE_S
    assert b[2]["start"] == 5.0 + HOOK_PAUSE_S
    assert abs(timed["total"] - (10.0 + HOOK_PAUSE_S)) < 1e-9
    assert sc["blocks"][0]["end"] == 3.0          # исходник не мутируется


def test_retime_pause_after_сдвигает_следующий():
    sc = _scenario()
    sc["blocks"][1]["pause_after"] = 0.8
    timed = retime_scenario(sc, [2.0, 3.0, 4.0, 1.0])
    b = timed["blocks"]
    assert abs(b[1]["end"] - (2.5 + 3.0 + 0.8)) < 1e-9
    assert abs(b[2]["start"] - (2.5 + 3.0 + 0.8)) < 1e-9


# --- концат-фильтры ---

def test_build_concat_filter_tpad_только_на_паузе():
    holds = [0.5, 0.0, 0.0, 0.0]
    fc = build_concat_filter(4, holds)
    assert ("[0:v]scale=1080:672:force_original_aspect_ratio=increase,crop=1080:672,"
            "fps=30,setsar=1,tpad=stop_mode=clone:stop_duration=0.500[v0]") in fc
    assert "[0:a]aresample=48000,apad=pad_dur=0.500[a0]" in fc
    assert "[1:v]scale=1080:672:force_original_aspect_ratio=increase,crop=1080:672,fps=30,setsar=1[v1]" in fc
    assert fc.count("tpad") == 1
    assert fc.endswith("concat=n=4:v=1:a=1[v][a]")


def test_build_voice_concat_filter_apad_только_на_паузе():
    holds = [0.5, 0.0]
    fc = build_voice_concat_filter(2, holds)
    assert "[0:a]aresample=48000,apad=pad_dur=0.500[a0]" in fc
    assert "[1:a]aresample=48000[a1]" in fc
    assert fc.count("apad") == 1
    assert fc.endswith("concat=n=2:v=0:a=1[a]")


# --- план видеоряда + slow ---

def _timed_5():
    return {"blocks": [
        {"role": "hook", "start": 0.0, "end": 3.0},
        {"role": "context", "start": 3.0, "end": 8.0},
        {"role": "development", "start": 8.0, "end": 20.0},
        {"role": "payoff", "start": 20.0, "end": 27.0},
        {"role": "cta", "start": 27.0, "end": 30.0},
    ]}


def test_plan_broll_cuts_роли_без_offset_продолжают_предыдущий():
    segments = [{"role": "hook", "offset": 100.0}, {"role": "payoff", "offset": 500.0}]
    cuts = plan_broll_cuts(_timed_5(), segments, src_dur=1000.0)
    starts_durs = [(c["start"], c["src_dur"]) for c in cuts]
    assert starts_durs == [
        (100.0, 3.0), (103.0, 5.0), (108.0, 12.0), (500.0, 7.0), (507.0, 3.0),
    ]
    assert all(c["slow"] is None and c["src_dur"] == c["screen_dur"] for c in cuts)


def test_plan_broll_cuts_гард_выхода_за_конец():
    segments = [{"role": "hook", "offset": 0.0}, {"role": "payoff", "offset": 995.0}]
    try:
        plan_broll_cuts(_timed_5(), segments, src_dur=1000.0)
        assert False, "должен был поднять RuntimeError"
    except RuntimeError as e:
        assert "payoff" in str(e)


def test_plan_broll_cuts_slow_укорачивает_отрезок():
    segments = [{"role": "hook", "offset": 0.0},
                {"role": "development", "offset": 200.0,
                 "slow": {"at": 2.0, "dur": 4.0, "factor": 2}}]
    cuts = plan_broll_cuts(_timed_5(), segments, src_dur=1000.0)
    dev = cuts[2]
    assert dev["screen_dur"] == 12.0
    assert dev["src_dur"] == 10.0     # 12 - 4 + 4/2
    assert cuts[3]["start"] == 210.0  # payoff продолжает по исходному времени


def test_slow_src_dur_математика():
    assert _slow_src_dur(12.0, {"at": 3.0, "dur": 4.0, "factor": 2}) == 10.0


def test_atempo_chain_в_диапазоне():
    assert _atempo_chain(0.5).startswith("atempo=0.5")


def test_atempo_chain_половина_половины():
    assert "atempo=0.5,atempo=0.5" in _atempo_chain(0.25)


def test_atempo_chain_одна_треть_произведение():
    parts = _atempo_chain(1.0 / 3).split(",")
    product = 1.0
    for part in parts:
        val = float(part.replace("atempo=", ""))
        assert 0.5 <= val <= 100.0
        product *= val
    assert abs(product - 1.0 / 3) < 1e-3


def test_build_broll_concat_filter_slow_три_части_и_setpts():
    cuts = [{"start": 0.0, "src_dur": 10.0, "screen_dur": 12.0,
             "slow": {"at": 2.0, "dur": 4.0, "factor": 2}}]
    fc = build_broll_concat_filter(cuts)
    assert "split=3" in fc
    assert "setpts=2.000*(PTS-STARTPTS)" in fc
    assert "atempo=0.500" in fc
    assert "trim=2.000:4.000" in fc
    assert "concat=n=3:v=1:a=0" in fc
    assert fc.endswith("concat=n=1:v=1:a=1[v][a]")


def test_build_broll_concat_filter_высокий_фактор_каскад():
    cuts = [{"start": 0.0, "src_dur": 12.0, "screen_dur": 12.0,
             "slow": {"at": 2.0, "dur": 4.0, "factor": 4}}]
    fc = build_broll_concat_filter(cuts)
    assert "atempo=0.5,atempo=0.5" in fc


def test_build_broll_concat_filter_без_slow():
    cuts = [{"start": 0.0, "src_dur": 3.0, "screen_dur": 3.0, "slow": None},
            {"start": 3.0, "src_dur": 5.0, "screen_dur": 5.0, "slow": None}]
    fc = build_broll_concat_filter(cuts)
    assert "[0:v]fps=30,setsar=1[v0]" in fc
    assert "[1:a]aresample=48000[a1]" in fc
    assert "split=3" not in fc
    assert fc.endswith("concat=n=2:v=1:a=1[v][a]")


# --- caption fixes ---

def test_build_caption_fixes_бренд_и_тема():
    hyp = {"theme": "кофе", "theme_spoken": "кофе", "brand_captions": {"Гайд": ["гайт", "гвайд"]}}
    fixes = build_caption_fixes(hyp)
    assert "Гайд" in fixes and "гайт" in fixes["Гайд"]
    assert "кофе" in fixes
    assert "кофее" in fixes["кофе"]  # падежная словоформа корня темы


def test_apply_caption_fixes_чинит_бренд():
    fixes = build_caption_fixes({"brand_captions": {"Гайд": ["гайт"]}})
    words = [{"start": 0.0, "end": 0.3, "text": "гайт"}]
    assert apply_caption_fixes(words, fixes)[0]["text"] == "Гайд"


def test_apply_caption_fixes_сохраняет_пунктуацию_хвост():
    fixes = build_caption_fixes({"brand_captions": {"Гайд": ["гайт"]}})
    words = [{"start": 0.0, "end": 0.3, "text": "гайт,"}]
    assert apply_caption_fixes(words, fixes)[0]["text"] == "Гайд,"


def test_apply_caption_fixes_не_трогает_обычные():
    fixes = build_caption_fixes({})
    words = [{"start": 0.0, "end": 0.3, "text": "рилса"},
             {"start": 0.3, "end": 0.6, "text": "тест"}]
    assert apply_caption_fixes(words, fixes) == words


def test_apply_caption_fixes_биграмма():
    fixes = build_caption_fixes({"brand_captions": {"вейтлист": ["вейт лист"]}})
    words = [{"start": 0.0, "end": 0.5, "text": "вейт"},
             {"start": 0.5, "end": 1.0, "text": "лист"}]
    result = apply_caption_fixes(words, fixes)
    assert len(result) == 1
    assert result[0]["text"] == "вейтлист"
    assert result[0]["start"] == 0.0 and result[0]["end"] == 1.0


def test_apply_caption_fixes_тема_падежная_форма():
    fixes = build_caption_fixes({"theme": "пабг", "theme_spoken": "пабг"})
    words = [{"start": 0.0, "end": 0.3, "text": "пабге"}]
    assert apply_caption_fixes(words, fixes)[0]["text"] == "пабг"


def test_build_caption_fixes_многословная_тема_не_ломает_theme_spoken():
    # regression: theme "домашний кофе" / theme_spoken "кофе" — theme_spoken
    # тут не падежная форма темы, а сокращение. Раньше авто-словоформы корня
    # ("кофе"+суффиксы) регистрировались как варианты для замены на ВСЮ фразу
    # темы, и корректно распознанное "кофе" (в т.ч. внутри дословной CTA)
    # подменялось на "домашний кофе" — сабы переставали совпадать с речью.
    hyp = {"theme": "домашний кофе", "theme_spoken": "кофе"}
    fixes = build_caption_fixes(hyp)
    words = [{"start": 0.0, "end": 0.3, "text": "кофе"}]
    assert apply_caption_fixes(words, fixes)[0]["text"] == "кофе"


# --- интеграция (slow) ---

def _lavfi_clip(path, dur, size="1280x720", freq=440):
    subprocess.run([
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30:duration={dur}",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={dur}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(path),
    ], check=True, capture_output=True)


def _lavfi_wav(path, dur, freq=660):
    subprocess.run([
        FFMPEG, "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={dur}",
        "-ar", "48000", "-ac", "2", str(path),
    ], check=True, capture_output=True)


def _slow_scenario():
    return {
        "theme": "кофе",
        "blocks": [
            {"role": "hook", "start": 0.0, "end": 3.0, "speech": "а"},
            {"role": "development", "start": 3.0, "end": 15.0, "speech": "в"},
            {"role": "payoff", "start": 15.0, "end": 22.0, "speech": "г"},
            {"role": "cta", "start": 22.0, "end": 25.0, "speech": "пиши кофе"},
        ],
    }


_FAKE_WORDS = [
    {"start": 0.5, "end": 1.0, "text": "тест"},
    {"start": 1.0, "end": 1.6, "text": "кофе"},
]
_FRAG_DURS = [1.5, 2.0, 1.5, 1.0]


def _assert_common(res, out):
    expected_total = sum(_FRAG_DURS) + HOOK_PAUSE_S
    assert abs(res["timed_scenario"]["total"] - expected_total) < 0.1
    assert Path(res["mp4"]).exists()
    assert probe_wh(str(out)) == (1080, 1920)
    assert abs(media_dur(str(out)) - expected_total) < 0.3
    assert res["lufs"] is not None
    # D5: голос слышен в окне первой реплики; D6: слой видеоряда в паузе после хука
    hook_end = res["timed_scenario"]["blocks"][0]["end"]
    voice_mv = _mean_volume(str(out), 0.2, hook_end - HOOK_PAUSE_S - 0.1)
    assert voice_mv is not None and voice_mv >= -35.0, f"голос тихий: {voice_mv} dB"
    bed_mv = _mean_volume(str(out), hook_end - HOOK_PAUSE_S + 0.05, hook_end - 0.05)
    assert bed_mv is not None and bed_mv >= -50.0, f"слой видеоряда тихий: {bed_mv} dB"


@pytest.mark.slow
def test_assemble_split_синтетика(tmp_path):
    rdir = tmp_path / "rdir"; rdir.mkdir()
    avatar_mp4s = []
    for i, d in enumerate(_FRAG_DURS):
        p = tmp_path / f"a{i}.mp4"
        _lavfi_clip(p, d, size="1080x672", freq=300 + 20 * i)
        avatar_mp4s.append(p)
    broll = tmp_path / "broll.mp4"
    _lavfi_clip(broll, 15, size="1920x1080", freq=200)

    out = tmp_path / "out.mp4"
    res = assemble(rdir, _slow_scenario(), broll, 0.0, out, format="split",
                   avatar_mp4s=avatar_mp4s, transcribe_fn=lambda vw, rd: _FAKE_WORDS)

    _assert_common(res, out)
    assert res["words_fixed"] == apply_caption_fixes(_FAKE_WORDS, build_caption_fixes({}))
    assert (rdir / "words.fixed.json").exists()
    assert json.loads((rdir / "words.fixed.json").read_text(encoding="utf-8")) == res["words_fixed"]


@pytest.mark.slow
def test_assemble_fullscreen_синтетика(tmp_path):
    rdir = tmp_path / "rdir"; rdir.mkdir()
    voice_wavs = []
    for i, d in enumerate(_FRAG_DURS):
        p = tmp_path / f"v{i}.wav"
        _lavfi_wav(p, d, freq=440 + 30 * i)
        voice_wavs.append(p)
    broll = tmp_path / "broll.mp4"
    _lavfi_clip(broll, 15, size="1920x1080", freq=200)

    out = tmp_path / "out.mp4"
    res = assemble(rdir, _slow_scenario(), broll, 0.0, out, format="fullscreen",
                   voice_wavs=voice_wavs, transcribe_fn=lambda vw, rd: _FAKE_WORDS)

    _assert_common(res, out)
