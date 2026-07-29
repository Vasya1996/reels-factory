"""Оркестрация pipeline.run_make: DI на внешние стадии, без сети/ffmpeg.

verify_reel не параметр run_make (внутренняя QA-логика) — подменяется через
monkeypatch модуля.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import reels_factory.pipeline as pipeline


def _scenario():
    return {"theme": "кофе", "blocks": [
        {"role": "hook", "start": 0.0, "end": 4.0, "speech": "кофе кислит"},
        {"role": "development", "start": 4.0, "end": 14.0, "speech": "молол мелко"},
        {"role": "payoff", "start": 14.0, "end": 22.0, "speech": "стало ровно"},
        {"role": "cta", "start": 22.0, "end": 25.0, "speech": "пиши кофе"},
    ]}


def _cfg(fmt="split"):
    return {"theme": "кофе", "theme_spoken": "кофе", "format": fmt, "voice_id": "v1",
            "product": {"name": "Гайд", "cta_phrase": "пиши кофе",
                        "brand_captions": {"Гайд": ["гайт"]}},
            "avatar": {"heygen_asset_id": "a1"}}


def _fake_covered_block(calls_out=None):
    """Фейк render_covered_block — без реального ffmpeg (voice_*.wav в тестах
    пустые, media_dur на них упал бы)."""
    def _fn(wav, out_mp4):
        if calls_out is not None:
            calls_out.append(str(wav))
        out_mp4 = Path(out_mp4)
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(b"")
        return out_mp4
    return _fn


class _FakeAvatar:
    def __init__(self):
        self.avatar_id = "a1"; self.motion_prompt = "m"; self.expressiveness = "medium"
        self.look_id = None; self.engine = "avatar_v"; self.resolution = "1080p"
        self.calls = []

    def generate(self, audio_wav, out_mp4, role=None):
        self.calls.append(("generate", str(audio_wav), str(out_mp4)))
        self.roles = getattr(self, "roles", []) + [role]
        out_mp4 = Path(out_mp4)
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(b"")
        return out_mp4


def _fake_master_audio(scenario, config, workdir, voice_id=None, meter=None):
    """Дефолтный фейк build_master_audio для тестов, не передающих
    master_audio_fn явно. Дефолт master_audio_enabled теперь True, поэтому
    без этой подмены такие тесты пошли бы в настоящую сборку (сеть,
    ElevenLabs). В отличие от точечных фейков в отдельных тестах (плоские
    2-секундные блоки — там нет B-roll окон, чувствительных к длительности),
    здесь тайминг блока берётся из уже заданных scenario start/end: иначе
    finalize_edit_plan пересчитывает окна precut/broll на куцые куски и
    validate_edit_plan сносит покрытие обратно на avatar."""
    wd = Path(workdir)
    master_wav = wd / "voice_master.wav"
    master_wav.write_bytes(b"master")
    block_wavs = []
    words = []
    timed = json.loads(json.dumps(scenario))
    for index, block in enumerate(timed["blocks"]):
        start, end = float(block["start"]), float(block["end"])
        wav = wd / f"voice_{index}.wav"
        wav.write_bytes(b"slice")
        block_wavs.append(wav)
        pad = min(0.2, (end - start) / 4.0)
        words.append({
            "start": start + pad,
            "end": end - pad,
            "text": block["speech"],
            "block_index": index,
        })
    timed["total"] = float(timed["blocks"][-1]["end"])
    return SimpleNamespace(
        wav=master_wav,
        block_wavs=tuple(block_wavs),
        words=tuple(words),
        timed_scenario=timed,
    )


def _fakes(monkeypatch, tmp_path, calls, captured=None):
    monkeypatch.setattr(pipeline, "WORK_ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "_build_master_audio", _fake_master_audio)

    def fake_synth(text, out_wav, *a, **kw):
        calls.append(("synth", text, kw.get("voice_id")))
        Path(out_wav).write_bytes(b"")
        return Path(out_wav)

    def fake_assemble(rdir, timed_scenario, **kw):
        out = Path(kw.get("out_mp4") or (Path(rdir) / "reel.mp4"))
        out.write_bytes(b"")
        calls.append(("assemble", kw.get("avatar_render_plan"), timed_scenario))
        if captured is not None:
            captured.update(kw)
            captured["timed_scenario"] = timed_scenario
        return {"mp4": str(out), "dur": float(timed_scenario.get("total") or 0.0),
                "timed_scenario": timed_scenario,
                "words_fixed": kw.get("alignment_words") or [],
                "gates": {"D8_face": "PASS"},
                "agent_cost_usd": 0.05}

    def fake_verify(mp4, scenario, **kw):
        calls.append(("verify", str(mp4), kw.get("words")))
        if captured is not None:
            captured["verify_format"] = kw.get("format")
        return {"all_pass": True, "gates": {}}

    monkeypatch.setattr(pipeline, "verify_reel", fake_verify)
    return fake_synth, fake_assemble


def _wd_with_scenario(tmp_path):
    wd = tmp_path / "wd"; wd.mkdir()
    (wd / "scenario.json").write_text(json.dumps(_scenario(), ensure_ascii=False), encoding="utf-8")
    return wd


def test_split_happy_path(monkeypatch, tmp_path):
    calls = []
    captured = {}
    fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    res = pipeline.run_make(_cfg("split"), wd,
                            avatar_client=avatar, synth_fn=fs, assemble_fn=fa)

    assert res["ok"] is True and res["qa_pass"] is True
    stages = [c[0] for c in calls]
    # master_audio включён по умолчанию: голос приходит одним фейком из
    # _fakes (master_audio_fn), per-block synth_fn больше не вызывается.
    assert stages == ["assemble", "verify"]
    # 4 блока -> 4 генерации аватара (cta через cached_generate тоже завершается generate)
    assert len(avatar.calls) == 4
    assemble_call = next(c for c in calls if c[0] == "assemble")
    # новый сборщик получает ретаймленный сценарий первым позиционным
    # аргументом; islands выключены — плана рендера аватара нет
    assert assemble_call[1] is None
    assert assemble_call[2] == captured["timed_scenario"]
    assert assemble_call[2]["total"] == 25.0
    assert len(captured["avatar_mp4s"]) == 4
    assert captured["out_mp4"] == wd / "reel.mp4"
    # cta-аватар осел в общий кэш WORK_ROOT/avatar_cache
    assert Path(avatar.calls[-1][2]).parent == tmp_path / "avatar_cache"
    # words_fixed из assemble прокинуты в verify
    verify_call = next(c for c in calls if c[0] == "verify")
    assert verify_call[2] == captured["alignment_words"]
    # гейты вставок от сборщика слились с гейтами verify
    assert res["gates"]["D8_face"] == "PASS"


def test_fullscreen_не_поддержан_и_падает_до_оплаты(monkeypatch, tmp_path):
    """format=fullscreen новый сборщик не умеет. Отказ обязан прийти ДО
    ElevenLabs и HeyGen: иначе понятная ошибка стоит денег."""
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    res = pipeline.run_make(_cfg("fullscreen"), wd, avatar_client=avatar,
                            synth_fn=fs, assemble_fn=fa)

    assert res["ok"] is False and res["stage"] == "config"
    assert "fullscreen" in res["error"]
    assert calls == []  # ни синтеза, ни сборки, ни verify
    assert avatar.calls == []  # HeyGen не дёрнут
    assert not (wd / "voice_master.wav").exists()  # ElevenLabs не дёрнут


def test_без_мастер_звука_падает_до_оплаты(monkeypatch, tmp_path):
    """Мастер-звук обязателен: путь с поблочным TTS новый сборщик не
    поддерживает. Проверка стоит там же, до платных вызовов."""
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)
    cfg = _cfg("avatar")
    cfg["master_audio"] = {"enabled": False}

    res = pipeline.run_make(cfg, wd, avatar_client=avatar,
                            synth_fn=fs, assemble_fn=fa)

    assert res["ok"] is False and res["stage"] == "config"
    assert "master_audio" in res["error"]
    assert calls == []
    assert avatar.calls == []


def test_avatar_с_аватаром_без_broll(monkeypatch, tmp_path):
    calls = []
    captured = {}
    fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    # avatar собирается и без низового видеоряда вовсе (нет вставок)
    res = pipeline.run_make(_cfg("avatar"), wd,
                            avatar_client=avatar, synth_fn=fs, assemble_fn=fa)

    assert res["ok"] is True and res["qa_pass"] is True
    # аватар генерируется на каждый блок (как split)
    assert len(avatar.calls) == 4
    assert len(captured["avatar_mp4s"]) == 4
    # format в сборщик больше не уходит — он остался только у verify
    assert captured["verify_format"] == "avatar"


def test_master_audio_одна_озвучка_вместо_block_tts(monkeypatch, tmp_path):
    calls = []
    captured = {}
    fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)
    master_calls = []

    def fake_master(scenario, config, workdir, voice_id=None, meter=None):
        master_calls.append((scenario, config, Path(workdir), voice_id))
        master_wav = Path(workdir) / "voice_master.wav"
        master_wav.write_bytes(b"master")
        block_wavs = []
        for index in range(len(scenario["blocks"])):
            wav = Path(workdir) / f"voice_{index}.wav"
            wav.write_bytes(b"slice")
            block_wavs.append(wav)
        timed = json.loads(json.dumps(scenario))
        for index, block in enumerate(timed["blocks"]):
            block["start"] = index * 2.0
            block["end"] = (index + 1) * 2.0
        timed["total"] = 8.0
        return SimpleNamespace(
            wav=master_wav,
            block_wavs=tuple(block_wavs),
            words=tuple(
                {
                    "start": index * 2.0 + 0.2,
                    "end": (index + 1) * 2.0 - 0.2,
                    "text": block["speech"],
                    "block_index": index,
                }
                for index, block in enumerate(timed["blocks"])
            ),
            timed_scenario=timed,
        )

    cfg = _cfg("avatar")
    cfg["master_audio"] = {"enabled": True}
    res = pipeline.run_make(
        cfg, wd, avatar_client=avatar, synth_fn=fs,
        assemble_fn=fa, master_audio_fn=fake_master,
    )

    assert res["ok"] is True
    assert len(master_calls) == 1
    assert master_calls[0][3] == "v1"
    assert not any(call[0] == "synth" for call in calls)
    assert len(avatar.calls) == 4
    assert captured["master_audio"] == wd / "voice_master.wav"
    assert len(captured["alignment_words"]) == 4
    assert captured["alignment_words"][0]["block_index"] == 0
    assert captured["alignment_words"][-1]["block_index"] == 3
    assert captured["timed_scenario"]["total"] == 8.0
    assert captured["edit_plan"]["status"] == "final"
    assert all(
        phrase["final_timing"] for phrase in captured["edit_plan"]["phrases"]
    )


def test_master_audio_не_разрешает_jump_cuts_ломать_timeline(monkeypatch, tmp_path):
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)
    cut_calls = []

    def fake_master(scenario, config, workdir, voice_id=None, meter=None):
        master_wav = Path(workdir) / "voice_master.wav"
        master_wav.write_bytes(b"master")
        slices = []
        for index in range(len(scenario["blocks"])):
            wav = Path(workdir) / f"voice_{index}.wav"
            wav.write_bytes(b"slice")
            slices.append(wav)
        timed = json.loads(json.dumps(scenario))
        for index, block in enumerate(timed["blocks"]):
            block["start"] = index * 2.0
            block["end"] = (index + 1) * 2.0
        timed["total"] = 8.0
        return SimpleNamespace(
            wav=master_wav,
            block_wavs=tuple(slices),
            words=tuple(
                {
                    "start": index * 2.0 + 0.2,
                    "end": (index + 1) * 2.0 - 0.2,
                    "text": block["speech"],
                    "block_index": index,
                }
                for index, block in enumerate(timed["blocks"])
            ),
            timed_scenario=timed,
        )

    def fake_cut(*args, **kwargs):
        cut_calls.append(1)
        return args[0]

    cfg = _cfg("avatar")
    cfg["master_audio"] = {"enabled": True}
    cfg["edit"] = {"jump_cuts": True}
    res = pipeline.run_make(
        cfg, wd, avatar_client=avatar, synth_fn=fs,
        assemble_fn=fa, master_audio_fn=fake_master,
        jump_cut_fn=fake_cut,
    )

    assert res["ok"] is True
    assert cut_calls == []


def test_avatar_islands_заменяет_block_by_block_photo_avatar_iv(
    monkeypatch, tmp_path
):
    calls = []
    captured = {}
    fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    avatar.engine = "avatar_iv"
    wd = _wd_with_scenario(tmp_path)

    def fake_master(scenario, config, workdir, voice_id=None, meter=None):
        master_wav = Path(workdir) / "voice_master.wav"
        master_wav.write_bytes(b"master-islands")
        block_wavs = []
        words = []
        timed = json.loads(json.dumps(scenario))
        for index, block in enumerate(timed["blocks"]):
            block["start"] = index * 2.0
            block["end"] = (index + 1) * 2.0
            wav = Path(workdir) / f"voice_{index}.wav"
            wav.write_bytes(b"legacy-slice")
            block_wavs.append(wav)
            words.append({
                "start": index * 2.0 + 0.2,
                "end": (index + 1) * 2.0 - 0.2,
                "text": block["speech"],
                "block_index": index,
            })
        timed["total"] = 8.0
        return SimpleNamespace(
            wav=master_wav,
            block_wavs=tuple(block_wavs),
            words=tuple(words),
            timed_scenario=timed,
        )

    rendered_plans = []

    def fake_render(master_wav, plan, client, workdir, cache_dir, *, edit_plan,
                     meter=None):
        rendered_plans.append(plan)
        clips = []
        for shot in plan["shots"]:
            clip = Path(workdir) / f"{shot['id']}.mp4"
            clip.write_bytes(b"offline-avatar-iv")
            clips.append(clip)
        return SimpleNamespace(
            clips=tuple(clips),
            plan=plan,
            manifest={"shots": [{"status": "ready"} for _ in clips]},
        )

    cfg = _cfg("avatar")
    cfg["master_audio"] = {"enabled": True}
    cfg["avatar_islands"] = {"enabled": True}
    res = pipeline.run_make(
        cfg,
        wd,
        avatar_client=avatar,
        synth_fn=fs,
        assemble_fn=fa,
        master_audio_fn=fake_master,
        avatar_render_fn=fake_render,
    )

    assert res["ok"] is True, res["error"]
    assert avatar.calls == []  # no legacy block-level requests
    assert len(rendered_plans) == 1
    plan = rendered_plans[0]
    assert plan["engine_scope"] == "photo_avatar_iv"
    assert plan["validation"]["all_pass"] is True
    assert captured["avatar_render_plan"] == plan
    # план рендера аватара доехал до сборщика вторым элементом кортежа
    assemble_call = next(call for call in calls if call[0] == "assemble")
    assert assemble_call[1] == plan
    assert len(captured["avatar_mp4s"]) == len(plan["shots"])
    assert res["avatar_summary"] == plan["summary"]


def test_avatar_islands_с_meter_не_падает_и_тарифицирует_шоты(monkeypatch, tmp_path):
    """Предохранитель ветки avatar_islands снят: с master_audio и переданным
    meter сборка не падает RuntimeError'ом, а счётчик получает секунды по
    каждому отрендеренному шоту. Фейки, без живых вызовов HeyGen/ffmpeg."""
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    avatar.engine = "avatar_iv"
    wd = _wd_with_scenario(tmp_path)
    meter = _FakeMeter()

    def fake_master(scenario, config, workdir, voice_id=None, meter=None):
        master_wav = Path(workdir) / "voice_master.wav"
        master_wav.write_bytes(b"master-islands")
        block_wavs = []
        words = []
        timed = json.loads(json.dumps(scenario))
        for index, block in enumerate(timed["blocks"]):
            block["start"] = index * 2.0
            block["end"] = (index + 1) * 2.0
            wav = Path(workdir) / f"voice_{index}.wav"
            wav.write_bytes(b"legacy-slice")
            block_wavs.append(wav)
            words.append({
                "start": index * 2.0 + 0.2,
                "end": (index + 1) * 2.0 - 0.2,
                "text": block["speech"],
                "block_index": index,
            })
        timed["total"] = 8.0
        return SimpleNamespace(
            wav=master_wav,
            block_wavs=tuple(block_wavs),
            words=tuple(words),
            timed_scenario=timed,
        )

    rendered_shot_counts = []

    def fake_render(master_wav, plan, client, workdir, cache_dir, *, edit_plan,
                     meter=None):
        rendered_shot_counts.append(len(plan["shots"]))
        clips = []
        for shot in plan["shots"]:
            clip = Path(workdir) / f"{shot['id']}.mp4"
            clip.write_bytes(b"offline-avatar-iv")
            clips.append(clip)
            if meter is not None:
                meter(3.5, cached=False, twin=False)
        return SimpleNamespace(
            clips=tuple(clips),
            plan=plan,
            manifest={"shots": [{"status": "ready"} for _ in clips]},
        )

    cfg = _cfg("avatar")
    cfg["master_audio"] = {"enabled": True}
    cfg["avatar_islands"] = {"enabled": True}
    res = pipeline.run_make(
        cfg,
        wd,
        avatar_client=avatar,
        synth_fn=fs,
        assemble_fn=fa,
        master_audio_fn=fake_master,
        avatar_render_fn=fake_render,
        meter=meter,
    )

    assert res["ok"] is True, res.get("error")
    assert len(meter.heygen_calls) == rendered_shot_counts[0]
    assert all(
        seconds == 3.5 and cached is False and twin is False
        for seconds, cached, twin in meter.heygen_calls
    )


def test_avatar_блок_на_100pct_закрытый_вставкой_не_дёргает_heygen(monkeypatch, tmp_path):
    """development на 100% под вставкой (insert=True) -> HeyGen не рендерит его,
    вместо этого дешёвый локальный covered_block_fn (голос поверх чёрного кадра)."""
    calls = []
    captured = {}
    fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    def fake_precut(scenario, config):
        return {"segments": [{"role": "development", "offset": 30.0, "insert": True}],
                "facts": {}, "log": []}

    covered_calls = []

    res = pipeline.run_make(_cfg("avatar"), wd, precut_fn=fake_precut,
                            avatar_client=avatar, synth_fn=fs, assemble_fn=fa,
                            covered_block_fn=_fake_covered_block(covered_calls))

    assert res["ok"] is True
    # development пропущен у HeyGen — остались только hook, payoff, cta (3, не 4)
    assert len(avatar.calls) == 3
    assert not any("voice_1.wav" in str(c[1]) for c in avatar.calls)
    # вместо этого ровно один вызов дешёвого локального рендера, на voice_1.wav
    assert len(covered_calls) == 1
    assert "voice_1.wav" in covered_calls[0]
    # общее число фрагментов аватара для сборки не меняется (4 — все блоки покрыты)
    assert len(captured["avatar_mp4s"]) == 4


def test_нет_scenario_даёт_stage_scenario(monkeypatch, tmp_path):
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    wd = tmp_path / "wd"; wd.mkdir()  # scenario.json отсутствует

    # format=split: fullscreen теперь отбивается раньше чтения scenario.json
    res = pipeline.run_make(_cfg("split"), wd,
                            synth_fn=fs, assemble_fn=fa)

    assert res["ok"] is False and res["stage"] == "scenario"


def test_несовпадение_языка_останавливает_pipeline_до_tts(monkeypatch, tmp_path):
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    scenario = _scenario()
    scenario["language"] = "kk"
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "scenario.json").write_text(
        json.dumps(scenario, ensure_ascii=False), encoding="utf-8"
    )
    # format=split: fullscreen отбивается раньше языковых проверок
    cfg = _cfg("split")
    cfg["language"] = "ru"
    cfg["voice_language"] = "ru"
    cfg["tts"] = {"language_code": "ru"}

    res = pipeline.run_make(
        cfg, wd,
        synth_fn=fs, assemble_fn=fa,
    )

    assert res["ok"] is False and res["stage"] == "language"
    assert calls == []


def test_голос_другого_языка_останавливает_pipeline_до_tts(monkeypatch, tmp_path):
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    scenario = _scenario()
    scenario["language"] = "kk"
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "scenario.json").write_text(
        json.dumps(scenario, ensure_ascii=False), encoding="utf-8"
    )
    # format=split: fullscreen отбивается раньше языковых проверок
    cfg = _cfg("split")
    cfg.update({
        "language": "kk",
        "voice_id": "voice-ru",
        "voice_language": "ru",
        "voices": {"ru": "voice-ru"},
        "tts": {"language_code": "kk"},
    })

    res = pipeline.run_make(
        cfg, wd,
        synth_fn=fs, assemble_fn=fa,
    )

    assert res["ok"] is False and res["stage"] == "language"
    assert calls == []


def test_caption_fixes_применяются_до_сборки(monkeypatch, tmp_path):
    """Новый сборщик карту фиксов не принимает: конвейер сам чинит слова
    выравнивания через apply_caption_fixes и отдаёт уже исправленные."""
    calls = []
    captured = {}
    fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    def fake_master(scenario, config, workdir, voice_id=None, meter=None):
        master = _fake_master_audio(scenario, config, workdir,
                                    voice_id=voice_id, meter=meter)
        words = list(master.words)
        # Whisper услышал бренд как "гайт" — brand_captions знает этот вариант
        words[0] = dict(words[0], text="гайт")
        return SimpleNamespace(
            wav=master.wav,
            block_wavs=master.block_wavs,
            words=tuple(words),
            timed_scenario=master.timed_scenario,
        )

    res = pipeline.run_make(_cfg("split"), wd,
                            avatar_client=avatar, synth_fn=fs, assemble_fn=fa,
                            master_audio_fn=fake_master)

    assert res["ok"] is True
    assert captured["alignment_words"][0]["text"] == "Гайд"
    assert len(captured["alignment_words"]) == 4
    assert captured["edit_plan"]["format_version"] == 1


def test_джамп_каты_выключены_по_умолчанию(monkeypatch, tmp_path):
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)
    cut_calls = []

    def fake_cut(frags, rdir, **kw):
        cut_calls.append(list(frags))
        return frags

    res = pipeline.run_make(_cfg("avatar"), wd, avatar_client=avatar,
                            synth_fn=fs, assemble_fn=fa,
                            jump_cut_fn=fake_cut)

    assert res["ok"] is True
    assert cut_calls == []  # флага нет — стадия не запускалась


def test_precut_план_строится_и_экономит_heygen(monkeypatch, tmp_path):
    """format=avatar без broll_plan: precut_fn покрывает development ->
    HeyGen для него не вызывается, canonical-план сохраняется в edit_plan.json."""
    calls = []
    captured = {}
    fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)
    covered_calls = []

    def fake_precut(scenario, config):
        clip = wd / "lib.mp4"
        clip.write_bytes(b"library")
        return {"segments": [{"role": "development", "insert": True, "offset": 0.0,
                              "clip": "lib.mp4", "path": str(clip),
                              "query": "молол мелко", "duration": 20.0}],
                "est": {"covered_s": 10.0, "total_s": 23.0}, "log": ["ок"]}

    res = pipeline.run_make(_cfg("avatar"), wd,
                            avatar_client=avatar, synth_fn=fs,
                            assemble_fn=fa, precut_fn=fake_precut,
                            covered_block_fn=_fake_covered_block(covered_calls))

    assert res["ok"] is True
    # development не ходил в HeyGen: 3 генерации вместо 4 + 1 дешёвый локальный
    assert len(avatar.calls) == 3
    assert len(covered_calls) == 1 and "voice_1.wav" in covered_calls[0]
    # план дошёл до сборки и сохранён для прозрачности
    assert captured["edit_plan"]["summary"]["covered_block_indexes"] == [1]
    assert (wd / "edit_plan.json").exists()
    assert not (wd / "segment_plan.json").exists()


def test_precut_пустой_план_пайплайн_как_раньше(monkeypatch, tmp_path):
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    def fake_precut(scenario, config):
        return {"segments": [], "est": {"covered_s": 0.0, "total_s": 25.0}, "log": []}

    res = pipeline.run_make(_cfg("avatar"), wd,
                            avatar_client=avatar, synth_fn=fs,
                            assemble_fn=fa, precut_fn=fake_precut)

    assert res["ok"] is True
    assert len(avatar.calls) == 4  # все блоки аватарные


def test_per_phrase_performance_llm_обогащает_canonical_plan(
    monkeypatch, tmp_path
):
    calls = []
    captured = {}
    fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    class Runner:
        prompt = None

        def run(self, prompt):
            self.prompt = prompt
            return json.dumps({
                "phrases": [
                    {
                        "phrase_id": f"phrase-{index:03d}",
                        "expressiveness": "medium",
                        "motion_prompt": (
                            "Looks at the camera and nods gently, calm and clear."
                        ),
                        "rationale": "Matches the approved phrase.",
                    }
                    for index in range(4)
                ]
            })

    runner = Runner()
    cfg = _cfg("split")
    cfg["edit_plan"] = {"performance_llm": {"enabled": True}}

    res = pipeline.run_make(
        cfg, wd,
        avatar_client=avatar, synth_fn=fs, assemble_fn=fa,
        performance_runner=runner,
    )

    assert res["ok"] is True
    assert "Photo Avatar IV" in runner.prompt
    assert all(
        phrase["avatar_performance"]["source"] == "llm"
        for phrase in captured["edit_plan"]["phrases"]
    )


def test_visual_director_llm_обогащает_canonical_plan_до_performance(
    monkeypatch, tmp_path
):
    calls = []
    captured = {}
    fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    class Runner:
        prompt = None

        def run(self, prompt):
            self.prompt = prompt
            return json.dumps({
                "visuals": [{
                    "phrase_ids": ["phrase-002"],
                    "template": "sequence_flow",
                    "variables": {
                        "title": "ПУТЬ К РЕЗУЛЬТАТУ",
                        # "РОВНО" — опора в реальной речи phrase-002 ("стало
                        # ровно"). С master_audio по умолчанию finalize
                        # прогоняет enforce_visual_grounding по-настоящему
                        # (раньше master было None и грайндинг не запускался),
                        # и придуманный пункт без опоры в речи снимался бы.
                        "items": ["БЫЛО", "РОВНО", "СТАЛО"],
                    },
                    "rationale": "Показывает причинную последовательность.",
                }]
            })

    runner = Runner()
    cfg = _cfg("split")
    cfg["edit_plan"] = {
        "visual_director": {
            "llm": {"enabled": True},
        }
    }

    res = pipeline.run_make(
        cfg,
        wd,
        avatar_client=avatar,
        synth_fn=fs,
        assemble_fn=fa,
        visual_runner=runner,
    )

    assert res["ok"] is True
    assert "Visual Director" in runner.prompt
    visual = next(
        window
        for window in captured["edit_plan"]["windows"]
        if (window.get("effect") or {}).get("visual_director")
    )
    assert visual["phrase_ids"] == ["phrase-002"]
    assert visual["effect"]["visual_director"]["source"] == "llm"
    assert visual["effect"]["hyperframes"]["block"] == "sequence_flow"


def test_visual_director_llm_bad_item_не_роняет_pipeline(
    monkeypatch, tmp_path
):
    calls = []
    captured = {}
    fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    class Runner:
        def run(self, _prompt):
            return json.dumps({
                "visuals": [{
                    "phrase_ids": ["unknown-phrase"],
                    "template": "concept_nodes",
                    "variables": {
                        "title": "НЕВЕРНОЕ ОКНО",
                        "items": ["ОДИН", "ДВА"],
                    },
                }]
            })

    cfg = _cfg("split")
    cfg["edit_plan"] = {
        "visual_director": {"llm": {"enabled": True}}
    }

    res = pipeline.run_make(
        cfg,
        wd,
        avatar_client=avatar,
        synth_fn=fs,
        assemble_fn=fa,
        visual_runner=Runner(),
    )

    assert res["ok"] is True
    review = captured["edit_plan"]["visual_director_reviews"][0]
    assert review["source"] == "llm"
    assert len(review["rejected"]) == 1
    assert captured["edit_plan"]["validation"]["all_pass"] is True


def test_precut_не_запускается_для_split(monkeypatch, tmp_path):
    """split: аватар всегда виден в верхней половине — покрытие неприменимо."""
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)
    precut_calls = []

    def fake_precut(scenario, config):
        precut_calls.append(1)
        return {"segments": [], "log": []}

    res = pipeline.run_make(_cfg("split"), wd,
                            avatar_client=avatar, synth_fn=fs,
                            assemble_fn=fa, precut_fn=fake_precut)

    assert res["ok"] is True
    assert precut_calls == []


def test_падение_precut_даёт_stage_plan(monkeypatch, tmp_path):
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    def broken_precut(scenario, config):
        raise RuntimeError("индекс битый")

    res = pipeline.run_make(_cfg("avatar"), wd,
                            avatar_client=avatar, synth_fn=fs,
                            assemble_fn=fa, precut_fn=broken_precut)

    assert res["ok"] is False and res["stage"] == "plan"
    assert "индекс" in res["error"]


class _FakeMeter:
    def __init__(self):
        self.heygen_calls = []
        self.eleven_calls = []
        self.claude_calls = []

    def heygen(self, seconds, *, cached=False, twin=False):
        self.heygen_calls.append((seconds, cached, twin))

    def elevenlabs(self, chars):
        self.eleven_calls.append(chars)

    def claude(self, usd, step="scenario"):
        self.claude_calls.append((round(usd, 2), step))


def test_кэшированный_фрагмент_не_тарифицируется():
    meter = _FakeMeter()
    meter.heygen(12.0, cached=True, twin=False)
    meter.heygen(30.0, cached=False, twin=False)
    billable = [s for s, cached, _ in meter.heygen_calls if not cached]
    assert billable == [30.0]


def test_конвейер_собирает_новым_движком():
    import reels_factory.pipeline as pipeline

    assert pipeline._assemble.__module__ == "reels_factory.hf_render"
    assert pipeline._assemble.__name__ == "assemble_hyperframes"


def test_run_make_принимает_meter():
    import inspect
    from reels_factory.pipeline import run_make
    assert "meter" in inspect.signature(run_make).parameters


def test_master_audio_с_meter_тарифицирует_единственный_запрос(monkeypatch, tmp_path):
    """Предохранитель ветки master_audio снят: с переданным meter сборка не
    падает, а счётчик получает символы единственного ElevenLabs запроса."""
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)
    meter = _FakeMeter()

    def fake_master(scenario, config, workdir, voice_id=None, meter=None):
        if meter is not None:
            meter(sum(len(b["speech"]) for b in scenario["blocks"]))
        master_wav = Path(workdir) / "voice_master.wav"
        master_wav.write_bytes(b"master")
        block_wavs = []
        for index in range(len(scenario["blocks"])):
            wav = Path(workdir) / f"voice_{index}.wav"
            wav.write_bytes(b"slice")
            block_wavs.append(wav)
        timed = json.loads(json.dumps(scenario))
        for index, block in enumerate(timed["blocks"]):
            block["start"] = index * 2.0
            block["end"] = (index + 1) * 2.0
        timed["total"] = 8.0
        return SimpleNamespace(
            wav=master_wav,
            block_wavs=tuple(block_wavs),
            words=tuple(
                {
                    "start": index * 2.0 + 0.2,
                    "end": (index + 1) * 2.0 - 0.2,
                    "text": block["speech"],
                    "block_index": index,
                }
                for index, block in enumerate(timed["blocks"])
            ),
            timed_scenario=timed,
        )

    cfg = _cfg("avatar")
    cfg["master_audio"] = {"enabled": True}
    res = pipeline.run_make(
        cfg, wd, avatar_client=avatar, synth_fn=fs,
        assemble_fn=fa, master_audio_fn=fake_master,
        meter=meter,
    )

    assert res["ok"] is True, res.get("error")
    assert len(meter.eleven_calls) == 1
    assert meter.eleven_calls[0] == sum(len(b["speech"]) for b in _scenario()["blocks"])


def test_compose_сессия_тарифицируется(monkeypatch, tmp_path):
    calls = []
    captured = {}
    fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)
    meter = _FakeMeter()

    result = pipeline.run_make(
        _cfg("avatar"),
        wd,
        avatar_client=avatar,
        synth_fn=fs,
        assemble_fn=fa,
        meter=meter,
    )

    assert result["ok"] is True, result.get("error")
    assert captured.get("agent_runner") is not None
    assert (0.05, "compose") in meter.claude_calls
