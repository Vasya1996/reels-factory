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
        {"role": "hook", "start": 0.0, "end": 3.0, "speech": "кофе кислит"},
        {"role": "development", "start": 3.0, "end": 13.0, "speech": "молол мелко"},
        {"role": "payoff", "start": 13.0, "end": 22.0, "speech": "стало ровно"},
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
                "gates": {"D8_face": "PASS"}}

    def fake_verify(mp4, scenario, **kw):
        calls.append(("verify", str(mp4), kw.get("words")))
        if captured is not None:
            captured["verify_format"] = kw.get("format")
        return {"all_pass": True, "gates": {}}

    monkeypatch.setattr(pipeline, "verify_reel", fake_verify)
    return fake_synth, fake_assemble


def _fake_early_plan(monkeypatch, calls=None, scenes=None):
    """Заглушка раннего плана агента (работа 9).

    После работы 9 аватар заказывается ПОСЛЕ плана агента, поэтому островной
    путь зовёт `hf_render.plan_before_avatar` — то есть настоящую сессию
    `claude -p`. В тестах она подменяется здесь.

    Имя в `pipeline` заранее не известно (в модуле принят стиль
    `from … import assemble_hyperframes as _assemble`), поэтому подменяются оба
    вероятных: `_plan_before_avatar` и `plan_before_avatar`.
    """
    сцены = list(scenes or [])

    def fake_plan(rdir, timed_scenario, **kw):
        if calls is not None:
            calls.append(("plan_before_avatar", Path(rdir),
                          kw.get("agent_spend"), kw.get("config")))
        return {"board": {"scenes": сцены}, "scenes": сцены, "gates": {}}

    for name in ("_plan_before_avatar", "plan_before_avatar"):
        monkeypatch.setattr(pipeline, name, fake_plan, raising=False)
    return fake_plan


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


def test_bot_job_не_запускает_render_пока_master_audio_не_утверждено(
        monkeypatch, tmp_path):
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)
    master_calls = []

    cfg = _cfg("avatar")
    cfg["master_audio"] = {"enabled": True, "review_required": True}
    result = pipeline.run_make(
        cfg,
        wd,
        avatar_client=avatar,
        synth_fn=fs,
        assemble_fn=fa,
        master_audio_fn=lambda *args, **kwargs: master_calls.append(1),
    )

    assert result["ok"] is False
    assert result["stage"] == "voice"
    assert "не утверждено" in result["error"]
    assert master_calls == []
    assert avatar.calls == []
    assert not any(call[0] == "assemble" for call in calls)


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
    _fake_early_plan(monkeypatch)
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
    _fake_early_plan(monkeypatch)
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


def test_на_островах_работа_агента_тоже_уходит_в_счёт(monkeypatch, tmp_path):
    """Аватар-острова меняют только заказ HeyGen: план островов считает наш
    детерминированный код (`build_avatar_render_plan`), а монтаж планирует агент.
    Значит его расход обязан списываться и здесь, ровно как на обычном пути —
    это боевая настройка сервера.

    Кошелёк ролика (`AgentSpend`) заводит конвейер и отдаёт его и раннему плану,
    и сборке: только так расход планировщика попадает в счёт при любом исходе.
    Поэтому фейк сборки кладёт прогон в переданный кошелёк, как это делает
    настоящая `assemble_hyperframes`."""
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    _fake_early_plan(monkeypatch)
    avatar = _FakeAvatar()
    avatar.engine = "avatar_iv"
    прогон = {"model": "claude-sonnet-5", "usage": {"output_tokens": 1000}}
    кошельки = []

    def сборка_с_агентом(rdir, timed_scenario, **kw):
        res = fa(rdir, timed_scenario, **kw)
        spend = kw.get("agent_spend")
        кошельки.append(spend)
        if spend is not None:
            spend.add(прогон, 1.24)
            res["agent_runs"] = spend.runs
            res["agent_cost_usd"] = spend.total_cost_usd
        return res

    def fake_master(scenario, config, workdir, voice_id=None, meter=None):
        master_wav = Path(workdir) / "voice_master.wav"
        master_wav.write_bytes(b"master-islands")
        timed = json.loads(json.dumps(scenario))
        block_wavs, words = [], []
        for index, block in enumerate(timed["blocks"]):
            block["start"], block["end"] = index * 2.0, (index + 1) * 2.0
            wav = Path(workdir) / f"voice_{index}.wav"
            wav.write_bytes(b"legacy-slice")
            block_wavs.append(wav)
            words.append({"start": index * 2.0 + 0.2, "end": (index + 1) * 2.0 - 0.2,
                          "text": block["speech"], "block_index": index})
        timed["total"] = 8.0
        return SimpleNamespace(wav=master_wav, block_wavs=tuple(block_wavs),
                               words=tuple(words), timed_scenario=timed)

    def fake_render(master_wav, plan, client, workdir, cache_dir, *, edit_plan,
                    meter=None):
        clips = []
        for shot in plan["shots"]:
            clip = Path(workdir) / f"{shot['id']}.mp4"
            clip.write_bytes(b"offline-avatar-iv")
            clips.append(clip)
        return SimpleNamespace(clips=tuple(clips), plan=plan,
                               manifest={"shots": [{"status": "ready"}
                                                   for _ in clips]})

    cfg = _cfg("avatar")
    cfg["master_audio"] = {"enabled": True}
    cfg["avatar_islands"] = {"enabled": True}
    meter = _FakeMeter()
    res = pipeline.run_make(
        cfg, _wd_with_scenario(tmp_path), avatar_client=avatar, synth_fn=fs,
        assemble_fn=сборка_с_агентом, master_audio_fn=fake_master,
        avatar_render_fn=fake_render, meter=meter,
    )

    assert res["ok"] is True, res.get("error")
    assert кошельки and кошельки[0] is not None, "сборке не передан кошелёк"
    assert meter.agent_calls == [([прогон], 1.24)]


def test_ранний_план_агента_идёт_до_заказа_аватара(monkeypatch, tmp_path):
    """Работа 9 (E): аватар заказывается ПО плану агента, а не до него.

    Заготовка есть, но не подключена — `hf_render.plan_before_avatar` и
    `avatar_islands.apply_agent_coverage` никто не зовёт, поэтому поле
    `avatarNeeded` сегодня ни на что не влияет и деньги HeyGen тратятся по
    эвристике. Порядок обязателен именно такой: план -> разметка покрытия по
    плану -> план заказа -> заказ. Кошелёк ролика при этом один на ранний план
    и на сборку.
    """
    calls = []
    captured = {}
    fs, fa = _fakes(monkeypatch, tmp_path, calls, captured=captured)
    avatar = _FakeAvatar()
    avatar.engine = "avatar_iv"
    wd = _wd_with_scenario(tmp_path)

    сцены = [{"id": "s-00", "startSec": 0.0, "endSec": 4.0,
              "presenter": "punch", "avatarNeeded": True},
             {"id": "s-01", "startSec": 4.0, "endSec": 8.0,
              "presenter": "none", "avatarNeeded": False}]
    _fake_early_plan(monkeypatch, calls=calls, scenes=сцены)

    def fake_coverage(edit_plan, scenes):
        calls.append(("apply_agent_coverage", scenes, None))
        return dict(json.loads(json.dumps(edit_plan)), coverage_by_agent=True)

    for name in ("apply_agent_coverage", "_apply_agent_coverage"):
        monkeypatch.setattr(pipeline, name, fake_coverage, raising=False)

    заказ = {}

    def fake_avatar_plan(edit_plan, config, *, master_audio_sha256=None):
        calls.append(("avatar_plan", None, None))
        заказ["edit_plan"] = edit_plan
        return {"format_version": 1, "engine_scope": "photo_avatar_iv",
                "shots": [{"id": "shot-000"}], "summary": {"island_count": 1},
                "validation": {"all_pass": True}}

    def fake_render(master_wav, plan, client, workdir, cache_dir, *, edit_plan,
                    meter=None):
        calls.append(("avatar_render", None, None))
        clip = Path(workdir) / "shot-000.mp4"
        clip.write_bytes(b"offline-avatar-iv")
        return SimpleNamespace(clips=(clip,), plan=plan,
                               manifest={"shots": [{"status": "ready"}]})

    def fake_master(scenario, config, workdir, voice_id=None, meter=None):
        master_wav = Path(workdir) / "voice_master.wav"
        master_wav.write_bytes(b"master-islands")
        timed = json.loads(json.dumps(scenario))
        block_wavs, words = [], []
        for index, block in enumerate(timed["blocks"]):
            block["start"], block["end"] = index * 2.0, (index + 1) * 2.0
            wav = Path(workdir) / f"voice_{index}.wav"
            wav.write_bytes(b"legacy-slice")
            block_wavs.append(wav)
            words.append({"start": index * 2.0 + 0.2,
                          "end": (index + 1) * 2.0 - 0.2,
                          "text": block["speech"], "block_index": index})
        timed["total"] = 8.0
        return SimpleNamespace(wav=master_wav, block_wavs=tuple(block_wavs),
                               words=tuple(words), timed_scenario=timed)

    cfg = _cfg("avatar")
    cfg["master_audio"] = {"enabled": True}
    cfg["avatar_islands"] = {"enabled": True}
    res = pipeline.run_make(
        cfg, wd, avatar_client=avatar, synth_fn=fs, assemble_fn=fa,
        master_audio_fn=fake_master, avatar_plan_fn=fake_avatar_plan,
        avatar_render_fn=fake_render,
    )

    assert res["ok"] is True, res.get("error")
    этапы = [call[0] for call in calls]
    for шаг in ("plan_before_avatar", "apply_agent_coverage", "avatar_plan",
                "avatar_render"):
        assert шаг in этапы, f"шага {шаг} в прогоне не было"
    assert (этапы.index("plan_before_avatar")
            < этапы.index("apply_agent_coverage")
            < этапы.index("avatar_plan") < этапы.index("avatar_render"))
    # план агента разложен по той же папке, куда потом идёт сборка
    ранний = next(call for call in calls if call[0] == "plan_before_avatar")
    assert ранний[1] == wd
    # островам достались сцены агента и размеченный по ним план
    покрытие = next(call for call in calls
                    if call[0] == "apply_agent_coverage")
    assert покрытие[1] == сцены
    assert заказ["edit_plan"].get("coverage_by_agent") is True
    # кошелёк один: расход раннего плана и сборки уходит в один счёт
    assert ранний[2] is not None, "раннему плану не передан кошелёк"
    assert captured["agent_spend"] is ранний[2]
    # Настройки клиента доехали до раннего шага: по ним считаются и числа в
    # задании агенту, и гейты плана, и сам заказ у HeyGen (`avatar_islands`).
    # Без этой передачи задание и гейты считали бы по умолчаниям, а счёт
    # пришёл бы по профилю клиента.
    assert ранний[3] is cfg, "раннему плану не переданы настройки клиента"
    assert (ранний[3] or {}).get("avatar_islands") == cfg["avatar_islands"]


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
                        "rationale": "Matches the approved phrase.",
                        "gesture": "nod_gentle",
                        "expressiveness": "medium",
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
        self.agent_calls = []

    def heygen(self, seconds, *, cached=False, twin=False):
        self.heygen_calls.append((seconds, cached, twin))

    def elevenlabs(self, chars):
        self.eleven_calls.append(chars)

    def claude_agent(self, runs, reported_usd=0.0):
        self.agent_calls.append((runs, reported_usd))


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


def test_работа_агента_монтажа_попадает_в_счёт(monkeypatch, tmp_path):
    """Планировщик и судья бироллов — платный шаг наравне с HeyGen: их расход
    копится в кошельке ролика, и он должен уйти в метр, а не потеряться.

    Кошелёк заводит конвейер и передаёт его сборке (`agent_spend`): иначе расход
    раннего плана и упавшей сборки в счёт не попадёт вовсе."""
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    прогон = {"model": "claude-sonnet-5", "usage": {"output_tokens": 1000}}
    кошельки = []

    def сборка_с_агентом(rdir, timed_scenario, **kw):
        res = fa(rdir, timed_scenario, **kw)
        spend = kw.get("agent_spend")
        кошельки.append(spend)
        if spend is not None:
            spend.add(прогон, 1.24)
            res["agent_runs"] = spend.runs
            res["agent_cost_usd"] = spend.total_cost_usd
        return res

    meter = _FakeMeter()
    res = pipeline.run_make(
        _cfg("avatar"), _wd_with_scenario(tmp_path), avatar_client=_FakeAvatar(),
        synth_fn=fs, assemble_fn=сборка_с_агентом, meter=meter,
    )

    assert res["ok"] is True, res.get("error")
    assert кошельки and кошельки[0] is not None, "сборке не передан кошелёк"
    assert meter.agent_calls == [([прогон], 1.24)]


def test_работа_агента_списывается_и_при_падении_сборки(monkeypatch, tmp_path):
    """Дефект 11: `meter.claude_agent` стоял после успешной сборки, поэтому
    упавший прогон не списывал ни планировщика, ни судью бироллов — а деньги за
    них уже потрачены. У бота та же задача решена через try/finally
    (`_charge_claude` в `bot.py`)."""
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    meter = _FakeMeter()
    кошельки = []

    def падающая_сборка(rdir, timed_scenario, **kw):
        кошельки.append(kw.get("agent_spend"))
        if kw.get("agent_spend") is not None:
            kw["agent_spend"].add(
                {"model": "claude-sonnet-5", "usage": {"output_tokens": 1000}},
                0.45)
        raise RuntimeError("рендер упал на середине")

    res = pipeline.run_make(
        _cfg("avatar"), _wd_with_scenario(tmp_path), avatar_client=_FakeAvatar(),
        synth_fn=fs, assemble_fn=падающая_сборка, meter=meter,
    )

    assert кошельки and кошельки[0] is not None, "сборке не передан кошелёк"
    assert res["ok"] is False and res["stage"] == "assemble"
    assert len(meter.agent_calls) == 1, "расход агента при падении не списан"
    прогоны, стоимость = meter.agent_calls[0]
    assert [run["model"] for run in прогоны] == ["claude-sonnet-5"]
    assert стоимость == 0.45


def test_повторный_прогон_не_списывает_работу_агента_дважды(monkeypatch, tmp_path):
    """Сборка возобновляемая: маркеры шагов позволяют запустить `run_make` на
    той же папке ещё раз, и второй прогон агента уже не зовёт. Списываться
    должно только то, что потрачено этим прогоном, — иначе кошелёк ролика,
    заведённый один раз на модуль, вычтет работу первого прогона второй раз."""
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    meter = _FakeMeter()
    wd = _wd_with_scenario(tmp_path)
    # первый прогон платит за план, второй подхватывает готовый и не платит
    по_прогонам = [[({"model": "claude-sonnet-5",
                      "usage": {"output_tokens": 1000}}, 1.0)], []]

    кошельки = []

    def сборка(rdir, timed_scenario, **kw):
        res = fa(rdir, timed_scenario, **kw)
        spend = kw.get("agent_spend")
        кошельки.append(spend)
        if spend is not None:
            for run, cost in по_прогонам.pop(0):
                spend.add(run, cost)
            res["agent_runs"] = spend.runs
            res["agent_cost_usd"] = spend.total_cost_usd
        return res

    for _ in range(2):
        res = pipeline.run_make(
            _cfg("avatar"), wd, avatar_client=_FakeAvatar(),
            synth_fn=fs, assemble_fn=сборка, meter=meter,
        )
        assert res["ok"] is True, res.get("error")

    assert all(кошелёк is not None for кошелёк in кошельки), (
        "сборке не передан кошелёк")
    # кошелёк заводится на каждый прогон заново — иначе второй спишет первый
    assert кошельки[0] is not кошельки[1]
    assert [стоимость for _, стоимость in meter.agent_calls] == [1.0, 0.0]
    assert sum(len(прогоны) for прогоны, _ in meter.agent_calls) == 1


def test_без_монтажа_один_проход_heygen(monkeypatch, tmp_path):
    """montage=False: единая master-дорожка -> один вызов HeyGen, без edit_plan,
    assemble, verify и поблочной озвучки."""
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    wd = _wd_with_scenario(tmp_path)

    master_wav = wd / "voice_master.wav"
    master_wav.write_bytes(b"")

    def fake_master(scenario, config, workdir, *, voice_id=None, meter=None):
        calls.append(("master_audio", voice_id))
        return SimpleNamespace(wav=master_wav)

    cfg = _cfg("avatar")
    cfg["montage"] = False
    cfg["master_audio"] = {"enabled": True}

    res = pipeline.run_make(cfg, wd, avatar_client=avatar,
                            synth_fn=fs, assemble_fn=fa,
                            master_audio_fn=fake_master)

    assert res["ok"] is True and res["qa_pass"] is True and res["montage"] is False
    # ровно один проход HeyGen по единой дорожке
    assert len(avatar.calls) == 1
    assert avatar.calls[0][1] == str(master_wav)
    # монтажный слой не задействован вовсе
    stages = [c[0] for c in calls]
    assert "assemble" not in stages
    assert "verify" not in stages
    assert "synth" not in stages
    assert ("master_audio", "v1") in calls
    assert Path(res["mp4"]).name == "reel.mp4"
    # результат уходит через json.dumps в _cmd_make — он обязан быть
    # сериализуемым (mp4 = str, не Path)
    assert isinstance(res["mp4"], str)
    json.dumps(res)




def test_красный_план_не_едет_в_заказ_а_откатывается_на_эвристику(
        monkeypatch, tmp_path):
    """Ревизия четвёртого круга померила цену этой дыры: после последней
    попытки код заказывал ведущую по плану с красными гейтами, а такой план
    заваливает `build_avatar_render_plan` — то есть сборка падает с уже
    оплаченной озвучкой (95 % расстановок обычной речи).

    Решение заказчика: откатываемся на прежнюю разметку. Клиент получает
    ролик, деньги за озвучку не сгорают, решение агента частично теряется — и
    это видно в гейтах ролика.
    """
    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    avatar = _FakeAvatar()
    avatar.engine = "avatar_iv"
    wd = _wd_with_scenario(tmp_path)

    сцены = [{"id": "s-00", "startSec": 0.0, "endSec": 4.0,
              "presenter": "punch", "avatarNeeded": True},
             {"id": "s-01", "startSec": 4.0, "endSec": 8.0,
              "presenter": "none", "avatarNeeded": False}]

    def fake_plan(rdir, timed_scenario, **kw):
        calls.append(("plan_before_avatar", Path(rdir), None))
        return {"board": {"scenes": сцены}, "scenes": сцены,
                "gates": {"D29_avatar_budget": "FAIL: заказ выше границы"}}

    for name in ("_plan_before_avatar", "plan_before_avatar"):
        monkeypatch.setattr(pipeline, name, fake_plan, raising=False)

    def fake_coverage(edit_plan, scenes):
        calls.append(("apply_agent_coverage", scenes, None))
        return edit_plan

    for name in ("apply_agent_coverage", "_apply_agent_coverage"):
        monkeypatch.setattr(pipeline, name, fake_coverage, raising=False)

    def fake_avatar_plan(edit_plan, config, *, master_audio_sha256=None):
        calls.append(("avatar_plan", None, None))
        return {"format_version": 1, "engine_scope": "photo_avatar_iv",
                "shots": [{"id": "shot-000"}], "summary": {"island_count": 1},
                "validation": {"all_pass": True}}

    def fake_render(master_wav, plan, client, workdir, cache_dir, *, edit_plan,
                    meter=None):
        clip = Path(workdir) / "shot-000.mp4"
        clip.write_bytes(b"offline-avatar-iv")
        return SimpleNamespace(clips=(clip,), plan=plan,
                               manifest={"shots": [{"status": "ready"}]})

    def fake_master(scenario, config, workdir, voice_id=None, meter=None):
        master_wav = Path(workdir) / "voice_master.wav"
        master_wav.write_bytes(b"master-islands")
        timed = json.loads(json.dumps(scenario))
        block_wavs, words = [], []
        for index, block in enumerate(timed["blocks"]):
            block["start"], block["end"] = index * 2.0, (index + 1) * 2.0
            wav = Path(workdir) / f"voice_{index}.wav"
            wav.write_bytes(b"slice")
            block_wavs.append(wav)
            words.append({"start": index * 2.0 + 0.2,
                          "end": (index + 1) * 2.0 - 0.2,
                          "text": block["speech"], "block_index": index})
        timed["total"] = 8.0
        return SimpleNamespace(wav=master_wav, block_wavs=tuple(block_wavs),
                               words=tuple(words), timed_scenario=timed)

    cfg = _cfg("avatar")
    cfg["master_audio"] = {"enabled": True}
    cfg["avatar_islands"] = {"enabled": True}
    res = pipeline.run_make(
        cfg, wd, avatar_client=avatar, synth_fn=fs, assemble_fn=fa,
        master_audio_fn=fake_master, avatar_plan_fn=fake_avatar_plan,
        avatar_render_fn=fake_render,
    )

    assert res["ok"] is True, res.get("error")
    этапы = [call[0] for call in calls]
    assert "apply_agent_coverage" not in этапы, (
        "решение агента применили, хотя его же гейты красные")
    assert "avatar_plan" in этапы, "ролик всё равно должен собраться"
    assert any(str(v).startswith("FAIL")
               for v in (res.get("gates") or {}).values())


# --- продолжение упавшей сборки: за что уже заплачено, то не платится снова ---

RATES_СЧЁТА = {
    "heygen_usd_per_second": 0.05,
    "heygen_twin_usd_per_second": 0.0667,
    "elevenlabs_usd_per_1k_chars": 0.10,
    "chars_per_second": 14.0,
    "claude_flat_usd_per_reel": 0.05,
}


class _ФотоАватарIV:
    """Клиент HeyGen островов: каждый вызов generate — это заказ за деньги."""

    def __init__(self):
        self.avatar_id = "photo-asset"
        self.look_id = None
        self.engine = "avatar_iv"
        self.resolution = "1080p"
        self.motion_prompt = "default"
        self.expressiveness = "low"
        self.calls = []

    def motion_prompt_for(self, role=None):
        return self.motion_prompt

    def generate(self, audio_wav, out_mp4, role=None, motion_prompt=None,
                 expressiveness=None):
        self.calls.append(str(audio_wav))
        out_mp4 = Path(out_mp4)
        out_mp4.write_bytes(b"clip|" + Path(audio_wav).read_bytes())
        return out_mp4


def _нарезка_без_ffmpeg(cmd):
    """Куски мастер-звука детерминированы: от них считается ключ кэша."""
    output = Path(cmd[-1])
    start = cmd[cmd.index("-ss") + 1]
    duration = cmd[cmd.index("-t") + 1]
    output.write_bytes(f"slice:{start}:{duration}".encode())


def _мастер_островов(scenario, config, workdir, voice_id=None, meter=None):
    """Синтез мастер-звука. Настоящий тарифицирует символы ровно так же."""
    if meter is not None:
        meter(sum(len(b["speech"]) for b in scenario["blocks"]))
    master_wav = Path(workdir) / "voice_master.wav"
    master_wav.write_bytes(b"master-islands")
    block_wavs, words = [], []
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
        wav=master_wav, block_wavs=tuple(block_wavs), words=tuple(words),
        timed_scenario=timed,
    )


def _записи_трат(ledger, job_id: str) -> dict:
    """Сколько строк в журнале трат у этой сборки, по подрядчикам."""
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT provider, COUNT(*) AS n FROM spend_log"
            " WHERE job_id = ? GROUP BY provider",
            (job_id,),
        ).fetchall()
    return {row["provider"]: int(row["n"]) for row in rows}


def test_повторный_прогон_не_платит_ни_за_озвучку_ни_за_ведущую(
        monkeypatch, tmp_path):
    """Ключевой тест продолжения упавшей сборки.

    Журнал трат от повторного списания НЕ защищает: `entry_id` содержит
    `run_id`, а он новый на каждый прогон. Защита держится только на двух
    вещах: утверждённая озвучка берётся с диска (`audio.approved.json`), а
    клипы ведущей — из общего кэша по ключу от нарезанного звука, и попадание
    в кэш метр не тарифицирует. Сломайся любая из них — человек оплатит
    второй раз то, что уже готово, и обещание кнопки продолжения станет
    неправдой.
    """
    from reels_factory.avatar_islands import render_avatar_islands
    from reels_factory.billing import JobMeter, LedgerStore
    from reels_factory.hf_render import (
        EARLY_PLAN_STEP, reset_montage_steps, run_step, step_done,
    )
    import reels_factory.render as render_mod

    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    _fake_early_plan(monkeypatch)
    # Длительность клипа меряет ffprobe; на кэш-хите его не зовут вовсе.
    monkeypatch.setattr(render_mod, "media_dur", lambda path: 4.0)

    ledger = LedgerStore(tmp_path / "billing.sqlite3")
    ledger.credit(7, 100_000_000, purchase_id="p1", amount_minor=10_000,
                  currency="usd")

    wd = _wd_with_scenario(tmp_path)
    # Озвучка утверждена человеком до сборки — как в боевом флоу бота.
    (wd / "audio.approved.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        pipeline, "load_approved_master_audio",
        lambda scenario, config, workdir: _мастер_островов(
            scenario, config, workdir),
    )

    def озвучка_запрещена(*a, **kw):
        raise AssertionError("утверждённую озвучку синтезировали заново")

    def острова(master_wav, plan, client, workdir, cache_dir, *, edit_plan,
                meter=None):
        return render_avatar_islands(
            master_wav, plan, client, workdir, cache_dir,
            edit_plan=edit_plan, meter=meter, run_cmd=_нарезка_без_ffmpeg,
        )

    cfg = _cfg("avatar")
    cfg["master_audio"] = {"enabled": True}
    cfg["avatar_islands"] = {"enabled": True}
    клиент = _ФотоАватарIV()

    прогоны, заказы = [], []
    for номер in range(2):
        if номер == 1:
            # Продолжение после провала проверок качества: монтаж пересобирают
            # с нуля, и всё, что помечено монтажными маркерами, снимается.
            # Озвучка и ведущая при этом обязаны остаться оплаченными один раз.
            for шаг in ("prepare", "plan", EARLY_PLAN_STEP, "compose",
                        "gates", "shots", "render", "loudness"):
                run_step(wd, шаг, lambda: None)
            reset_montage_steps(wd)
            assert step_done(wd, EARLY_PLAN_STEP) is True
            assert step_done(wd, "compose") is False
        # run_id у каждого прогона свой — ровно поэтому дубль по entry_id не
        # ловится и вся защита ложится на кэши.
        meter = JobMeter(ledger, chat_id=7, job_id="job-1",
                         rates=RATES_СЧЁТА, markup=1.0)
        res = pipeline.run_make(
            cfg, wd, avatar_client=клиент, synth_fn=fs, assemble_fn=fa,
            master_audio_fn=озвучка_запрещена, avatar_render_fn=острова,
            meter=meter,
        )
        assert res["ok"] is True, res.get("error")
        прогоны.append(_записи_трат(ledger, "job-1"))
        заказы.append(len(клиент.calls))

    assert прогоны[0].get("elevenlabs", 0) == 0, (
        "утверждённая озвучка тарифицирована на сборке")
    assert прогоны[0].get("heygen", 0) > 0, "первый прогон обязан платить"
    assert прогоны[1] == прогоны[0], (
        "второй прогон дописал в журнал трат новые записи")
    assert заказы[1] == заказы[0], "ведущая заказана у HeyGen второй раз"

    # Контроль: тот же стенд без утверждённой озвучки платить обязан — иначе
    # проверка выше держалась бы на том, что тарифицировать тут нечем.
    контроль = tmp_path / "контроль"
    контроль.mkdir()
    свежая = _wd_with_scenario(контроль)
    meter = JobMeter(ledger, chat_id=7, job_id="job-контроль",
                     rates=RATES_СЧЁТА, markup=1.0)
    res = pipeline.run_make(
        cfg, свежая, avatar_client=клиент, synth_fn=fs, assemble_fn=fa,
        master_audio_fn=_мастер_островов, avatar_render_fn=острова,
        meter=meter,
    )
    assert res["ok"] is True, res.get("error")
    assert _записи_трат(ledger, "job-контроль").get("elevenlabs", 0) > 0


def test_быстрый_путь_без_монтажа_не_заказывает_ведущую_второй_раз(
        monkeypatch, tmp_path):
    """Д1. Продолжение ролика «без монтажа» заказывает ведущую заново — и
    человек платит за неё второй раз.

    `_run_plain_avatar` зовёт `avatar_client.generate` и `meter.heygen`
    безусловно: ни маркера шага, ни взгляда на готовый `reel.mp4` там нет.
    Второй прогон на той же папке — это второй заказ HeyGen и вторая запись в
    журнале трат, то есть прямые деньги: минута ведущей стоит около трёх
    долларов. А кнопка продолжения на этом пути показывается, и её текст
    обещает ровно обратное — «платить за них второй раз не придётся».

    Стенд настоящий: два прогона одной папки, живой журнал трат и клиент
    HeyGen, считающий заказы. Утверждённая озвучка лежит на диске, поэтому
    единственное, за что тут можно заплатить дважды, — ведущая.
    """
    from reels_factory.billing import JobMeter, LedgerStore
    import reels_factory.render as render_mod

    calls = []
    fs, fa = _fakes(monkeypatch, tmp_path, calls)
    # Секунды заказа меряет ffprobe; в тесте настоящего mp4 нет.
    monkeypatch.setattr(render_mod, "media_dur", lambda path: 4.0)

    ledger = LedgerStore(tmp_path / "billing.sqlite3")
    ledger.credit(7, 100_000_000, purchase_id="p1", amount_minor=10_000,
                  currency="usd")

    wd = _wd_with_scenario(tmp_path)
    # Озвучка утверждена человеком до сборки — как в боевом флоу бота.
    (wd / "audio.approved.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        pipeline, "load_approved_master_audio",
        lambda scenario, config, workdir: _мастер_островов(
            scenario, config, workdir),
    )

    def озвучка_запрещена(*a, **kw):
        raise AssertionError("утверждённую озвучку синтезировали заново")

    cfg = _cfg("avatar")
    cfg["montage"] = False
    cfg["master_audio"] = {"enabled": True}
    клиент = _ФотоАватарIV()

    прогоны, заказы = [], []
    for _ in range(2):
        # run_id у каждого прогона свой — дубль по entry_id журнал не поймает,
        # защищать деньги обязан сам конвейер.
        meter = JobMeter(ledger, chat_id=7, job_id="job-без-монтажа",
                         rates=RATES_СЧЁТА, markup=1.0)
        res = pipeline.run_make(
            cfg, wd, avatar_client=клиент, synth_fn=fs, assemble_fn=fa,
            master_audio_fn=озвучка_запрещена, meter=meter,
        )
        assert res["ok"] is True, res.get("error")
        assert Path(res["mp4"]).exists(), "прогон не оставил ролик на диске"
        прогоны.append(_записи_трат(ledger, "job-без-монтажа"))
        заказы.append(len(клиент.calls))

    assert заказы[0] == 1, "первый прогон обязан заказать ведущую один раз"
    assert прогоны[0].get("heygen", 0) == 1, "первый прогон обязан платить"
    assert заказы[1] == заказы[0], (
        "ведущая заказана у HeyGen второй раз — готовый клип не переиспользован")
    assert прогоны[1] == прогоны[0], (
        "второй прогон дописал в журнал трат новое списание за ведущую")

    # Контроль: на чистой папке заказ и списание обязаны быть — иначе проверки
    # выше держались бы на том, что тут вообще нечего заказывать.
    контроль = tmp_path / "контроль"
    контроль.mkdir()
    свежая = _wd_with_scenario(контроль)
    (свежая / "audio.approved.json").write_text("{}", encoding="utf-8")
    meter = JobMeter(ledger, chat_id=7, job_id="job-контроль-без-монтажа",
                     rates=RATES_СЧЁТА, markup=1.0)
    res = pipeline.run_make(
        cfg, свежая, avatar_client=клиент, synth_fn=fs, assemble_fn=fa,
        master_audio_fn=озвучка_запрещена, meter=meter,
    )
    assert res["ok"] is True, res.get("error")
    assert len(клиент.calls) == заказы[0] + 1
    assert _записи_трат(ledger, "job-контроль-без-монтажа").get("heygen", 0) == 1


def test_провал_гейтов_готового_файла_доезжает_до_следующего_прогона(
        monkeypatch, tmp_path):
    """Д3. Причина отказа теряется, когда валятся гейты готового файла.

    Общий вердикт складывается в `pipeline.py` из гейтов сборщика и гейтов
    `verify_reel` (D1_duration, D2_resolution, D3_loudness, D5_voice,
    D7_captions). А запись причины делает только сборщик и только по СВОИМ
    гейтам (`hf_render.py:1409`): его гейты зелёные, строка выходит пустой, и
    `save_retry_reason` файл причины удаляет.

    Итог: ролик признан негодным, человек жмёт «Перезапустить сборку», а
    следующий прогон получает то же задание без единого слова о том, чем
    предыдущий не прошёл, — и отдаёт тот же ролик за те же деньги.
    """
    from reels_factory.hf_render import last_retry_reason, save_retry_reason

    calls = []
    _fakes(monkeypatch, tmp_path, calls)
    wd = _wd_with_scenario(tmp_path)
    увиденные_причины = []
    гейты_файла = {"D1_duration": "FAIL: 41 с при потолке 40"}

    def сборка(rdir, timed_scenario, **kw):
        """Хвост настоящего сборщика: свои гейты — и запись причины по ним."""
        rdir = Path(rdir)
        увиденные_причины.append(last_retry_reason(rdir))
        out = Path(kw.get("out_mp4") or (rdir / "reel.mp4"))
        out.write_bytes(b"")
        свои = {"D8_face": "PASS", "D18_change_rate": "PASS"}
        save_retry_reason(rdir, "; ".join(
            f"{имя}: {вердикт}" for имя, вердикт in свои.items()
            if str(вердикт).startswith("FAIL")))
        return {"mp4": str(out), "dur": float(timed_scenario.get("total") or 0.0),
                "timed_scenario": timed_scenario,
                "words_fixed": kw.get("alignment_words") or [], "gates": свои}

    def проверка(mp4, scenario, **kw):
        return {"all_pass": True, "gates": dict(гейты_файла)}

    monkeypatch.setattr(pipeline, "verify_reel", проверка)

    def прогон():
        return pipeline.run_make(
            _cfg("avatar"), wd, avatar_client=_FakeAvatar(),
            covered_block_fn=_fake_covered_block(), assemble_fn=сборка)

    первый = прогон()
    assert первый["ok"] is True and первый["qa_pass"] is False, первый
    assert last_retry_reason(wd), (
        "провал по готовому файлу не оставил на папке ни слова — продолжение "
        "получит то же задание и тот же отказ за деньги человека")
    assert "D1_duration" in last_retry_reason(wd)

    # Продолжение той же сборки: причина обязана доехать до задания.
    второй = прогон()
    assert второй["qa_pass"] is False
    assert увиденные_причины[1] and "D1_duration" in увиденные_причины[1], (
        f"сборщик второго прогона не узнал причину отказа: "
        f"{увиденные_причины[1]!r}")

    # Пройденные проверки запись снимают: иначе причина висела бы на папке
    # вечно и гоняла агента заново на каждом следующем продолжении.
    гейты_файла = {"D1_duration": "PASS"}
    третий = прогон()
    assert третий["qa_pass"] is True
    assert last_retry_reason(wd) is None
