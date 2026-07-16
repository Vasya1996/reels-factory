"""Оркестрация pipeline.run_make: DI на внешние стадии, без сети/ffmpeg.

verify_reel не параметр run_make (внутренняя QA-логика) — подменяется через
monkeypatch модуля.
"""
import json
from pathlib import Path

import reels_factory.pipeline as pipeline


def _scenario():
    return {"theme": "кофе", "blocks": [
        {"role": "hook", "start": 0.0, "end": 3.0, "speech": "кофе кислит"},
        {"role": "development", "start": 3.0, "end": 15.0, "speech": "молол мелко"},
        {"role": "payoff", "start": 15.0, "end": 22.0, "speech": "стало ровно"},
        {"role": "cta", "start": 22.0, "end": 25.0, "speech": "пиши кофе"},
    ]}


def _cfg(fmt="split"):
    return {"theme": "кофе", "theme_spoken": "кофе", "format": fmt, "voice_id": "v1",
            "product": {"name": "Гайд", "cta_phrase": "пиши кофе",
                        "brand_captions": {"Гайд": ["гайт"]}},
            "avatar": {"heygen_asset_id": "a1"}}


class _FakeAvatar:
    def __init__(self):
        self.avatar_id = "a1"; self.motion_prompt = "m"; self.expressiveness = "medium"
        self.calls = []

    def generate(self, audio_wav, out_mp4):
        self.calls.append(("generate", str(audio_wav), str(out_mp4)))
        out_mp4 = Path(out_mp4)
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(b"")
        return out_mp4


def _fakes(monkeypatch, tmp_path, calls, captured=None):
    monkeypatch.setattr(pipeline, "WORK_ROOT", tmp_path)

    def fake_ingest(source, workdir):
        calls.append(("ingest", source))
        p = Path(workdir) / "broll.mp4"; p.write_bytes(b"")
        return {"video_path": str(p)}

    def fake_synth(text, out_wav, *a, **kw):
        calls.append(("synth", text, kw.get("voice_id")))
        Path(out_wav).write_bytes(b"")
        return Path(out_wav)

    def fake_assemble(rdir, scenario, broll_mp4, offset, out_mp4, **kw):
        calls.append(("assemble", kw.get("format"),
                      len(kw.get("avatar_mp4s") or []), len(kw.get("voice_wavs") or [])))
        if captured is not None:
            captured["caption_fixes"] = kw.get("caption_fixes")
            captured["broll_segments"] = kw.get("broll_segments")
            captured["punch_windows"] = kw.get("punch_windows")
        Path(out_mp4).write_bytes(b"")
        timed = dict(scenario, total=25.0)
        return {"mp4": str(out_mp4), "dur": 25.0, "lufs": -14.0,
                "timed_scenario": timed, "words_fixed": [{"text": "кофе"}]}

    def fake_verify(mp4, scenario, **kw):
        calls.append(("verify", str(mp4), kw.get("words")))
        if captured is not None:
            captured["verify_format"] = kw.get("format")
        return {"all_pass": True, "gates": {}}

    monkeypatch.setattr(pipeline, "verify_reel", fake_verify)
    return fake_ingest, fake_synth, fake_assemble


def _wd_with_scenario(tmp_path):
    wd = tmp_path / "wd"; wd.mkdir()
    (wd / "scenario.json").write_text(json.dumps(_scenario(), ensure_ascii=False), encoding="utf-8")
    return wd


def test_split_happy_path(monkeypatch, tmp_path):
    calls = []
    fi, fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    res = pipeline.run_make(_cfg("split"), "broll.mp4", 30.0, wd,
                            avatar_client=avatar, synth_fn=fs, ingest_fn=fi, assemble_fn=fa)

    assert res["ok"] is True and res["qa_pass"] is True
    stages = [c[0] for c in calls]
    assert stages == ["synth", "synth", "synth", "synth", "ingest", "assemble", "verify"]
    # 4 блока -> 4 генерации аватара (cta через cached_generate тоже завершается generate)
    assert len(avatar.calls) == 4
    assemble_call = next(c for c in calls if c[0] == "assemble")
    assert assemble_call[1] == "split" and assemble_call[2] == 4 and assemble_call[3] == 0
    # cta-аватар осел в общий кэш WORK_ROOT/avatar_cache
    assert Path(avatar.calls[-1][2]).parent == tmp_path / "avatar_cache"
    # words_fixed из assemble прокинуты в verify
    verify_call = next(c for c in calls if c[0] == "verify")
    assert verify_call[2] == [{"text": "кофе"}]


def test_fullscreen_без_аватара(monkeypatch, tmp_path):
    calls = []
    fi, fs, fa = _fakes(monkeypatch, tmp_path, calls)
    wd = _wd_with_scenario(tmp_path)

    res = pipeline.run_make(_cfg("fullscreen"), "broll.mp4", 30.0, wd,
                            synth_fn=fs, ingest_fn=fi, assemble_fn=fa)

    assert res["ok"] is True
    assemble_call = next(c for c in calls if c[0] == "assemble")
    assert assemble_call[1] == "fullscreen" and assemble_call[2] == 0 and assemble_call[3] == 4
    # голос синтезируется с voice_id из конфига
    assert all(c[2] == "v1" for c in calls if c[0] == "synth")


def test_avatar_с_аватаром_без_broll(monkeypatch, tmp_path):
    calls = []
    captured = {}
    fi, fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    # broll_source=None: для avatar видеоряд опционален (нет вставок)
    res = pipeline.run_make(_cfg("avatar"), None, 0.0, wd,
                            avatar_client=avatar, synth_fn=fs, ingest_fn=fi, assemble_fn=fa)

    assert res["ok"] is True and res["qa_pass"] is True
    # ingest пропущен (нет источника видеоряда)
    assert not any(c[0] == "ingest" for c in calls)
    # аватар генерируется на каждый блок (как split)
    assert len(avatar.calls) == 4
    assemble_call = next(c for c in calls if c[0] == "assemble")
    assert assemble_call[1] == "avatar" and assemble_call[2] == 4 and assemble_call[3] == 0
    # verify получает format=avatar
    assert captured["verify_format"] == "avatar"


def test_avatar_со_вставками_ingest_вызывается(monkeypatch, tmp_path):
    calls = []
    captured = {}
    fi, fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)
    broll_plan = {"segments": [{"role": "development", "offset": 30.0, "insert": True}],
                  "facts": {}}

    res = pipeline.run_make(_cfg("avatar"), "broll.mp4", 0.0, wd, broll_plan=broll_plan,
                            avatar_client=avatar, synth_fn=fs, ingest_fn=fi, assemble_fn=fa)

    assert res["ok"] is True
    assert any(c[0] == "ingest" for c in calls)  # источник вставок скачивается
    assert captured["broll_segments"] == broll_plan["segments"]


def test_провал_ingest_даёт_stage_ingest(monkeypatch, tmp_path):
    calls = []
    _, fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    def broken(source, workdir):
        raise RuntimeError("сеть недоступна")

    res = pipeline.run_make(_cfg("split"), "broll.mp4", 30.0, wd,
                            avatar_client=avatar, synth_fn=fs, ingest_fn=broken, assemble_fn=fa)

    assert res["ok"] is False and res["stage"] == "ingest"
    assert res["error"] == "сеть недоступна"


def test_нет_scenario_даёт_stage_scenario(monkeypatch, tmp_path):
    calls = []
    fi, fs, fa = _fakes(monkeypatch, tmp_path, calls)
    wd = tmp_path / "wd"; wd.mkdir()  # scenario.json отсутствует

    res = pipeline.run_make(_cfg("fullscreen"), "broll.mp4", 30.0, wd,
                            synth_fn=fs, ingest_fn=fi, assemble_fn=fa)

    assert res["ok"] is False and res["stage"] == "scenario"


def test_caption_fixes_и_broll_plan_прокидываются(monkeypatch, tmp_path):
    calls = []
    captured = {}
    fi, fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)
    broll_plan = {"segments": [{"role": "hook", "offset": 30.0}], "facts": {}}

    res = pipeline.run_make(_cfg("split"), "broll.mp4", 0.0, wd, broll_plan=broll_plan,
                            avatar_client=avatar, synth_fn=fs, ingest_fn=fi, assemble_fn=fa)

    assert res["ok"] is True
    assert "Гайд" in captured["caption_fixes"]
    assert "кофе" in captured["caption_fixes"]
    assert captured["broll_segments"] == broll_plan["segments"]


def test_punch_из_broll_plan_прокидывается_в_assemble(monkeypatch, tmp_path):
    calls = []
    captured = {}
    fi, fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)
    broll_plan = {"segments": [{"role": "hook", "offset": 30.0}],
                  "punch": [[15.0, 0.5], [20.0, 0.6]], "facts": {}}

    res = pipeline.run_make(_cfg("split"), "broll.mp4", 0.0, wd, broll_plan=broll_plan,
                            avatar_client=avatar, synth_fn=fs, ingest_fn=fi, assemble_fn=fa)

    assert res["ok"] is True
    assert captured["punch_windows"] == broll_plan["punch"]


def test_без_broll_plan_punch_windows_none(monkeypatch, tmp_path):
    calls = []
    captured = {}
    fi, fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    res = pipeline.run_make(_cfg("split"), "broll.mp4", 30.0, wd,
                            avatar_client=avatar, synth_fn=fs, ingest_fn=fi, assemble_fn=fa)

    assert res["ok"] is True
    assert captured["punch_windows"] is None
