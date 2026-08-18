import copy
import hashlib
import json
import math
import sqlite3
from pathlib import Path

import pytest

from reels_factory.avatar import cached_generate
from reels_factory.avatar_islands import (
    RENDER_MANIFEST_FILENAME,
    RENDER_PLAN_FILENAME,
    apply_agent_coverage,
    build_avatar_render_plan,
    render_avatar_islands,
    validate_avatar_render_plan,
)
from reels_factory.editplan import (
    EDIT_PLAN_COVERAGE,
    EDIT_PLAN_FORMAT_VERSION,
    validate_edit_plan,
)


def _final_edit_plan(duration: int) -> dict:
    step = 2
    ranges = {
        30: [(10, 18)],
        60: [(14, 20), (36, 42)],
        90: [(14, 20), (38, 44), (64, 70)],
    }[duration]
    phrase_texts = [f"Фраза {index + 1} про понятную систему"
                    for index in range(duration // step)]
    text = " ".join(phrase_texts)
    phrases, windows = [], []
    cursor = 0
    for index, phrase_text in enumerate(phrase_texts):
        start = index * step
        end = start + step
        role = (
            "hook" if index == 0
            else "cta" if index == len(phrase_texts) - 1
            else "payoff" if index == len(phrase_texts) - 2
            else "development"
        )
        hidden = any(left <= start and end <= right for left, right in ranges)
        coverage = "hyperframes" if hidden else "avatar"
        prompt = {
            "hook": "Looks at the camera and leans in slightly, confident.",
            "development":
                "Looks at the camera and gestures lightly with one hand.",
            "payoff": "Looks at the camera and nods gently, sincere.",
            "cta":
                "Looks at the camera and makes one inviting open-hand gesture.",
        }[role]
        expressiveness = {
            "hook": "medium",
            "development": "medium",
            "payoff": "low",
            "cta": "medium",
        }[role]
        phrase_id = f"phrase-{index:03d}"
        character_start = cursor
        character_end = cursor + len(phrase_text)
        timing = {"start": float(start), "end": float(end), "duration": step}
        phrases.append({
            "id": phrase_id,
            "index": index,
            "block_id": f"block-{index}",
            "block_index": index,
            "role": role,
            "text": phrase_text,
            "character_start": character_start,
            "character_end": character_end,
            "estimated_timing": copy.deepcopy(timing),
            "final_timing": copy.deepcopy(timing),
            "speech_timing": copy.deepcopy(timing),
            "visual_intent": "Тестовое окно.",
            "coverage": coverage,
            "asset": None,
            "fallback": {"coverage": "avatar", "reason": "test"},
            "decision_reason": "test",
            "window_id": None,
            "avatar_performance": {
                "expressiveness": expressiveness,
                "motion_prompt": prompt,
                "prompt_language": "en",
                "source": "llm",
                "rationale": "test",
                "engine_scope": "photo_avatar_iv",
            },
        })
        cursor = character_end + 1
    groups = []
    for phrase in phrases:
        if groups and groups[-1][0]["coverage"] == phrase["coverage"]:
            groups[-1].append(phrase)
        else:
            groups.append([phrase])
    for index, group in enumerate(groups):
        window_id = f"window-{index:03d}"
        for phrase in group:
            phrase["window_id"] = window_id
        coverage = group[0]["coverage"]
        timing = {
            "start": group[0]["final_timing"]["start"],
            "end": group[-1]["final_timing"]["end"],
            "duration":
                group[-1]["final_timing"]["end"]
                - group[0]["final_timing"]["start"],
        }
        windows.append({
            "id": window_id,
            "index": index,
            "block_id": group[0]["block_id"],
            "block_index": group[0]["block_index"],
            "role": group[0]["role"],
            "phrase_ids": [phrase["id"] for phrase in group],
            "coverage": coverage,
            "visual_intent": "Тестовое окно.",
            "asset": None,
            "safe_to_skip_avatar": False,
            "estimated_timing": copy.deepcopy(timing),
            "final_timing": copy.deepcopy(timing),
            "effect": (
                {"type": "chart_bars"}
                if coverage == "hyperframes" else {"type": "none"}
            ),
        })
    return {
        "format_version": EDIT_PLAN_FORMAT_VERSION,
        "status": "final",
        "script": {
            "language": "ru",
            "text": text,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
        "timeline": {
            "estimated_duration_seconds": duration,
            "final_duration_seconds": duration,
        },
        "constraints": {},
        "blocks": [],
        "phrases": phrases,
        "windows": windows,
        "events": {},
        "revisions": [],
        "log": [],
    }


def _config(**island_overrides) -> dict:
    return {
        "format": "avatar",
        "avatar": {
            "heygen_asset_id": "photo-asset",
            "engine": "avatar_iv",
            "resolution": "1080p",
        },
        "master_audio": {"enabled": True},
        "avatar_islands": {"enabled": True, **island_overrides},
    }


@pytest.mark.parametrize(
    ("duration", "expected_islands", "max_shots"),
    [(30, 2, 5), (60, 3, 10), (90, 4, 15)],
)
def test_adaptive_plan_30_60_90(duration, expected_islands, max_shots):
    edit_plan = _final_edit_plan(duration)
    plan = build_avatar_render_plan(
        edit_plan, _config(), master_audio_sha256="master-sha"
    )

    assert plan["validation"]["all_pass"] is True
    assert len(plan["islands"]) == expected_islands
    assert 1 < len(plan["shots"]) <= max_shots
    assert all(
        shot["visible_timing"]["duration"] <= 18
        for shot in plan["shots"]
    )
    visible_phrase_ids = {
        phrase["id"] for phrase in edit_plan["phrases"]
        if phrase["coverage"] in {"avatar", "mixed"}
    }
    assigned = {
        phrase_id for shot in plan["shots"] for phrase_id in shot["phrase_ids"]
    }
    assert assigned == visible_phrase_ids
    assert plan["summary"]["avatar_requested_seconds"] < duration


def test_performance_intents_preserved_and_low_high_forces_boundary():
    edit_plan = _final_edit_plan(30)
    # Two adjacent visible development phrases now require a material shift.
    edit_plan["phrases"][2]["avatar_performance"].update({
        "expressiveness": "low",
        "motion_prompt": "Looks at the camera and nods gently.",
    })
    edit_plan["phrases"][3]["avatar_performance"].update({
        "expressiveness": "high",
        "motion_prompt": "Looks at the camera and leans in with emphasis.",
    })

    plan = build_avatar_render_plan(edit_plan, _config())
    shot_by_phrase = {
        phrase_id: shot
        for shot in plan["shots"]
        for phrase_id in shot["phrase_ids"]
    }

    assert shot_by_phrase["phrase-002"]["id"] != shot_by_phrase["phrase-003"]["id"]
    intents = [
        intent
        for shot in plan["shots"]
        for intent in shot["phrase_performance_intents"]
    ]
    assert {item["phrase_id"] for item in intents} == {
        phrase["id"] for phrase in edit_plan["phrases"]
        if phrase["coverage"] in {"avatar", "mixed"}
    }


def test_mixed_bubble_window_is_included_in_avatar_iv_islands():
    edit_plan = _final_edit_plan(30)
    bubble_window = next(
        window
        for window in edit_plan["windows"]
        if window["coverage"] == "hyperframes"
    )
    bubble_window_index = edit_plan["windows"].index(bubble_window)
    remainder = copy.deepcopy(bubble_window)
    bubble_window["phrase_ids"] = bubble_window["phrase_ids"][:2]
    remainder["id"] = f"{bubble_window['id']}-remainder"
    remainder["phrase_ids"] = remainder["phrase_ids"][2:]
    split_at = edit_plan["phrases"][6]["final_timing"]["end"]
    for timing_key in ("estimated_timing", "final_timing"):
        bubble_window[timing_key]["end"] = split_at
        bubble_window[timing_key]["duration"] = (
            split_at - bubble_window[timing_key]["start"]
        )
        remainder[timing_key]["start"] = split_at
        remainder[timing_key]["duration"] = (
            remainder[timing_key]["end"] - split_at
        )
    bubble_window["coverage"] = "mixed"
    bubble_window["effect"] = {
        "type": "chart_bars",
        "hyperframes": {"block": "task_list", "variables": {}},
        "bubble": {"shape": "circle", "position": "bottom_left"},
    }
    edit_plan["windows"][bubble_window_index:bubble_window_index + 1] = [
        bubble_window,
        remainder,
    ]
    bubble_phrase_ids = set(bubble_window["phrase_ids"])
    for phrase in edit_plan["phrases"]:
        if phrase["id"] in bubble_phrase_ids:
            phrase["coverage"] = "mixed"
            phrase["window_id"] = bubble_window["id"]
        elif phrase["id"] in remainder["phrase_ids"]:
            phrase["window_id"] = remainder["id"]

    plan = build_avatar_render_plan(edit_plan, _config())
    generated_phrase_ids = {
        phrase_id
        for shot in plan["shots"]
        for phrase_id in shot["phrase_ids"]
    }

    assert bubble_phrase_ids <= generated_phrase_ids
    assert plan["validation"]["all_pass"] is True


def test_avatar_v_is_rejected_before_render_plan():
    config = _config()
    config["avatar"]["heygen_look_id"] = "look-v"
    with pytest.raises(ValueError, match="Photo Avatar IV"):
        build_avatar_render_plan(_final_edit_plan(30), config)


class _FakePhotoAvatarIV:
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

    def generate(
        self,
        audio_wav,
        out_mp4,
        role=None,
        motion_prompt=None,
        expressiveness=None,
    ):
        self.calls.append({
            "audio": str(audio_wav),
            "role": role,
            "motion_prompt": motion_prompt,
            "expressiveness": expressiveness,
        })
        out_mp4 = Path(out_mp4)
        out_mp4.write_bytes(b"clip|" + Path(audio_wav).read_bytes())
        return out_mp4


def test_render_slices_parallel_cache_and_durable_manifest(tmp_path):
    edit_plan = _final_edit_plan(30)
    master = tmp_path / "voice_master.wav"
    master.write_bytes(b"offline-master-audio")
    master_sha = hashlib.sha256(master.read_bytes()).hexdigest()
    plan = build_avatar_render_plan(
        edit_plan, _config(max_parallel=2), master_audio_sha256=master_sha
    )
    client = _FakePhotoAvatarIV()

    def fake_run(cmd):
        output = Path(cmd[-1])
        start = cmd[cmd.index("-ss") + 1]
        duration = cmd[cmd.index("-t") + 1]
        output.write_bytes(f"slice:{start}:{duration}".encode())

    first = render_avatar_islands(
        master,
        plan,
        client,
        tmp_path / "job",
        tmp_path / "cache",
        edit_plan=edit_plan,
        run_cmd=fake_run,
    )
    calls_after_first = len(client.calls)
    second = render_avatar_islands(
        master,
        plan,
        client,
        tmp_path / "job",
        tmp_path / "cache",
        edit_plan=edit_plan,
        run_cmd=fake_run,
    )

    assert len(first.clips) == len(plan["shots"])
    assert second.clips == first.clips
    assert len(client.calls) == calls_after_first
    assert calls_after_first == len(plan["shots"])
    assert (tmp_path / "job" / RENDER_PLAN_FILENAME).exists()
    manifest = json.loads(
        (tmp_path / "job" / RENDER_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert all(item["status"] == "ready" for item in manifest["shots"])
    assert all(item["cache_key"] for item in manifest["shots"])
    assert all(item["clip_sha256"] for item in manifest["shots"])


class _FakeMeter:
    """Колбэк с сигнатурой JobMeter.heygen — модуль про биллинг ничего не
    знает, ему передают именно такой колбэк."""

    def __init__(self):
        self.calls = []

    def __call__(self, seconds, *, cached=False, twin=False):
        self.calls.append((seconds, cached, twin))


def _fake_run_slices(cmd):
    output = Path(cmd[-1])
    start = cmd[cmd.index("-ss") + 1]
    duration = cmd[cmd.index("-t") + 1]
    output.write_bytes(f"slice:{start}:{duration}".encode())


def test_каждый_готовый_шот_тарифицируется_по_факту_файла(tmp_path, monkeypatch):
    """Owner: списываем длительность ВЫДАННОГО клипа, меряя факт mp4, а не
    плановую request_timing. Длина фейкового клипа зависит от содержимого
    audio-среза (текст "slice:start:duration"), которое заведомо не равно
    числовой длительности из плана — это доказывает, что в meter уходит
    длительность фактического файла, а не плановое значение."""
    import reels_factory.render as render_mod
    monkeypatch.setattr(
        render_mod, "media_dur",
        lambda path: float(len(Path(path).read_bytes())),
    )

    edit_plan = _final_edit_plan(30)
    master = tmp_path / "voice_master.wav"
    master.write_bytes(b"offline-master-audio")
    master_sha = hashlib.sha256(master.read_bytes()).hexdigest()
    plan = build_avatar_render_plan(
        edit_plan, _config(), master_audio_sha256=master_sha
    )
    client = _FakePhotoAvatarIV()
    meter = _FakeMeter()

    result = render_avatar_islands(
        master, plan, client, tmp_path / "job", tmp_path / "cache",
        edit_plan=edit_plan, run_cmd=_fake_run_slices, meter=meter,
    )

    assert len(meter.calls) == len(plan["shots"])
    # twin наружу всегда False — Stage 3 запрещает Digital Twin, ставку
    # применять неоткуда.
    assert all(cached is False and twin is False for _, cached, twin in meter.calls)
    expected_total = sum(len(clip.read_bytes()) for clip in result.clips)
    assert sum(seconds for seconds, _, _ in meter.calls) == expected_total
    planned_total = sum(shot["request_timing"]["duration"] for shot in plan["shots"])
    assert sum(seconds for seconds, _, _ in meter.calls) != planned_total


def test_шот_из_кэша_не_тарифицируется(tmp_path, monkeypatch):
    """Owner: попадание в кэш денег не стоит, и хит определяется ДО вызова
    генерации — по существованию cache_dir/{cache_key}.mp4. Второй прогон
    того же плана — все шоты из кэша, HeyGen повторно не вызывается."""
    import reels_factory.render as render_mod
    monkeypatch.setattr(render_mod, "media_dur", lambda path: 5.0)

    edit_plan = _final_edit_plan(30)
    master = tmp_path / "voice_master.wav"
    master.write_bytes(b"offline-master-audio")
    master_sha = hashlib.sha256(master.read_bytes()).hexdigest()
    plan = build_avatar_render_plan(
        edit_plan, _config(), master_audio_sha256=master_sha
    )
    client = _FakePhotoAvatarIV()

    first_meter = _FakeMeter()
    render_avatar_islands(
        master, plan, client, tmp_path / "job", tmp_path / "cache",
        edit_plan=edit_plan, run_cmd=_fake_run_slices, meter=first_meter,
    )
    assert all(cached is False for _, cached, _ in first_meter.calls)
    calls_after_first = len(client.calls)

    second_meter = _FakeMeter()
    render_avatar_islands(
        master, plan, client, tmp_path / "job", tmp_path / "cache",
        edit_plan=edit_plan, run_cmd=_fake_run_slices, meter=second_meter,
    )

    assert len(client.calls) == calls_after_first  # HeyGen не вызван повторно
    assert len(second_meter.calls) == len(plan["shots"])
    assert all(cached is True for _, cached, _ in second_meter.calls)


def test_упавший_шот_не_тарифицируется_успешные_из_прогона_тарифицируются(
    tmp_path, monkeypatch
):
    """Owner: шоты рендерятся параллельно, часть может упасть, а функция всё
    равно проходит по всем и кидает исключение в конце (частичный провал).
    Счётчик должен увидеть успешные шоты именно этого прогона, а не потерять
    их из-за итогового исключения; упавший шот тарифицироваться не должен."""
    import reels_factory.render as render_mod
    monkeypatch.setattr(render_mod, "media_dur", lambda path: 4.0)

    edit_plan = _final_edit_plan(30)
    master = tmp_path / "voice_master.wav"
    master.write_bytes(b"offline-master-audio")
    master_sha = hashlib.sha256(master.read_bytes()).hexdigest()
    plan = build_avatar_render_plan(
        edit_plan, _config(), master_audio_sha256=master_sha
    )
    client = _FakePhotoAvatarIV()
    meter = _FakeMeter()
    failing_shot_id = plan["shots"][2]["id"]

    def flaky_generate(client, audio_wav, cache_dir, motion_prompt=None,
                        expressiveness=None, role=None):
        if failing_shot_id in str(audio_wav):
            raise RuntimeError("HeyGen отказал")
        return cached_generate(
            client, audio_wav, cache_dir, role=role,
            motion_prompt=motion_prompt, expressiveness=expressiveness,
        )

    with pytest.raises(RuntimeError, match="avatar island render failed"):
        render_avatar_islands(
            master, plan, client, tmp_path / "job", tmp_path / "cache",
            edit_plan=edit_plan, run_cmd=_fake_run_slices, meter=meter,
            generate_fn=flaky_generate,
        )

    assert len(meter.calls) == len(plan["shots"]) - 1
    assert sum(seconds for seconds, _, _ in meter.calls) == 4.0 * (len(plan["shots"]) - 1)


def test_упавший_meter_не_роняет_готовый_шот_и_не_роняет_сборку(
    tmp_path, monkeypatch, capsys
):
    """Fix 1: сбой самого метра (contention с ботом за sqlite-ledger,
    запертый/битый файл) не должен превращать уже оплаченный и доставленный
    HeyGen clip в failed shot. Раньше meter() звался ВНУТРИ try/except,
    который классифицирует шот, — его исключение переписывало status на
    failed, шот попадал в failures, и вся сборка падала, хотя рендер уже
    состоялся и был оплачен HeyGen'ом."""
    import reels_factory.render as render_mod
    monkeypatch.setattr(render_mod, "media_dur", lambda path: 5.0)

    edit_plan = _final_edit_plan(30)
    master = tmp_path / "voice_master.wav"
    master.write_bytes(b"offline-master-audio")
    master_sha = hashlib.sha256(master.read_bytes()).hexdigest()
    plan = build_avatar_render_plan(
        edit_plan, _config(), master_audio_sha256=master_sha
    )
    client = _FakePhotoAvatarIV()

    def broken_meter(seconds, *, cached=False, twin=False):
        raise sqlite3.OperationalError("database is locked")

    result = render_avatar_islands(
        master, plan, client, tmp_path / "job", tmp_path / "cache",
        edit_plan=edit_plan, run_cmd=_fake_run_slices, meter=broken_meter,
    )

    assert len(result.clips) == len(plan["shots"])
    manifest = json.loads(
        (tmp_path / "job" / RENDER_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert all(item["status"] == "ready" for item in manifest["shots"])
    assert all(item["error"] is None for item in manifest["shots"])
    err = capsys.readouterr().err
    assert "database is locked" in err
    assert "не тарифицирован" in err


def test_кэш_хит_не_вызывает_ffprobe(tmp_path, monkeypatch, capsys):
    """Fix 2: попадание в кэш денег не стоит (JobMeter.heygen игнорирует
    duration при cached=True), значит мерить длительность клипа на кэш-хите
    незачем — это лишний ffprobe subprocess на каждый закэшированный шот, а
    при сбое пробы вводит оператора в заблуждение, будто деньги ушли в
    никуда, хотя списания вообще не было. media_dur не должен звонить на
    кэш-хите вовсе — даже если он бы упал, тарификация должна тихо пройти с
    cached=True/seconds=0.0."""
    import reels_factory.render as render_mod
    monkeypatch.setattr(render_mod, "media_dur", lambda path: 5.0)

    edit_plan = _final_edit_plan(30)
    master = tmp_path / "voice_master.wav"
    master.write_bytes(b"offline-master-audio")
    master_sha = hashlib.sha256(master.read_bytes()).hexdigest()
    plan = build_avatar_render_plan(
        edit_plan, _config(), master_audio_sha256=master_sha
    )
    client = _FakePhotoAvatarIV()

    # Прогрев кэша — первый прогон реально рендерит и мерит каждый шот.
    render_avatar_islands(
        master, plan, client, tmp_path / "job", tmp_path / "cache",
        edit_plan=edit_plan, run_cmd=_fake_run_slices, meter=_FakeMeter(),
    )

    def exploding_media_dur(path):
        raise RuntimeError("ffprobe не должен звонить на кэш-хите")

    monkeypatch.setattr(render_mod, "media_dur", exploding_media_dur)
    meter = _FakeMeter()
    render_avatar_islands(
        master, plan, client, tmp_path / "job", tmp_path / "cache",
        edit_plan=edit_plan, run_cmd=_fake_run_slices, meter=meter,
    )

    assert len(meter.calls) == len(plan["shots"])
    assert all(
        cached is True and seconds == 0.0 for seconds, cached, _ in meter.calls
    )
    assert "ffprobe" not in capsys.readouterr().err


def test_validator_detects_duplicate_visible_phrase():
    edit_plan = _final_edit_plan(30)
    plan = build_avatar_render_plan(edit_plan, _config())
    plan["shots"][1]["phrase_ids"].append(plan["shots"][0]["phrase_ids"][0])
    report = validate_avatar_render_plan(plan, edit_plan)
    assert report["all_pass"] is False
    assert any("ровно один раз" in error for error in report["errors"])


def test_решение_агента_перекрывает_эвристику_покрытия():
    """Работа 9: вход островов — avatarNeeded из плана агента; нарезка
    прежним кодом.

    Дефект 1: отказ агента писался значением "broll", которого нет в
    `EDIT_PLAN_COVERAGE` (editplan.py:222) — на таком плане валидация падает и
    заказ не состоится. Единственное валидное имя полнокадровой вставки —
    "full_broll", и здесь же проверяется, что ни одна фраза не выходит за
    закрытый список значений.
    """
    from reels_factory.avatar_islands import apply_agent_coverage

    plan = {"phrases": [
        {"id": "p0", "coverage": "full_broll",
         "final_timing": {"start": 0.0, "end": 2.0}},
        {"id": "p1", "coverage": "avatar",
         "final_timing": {"start": 2.0, "end": 4.0}},
        {"id": "p2", "coverage": "avatar",
         "final_timing": {"start": 4.0, "end": 6.0}},
    ]}
    scenes = [
        {"id": "s-01", "startSec": 0.0, "endSec": 2.0, "avatarNeeded": True},
        {"id": "s-02", "startSec": 2.0, "endSec": 4.0, "avatarNeeded": False},
        {"id": "s-03", "startSec": 4.0, "endSec": 6.0},
    ]
    out = apply_agent_coverage(plan, scenes)
    got = {p["id"]: p["coverage"] for p in out["phrases"]}
    assert got["p0"] == "avatar"      # агент попросил ведущую
    assert got["p1"] == "full_broll"  # агент отказался — экономия HeyGen
    assert got["p2"] == "avatar"      # решения нет — эвристика не тронута
    assert set(got.values()) <= EDIT_PLAN_COVERAGE
    # исходный план не изменён
    assert plan["phrases"][0]["coverage"] == "full_broll"


# Сцены агента для 30-секундного ролика фикстуры: они выстилают ролик целиком
# и режутся по фразам, но НЕ по окнам edit plan — так их и кладёт
# `hf_phrases.lay_out_scenes` (сцена не длиннее MAX_STATIC_SPAN, границы берутся
# у фраз). Именно поэтому решение агента приходится переносить на окно, а не
# только на фразу.
def _agent_scenes() -> list[dict]:
    return [
        {"id": "s-01", "startSec": 0.0, "endSec": 4.0,
         "presenter": "full", "avatarNeeded": True},
        {"id": "s-02", "startSec": 4.0, "endSec": 8.0,
         "presenter": "none", "avatarNeeded": False},
        {"id": "s-03", "startSec": 8.0, "endSec": 10.0,
         "presenter": "full", "avatarNeeded": True},
        {"id": "s-04", "startSec": 10.0, "endSec": 14.0,
         "presenter": "pip-br", "avatarNeeded": True},
        {"id": "s-05", "startSec": 14.0, "endSec": 18.0,
         "presenter": "none", "avatarNeeded": False},
        {"id": "s-06", "startSec": 18.0, "endSec": 22.0,
         "presenter": "full", "avatarNeeded": True},
        # Решения нет вовсе — эвристика edit plan остаётся за старшего.
        {"id": "s-07", "startSec": 22.0, "endSec": 26.0,
         "presenter": "full"},
        {"id": "s-08", "startSec": 26.0, "endSec": 30.0,
         "presenter": "full", "avatarNeeded": True},
    ]


def _thrifty_scenes() -> list[dict]:
    """Тот же ролик, но ведущая заказана только на трёх кусках по 4 с.

    Лицо не пропадает дольше `MAX_FACE_ABSENCE_S` (editplan.py:229): дыры
    4–14 с и 18–26 с укладываются в лимит, поэтому такой план валиден и
    доходит до заказа — на нём и проверяется, что бюджет НЕ превышен.
    """
    return [
        {"id": "s-01", "startSec": 0.0, "endSec": 4.0,
         "presenter": "full", "avatarNeeded": True},
        {"id": "s-02", "startSec": 4.0, "endSec": 8.0,
         "presenter": "none", "avatarNeeded": False},
        {"id": "s-03", "startSec": 8.0, "endSec": 12.0,
         "presenter": "none", "avatarNeeded": False},
        {"id": "s-04", "startSec": 12.0, "endSec": 14.0,
         "presenter": "none", "avatarNeeded": False},
        {"id": "s-05", "startSec": 14.0, "endSec": 18.0,
         "presenter": "full", "avatarNeeded": True},
        {"id": "s-06", "startSec": 18.0, "endSec": 22.0,
         "presenter": "none", "avatarNeeded": False},
        {"id": "s-07", "startSec": 22.0, "endSec": 26.0,
         "presenter": "none", "avatarNeeded": False},
        {"id": "s-08", "startSec": 26.0, "endSec": 30.0,
         "presenter": "full", "avatarNeeded": True},
    ]


def _window_of(plan: dict, phrase_id: str) -> dict:
    phrase = next(item for item in plan["phrases"] if item["id"] == phrase_id)
    return next(
        window for window in plan["windows"]
        if phrase["window_id"] == window["id"]
    )


def test_план_после_решения_агента_проходит_валидацию_edit_plan():
    """Дефекты 1 и 2 вместе: план после агента должен пройти тот же
    `validate_edit_plan(require_final=True)`, которым его судит
    `build_avatar_render_plan` (avatar_islands.py:323).

    Сейчас падает дважды: значение "broll" не входит в `EDIT_PLAN_COVERAGE`
    (editplan.py:222), а окна остаются со старым coverage — валидатор требует
    совпадения фразы и окна (editplan.py:2525). Пока это не починено, заказ
    аватара по плану агента вообще не состоится.
    """
    edit_plan = _final_edit_plan(30)
    out = apply_agent_coverage(edit_plan, _agent_scenes())

    coverages = {phrase["coverage"] for phrase in out["phrases"]}
    assert coverages <= EDIT_PLAN_COVERAGE
    assert "full_broll" in coverages
    report = validate_edit_plan(
        out, require_final=True, require_asset_files=False
    )
    assert report["all_pass"] is True, report["errors"]

    # И такой план доезжает до заказа: аватар заказывается ровно там, где
    # агент его попросил, и не заказывается там, где отказался.
    plan = build_avatar_render_plan(
        out, _config(), master_audio_sha256="master-sha"
    )
    ordered = {
        phrase_id for shot in plan["shots"] for phrase_id in shot["phrase_ids"]
    }
    assert ordered == {
        phrase["id"] for phrase in out["phrases"]
        if phrase["coverage"] in {"avatar", "mixed"}
    }
    assert {"phrase-002", "phrase-003"}.isdisjoint(ordered)
    assert {"phrase-005", "phrase-006"} <= ordered


def test_решение_агента_переносится_на_окно_вместе_с_фразой():
    """Дефект 2: `apply_agent_coverage` правит только фразу, а окно остаётся
    прежним — валидатор требует, чтобы coverage фразы и её окна совпадали
    (editplan.py:2525-2526).

    Канон правки окна — `editplan._downgrade_window` (editplan.py:2179): вместе
    с coverage меняются `zone` (editplan._zone_for, editplan.py:1290), `asset`,
    `effect` и `safe_to_skip_avatar`, иначе в окне остаётся материал от снятого
    решения. Сцены агента режут окна посередине, поэтому окно приходится
    делить: границы решения — границы сцен, а не старой раскадровки.
    """
    edit_plan = _final_edit_plan(30)
    out = apply_agent_coverage(edit_plan, _agent_scenes())
    by_id = {phrase["id"]: phrase for phrase in out["phrases"]}

    # Инвариант, который проверяет validate_edit_plan.
    ids = [window["id"] for window in out["windows"]]
    assert len(ids) == len(set(ids))
    for window in out["windows"]:
        assert window["phrase_ids"]
        assert {by_id[item]["coverage"] for item in window["phrase_ids"]} == {
            window["coverage"]
        }
        assert all(
            by_id[item]["window_id"] == window["id"]
            for item in window["phrase_ids"]
        )

    # Окна выстилают ролик без дыр: дыра — это кусок, за который никто не
    # отвечает.
    bounds = [
        (window["final_timing"]["start"], window["final_timing"]["end"])
        for window in out["windows"]
    ]
    assert bounds[0][0] == 0.0 and bounds[-1][1] == 30.0
    assert all(
        left[1] == right[0] for left, right in zip(bounds, bounds[1:])
    )

    # Сколько окон получилось при дележе — дело кода; проверяется то, что
    # видит зритель: где по времени лежит ведущая, а где вставка. Соседние
    # окна одного покрытия склеиваем здесь сами.
    runs: list[list] = []
    for window in out["windows"]:
        timing = window["final_timing"]
        if runs and runs[-1][0] == window["coverage"]:
            runs[-1][2] = timing["end"]
        else:
            runs.append([window["coverage"], timing["start"], timing["end"]])
    spans = [(item[1], item[2]) for item in runs]
    coverage = [item[0] for item in runs]
    assert spans == [(0.0, 4.0), (4.0, 8.0), (8.0, 14.0),
                     (14.0, 18.0), (18.0, 30.0)]
    assert coverage[0] == "avatar"       # хук ведущей агент оставил себе
    assert coverage[1] == "full_broll"   # отказ агента внутри окна-хука
    assert coverage[2] == "avatar"
    # Уже безлицевое окно решение «ведущей тут нет» не переписывает: графика
    # этого окна и так закрывает кадр без аватара.
    assert coverage[3] in {"full_broll", "hyperframes"}
    assert coverage[4] == "avatar"       # призыв остался с ведущей

    hidden = _window_of(out, "phrase-002")
    assert hidden["coverage"] == "full_broll"
    assert hidden["zone"] == "fullscreen"
    assert hidden["asset"] is None
    assert (hidden["effect"] or {}).get("type") == "none"
    assert hidden["safe_to_skip_avatar"] is False

    # Обратное направление — ровно то, что делает _downgrade_window.
    returned = _window_of(out, "phrase-005")
    assert returned["coverage"] == "avatar"
    assert returned["zone"] == "video-overlay"
    assert returned["asset"] is None
    assert returned.get("material") is None
    assert (returned["effect"] or {}).get("type") == "none"
    assert returned["safe_to_skip_avatar"] is False


def test_превышение_бюджета_заказа_попадает_в_отчёт_плана():
    """Пункт D: превышение бюджета заказа ведущей сейчас только печатается в
    stderr (avatar_islands.py:511-518) — до отчёта по сборке оно не доходит,
    а `pipeline.py:486` отдаёт наружу именно `plan["summary"]`.

    Числа должны лежать в отчёте плана: сколько секунд разрешено (ориентир
    `AVATAR_ON_SCREEN_MAX` и граница `AVATAR_ON_SCREEN_HARD_MAX` от
    хронометража), сколько заказано и на сколько промахнулись. Превышение
    сборку не отклоняет — валидация остаётся зелёной.
    """
    from reels_factory.hf_montage import (AVATAR_ON_SCREEN_HARD_MAX,
                                          AVATAR_ON_SCREEN_MAX)

    edit_plan = _final_edit_plan(30)
    plan = build_avatar_render_plan(
        edit_plan, _config(), master_audio_sha256="master-sha"
    )
    budget = plan["summary"]["avatar_budget"]

    assert budget["max_ratio"] == AVATAR_ON_SCREEN_MAX
    assert budget["budget_seconds"] == pytest.approx(
        30 * AVATAR_ON_SCREEN_MAX, abs=0.01
    )
    requested = plan["summary"]["avatar_requested_seconds"]
    assert budget["requested_seconds"] == pytest.approx(requested, abs=0.01)
    assert budget["over_target"] is True
    assert budget["over_budget"] is True
    assert budget["over_seconds"] == pytest.approx(
        requested - 30 * AVATAR_ON_SCREEN_HARD_MAX, abs=0.01
    )
    # Промах по деньгам не отклоняет сборку — он повод для пересдачи и строчки
    # в отчёте, а не для отказа.
    assert plan["validation"]["all_pass"] is True

    # Экономный план агента: тот же ролик, ведущая на трёх кусках — превышения
    # нет, и это должно быть видно теми же полями.
    thrifty = build_avatar_render_plan(
        apply_agent_coverage(_final_edit_plan(30), _thrifty_scenes()),
        _config(),
        master_audio_sha256="master-sha",
    )
    thrifty_budget = thrifty["summary"]["avatar_budget"]
    assert thrifty_budget["over_budget"] is False
    assert thrifty_budget["over_target"] is False
    assert thrifty_budget["over_seconds"] == 0.0
    assert (
        thrifty_budget["requested_seconds"]
        <= thrifty_budget["budget_seconds"] + 0.16
    )


def test_план_между_ориентиром_и_границей_не_числится_перерасходом():
    """Решение заказчика: ориентир доли ведущей 60 % хронометража, а
    заворачивает план только 70 %. Отчёт плана обязан различать эти два числа:
    `over_target` — перешёл ориентир, `over_budget` — перешёл границу, по
    которой судит гейт до заказа (`D29_avatar_budget`, hf_render.py). Иначе
    план, который гейт принял, приезжает в отчёт сборки перерасходом.
    """
    from reels_factory.hf_montage import (AVATAR_ON_SCREEN_HARD_MAX,
                                          AVATAR_ON_SCREEN_MAX)

    # Ведущая на трёх островах: доля заказа садится в полосу между ориентиром
    # и границей. Границы сцен идут по границам готовых окон плана, чтобы
    # короткий кусок не пришлось возвращать ведущей
    # (`_restore_short_faceless`) — тогда доля уехала бы выше полосы.
    scenes = [
        {"id": "s-01", "startSec": 0.0, "endSec": 4.0, "avatarNeeded": True},
        {"id": "s-02", "startSec": 4.0, "endSec": 8.0, "avatarNeeded": False},
        {"id": "s-03", "startSec": 8.0, "endSec": 10.0, "avatarNeeded": True},
        {"id": "s-04", "startSec": 10.0, "endSec": 18.0, "avatarNeeded": False},
        {"id": "s-05", "startSec": 18.0, "endSec": 30.0, "avatarNeeded": True},
    ]
    plan = build_avatar_render_plan(
        apply_agent_coverage(_final_edit_plan(30), scenes),
        _config(),
        master_audio_sha256="master-sha",
    )
    budget = plan["summary"]["avatar_budget"]
    assert budget["max_ratio"] == AVATAR_ON_SCREEN_MAX
    assert budget["hard_max_ratio"] == AVATAR_ON_SCREEN_HARD_MAX
    assert budget["hard_budget_seconds"] == pytest.approx(
        30 * AVATAR_ON_SCREEN_HARD_MAX, abs=0.01)
    assert (AVATAR_ON_SCREEN_MAX < budget["requested_ratio"]
            <= AVATAR_ON_SCREEN_HARD_MAX), (
        "план не попал в полосу — тест проверяет не тот случай")
    assert budget["over_target"] is True
    assert budget["over_budget"] is False
    assert budget["over_seconds"] == 0.0


def test_сцены_без_avatarNeeded_не_трогают_покрытие_но_видны_в_отчёте():
    """Пункт D: сцена без `avatarNeeded` — это не отказ, а молчание агента:
    покрытие такой сцены остаётся эвристическим, и заказ по ней идёт как
    раньше. Но молчание должно быть посчитано: по нему решают, была ли
    пересдача осмысленной, и оно попадает в отчёт по сборке.
    """
    edit_plan = _final_edit_plan(30)
    before = {
        phrase["id"]: phrase["coverage"] for phrase in edit_plan["phrases"]
    }
    out = apply_agent_coverage(edit_plan, _agent_scenes())
    after = {phrase["id"]: phrase["coverage"] for phrase in out["phrases"]}

    # s-07 (22–26 с) решения не назвала — фразы 011 и 012 не тронуты.
    assert after["phrase-011"] == before["phrase-011"] == "avatar"
    assert after["phrase-012"] == before["phrase-012"] == "avatar"

    report = out["agent_coverage"]
    assert report["scenes"] == 8
    assert report["avatar_scenes"] == 5
    assert report["faceless_scenes"] == 2
    assert report["undecided_scenes"] == 1

    # Исходный план агент не переписывает — его перечитывают с диска.
    assert edit_plan["phrases"][2]["coverage"] == "avatar"
    assert "agent_coverage" not in edit_plan


# --- быстрая речь: фраза 2,4 с, окна пофразно ----------------------------


def _fast_edit_plan(count: int = 16, step: float = 2.4,
                    hidden: set[int] | None = None,
                    durations: list[float] | None = None) -> dict:
    """Финальный план монтажа быстрой речи: окно на каждую фразу.

    Так их и заводит `editplan` (`_assign_window`): окно на фразу, и соседние
    не склеиваются никогда. На фразе 2,4 с любая сцена без ведущей разваливалась
    на окна короче `MIN_FULLSCREEN_S`, и `validate_edit_plan` заворачивал план
    уже в `build_avatar_render_plan` — после оплаченной озвучки.

    `hidden` — номера фраз, которым эвристика уже отдала кадр схеме
    (`hyperframes`): решение агента такие фразы не трогает, и на них
    проверяется возврат слишком короткого куска ведущей.
    """
    hidden = hidden or set()
    durations = list(durations or [step] * count)
    count = len(durations)
    edges = [round(sum(durations[:index]), 6) for index in range(count + 1)]
    texts = [f"Фраза {index + 1} быстрой речи" for index in range(count)]
    text = " ".join(texts)
    phrases, windows = [], []
    cursor = 0
    for index, phrase_text in enumerate(texts):
        start, end = edges[index], edges[index + 1]
        step = round(end - start, 6)
        role = ("hook" if index == 0
                else "cta" if index == count - 1
                else "payoff" if index == count - 2
                else "development")
        timing = {"start": start, "end": end, "duration": step}
        phrase_id = f"phrase-{index:03d}"
        window_id = f"window-{index:03d}"
        coverage = "hyperframes" if index in hidden else "avatar"
        phrases.append({
            "id": phrase_id, "index": index, "block_id": f"block-{index}",
            "block_index": index, "role": role, "text": phrase_text,
            "character_start": cursor, "character_end": cursor + len(phrase_text),
            "estimated_timing": copy.deepcopy(timing),
            "final_timing": copy.deepcopy(timing),
            "speech_timing": copy.deepcopy(timing),
            "visual_intent": "Тестовое окно.", "coverage": coverage,
            "asset": None, "fallback": {"coverage": "avatar", "reason": "test"},
            "decision_reason": "test", "window_id": window_id,
            "avatar_performance": {
                "expressiveness": "medium",
                "motion_prompt": "Looks at the camera and nods gently.",
                "prompt_language": "en", "source": "llm", "rationale": "test",
                "engine_scope": "photo_avatar_iv",
            },
        })
        cursor += len(phrase_text) + 1
        windows.append({
            "id": window_id, "index": index, "block_id": f"block-{index}",
            "block_index": index, "role": role, "phrase_ids": [phrase_id],
            "coverage": coverage, "visual_intent": "Тестовое окно.",
            "asset": None, "safe_to_skip_avatar": False,
            "estimated_timing": copy.deepcopy(timing),
            "final_timing": copy.deepcopy(timing),
            "effect": ({"type": "chart_bars"} if index in hidden
                       else {"type": "none"}),
        })
    return {
        "format_version": EDIT_PLAN_FORMAT_VERSION, "status": "final",
        "script": {"language": "ru", "text": text,
                   "text_sha256": hashlib.sha256(
                       text.encode("utf-8")).hexdigest()},
        "timeline": {"estimated_duration_seconds": edges[-1],
                     "final_duration_seconds": edges[-1]},
        "constraints": {}, "blocks": [], "phrases": phrases,
        "windows": windows, "events": {}, "revisions": [], "log": [],
    }


def _fast_scenes(pairs: list[tuple[float, float, bool]]) -> list[dict]:
    return [{"id": f"s-{index:02d}", "startSec": start, "endSec": end,
             "presenter": "full" if needed else "none",
             "avatarNeeded": needed}
            for index, (start, end, needed) in enumerate(pairs)]


def test_соседние_окна_одного_решения_агента_склеиваются_в_одно():
    """Дефект 1: решение агента переносилось на каждое окно порознь, а порог
    `MIN_FULLSCREEN_S` валидатор меряет на окне (editplan.py:2544).

    На быстрой речи (фраза 2,4 с) сцена без ведущей разваливалась на окна по
    2,4 с, и ни один план не проходил `validate_edit_plan`: сплошной перебор
    находил единственный принимаемый план — ведущая весь ролик, самый дорогой
    из всех.
    """
    edit_plan = _fast_edit_plan(8)
    scenes = _fast_scenes([(0.0, 4.8, True), (4.8, 9.6, False),
                           (9.6, 14.4, True), (14.4, 19.2, True)])
    out = apply_agent_coverage(edit_plan, scenes)

    faceless = [window for window in out["windows"]
                if window["coverage"] == "full_broll"]
    assert len(faceless) == 1, "соседние окна одного решения не склеились"
    window = faceless[0]
    assert window["phrase_ids"] == ["phrase-002", "phrase-003"]
    assert window["final_timing"]["start"] == 4.8
    assert window["final_timing"]["end"] == 9.6
    # Фразы знают своё новое окно — этого требует валидатор (editplan.py:2523).
    by_id = {phrase["id"]: phrase for phrase in out["phrases"]}
    assert {by_id[item]["window_id"] for item in window["phrase_ids"]} == {
        window["id"]}

    report = validate_edit_plan(out, require_final=True,
                                require_asset_files=False)
    assert report["all_pass"] is True, report["errors"]
    # И такой план доезжает до заказа: ведущей нет ровно там, где отказался агент.
    plan = build_avatar_render_plan(out, _config(), master_audio_sha256="sha")
    ordered = {item for shot in plan["shots"] for item in shot["phrase_ids"]}
    assert {"phrase-002", "phrase-003"}.isdisjoint(ordered)
    assert len(ordered) == 6


def test_склейка_не_переходит_границу_решения_агента():
    """Склеиваем внутри одной сцены, а не по всему ролику: сцена — единица
    решения агента, и ровно её меряет гейт `D31_faceless_scenes` (hf_render).
    Окно длиннее судимого куска означало бы, что правило говорит одно, а
    валидатор проверяет другое."""
    edit_plan = _fast_edit_plan(8)
    scenes = _fast_scenes([(0.0, 4.8, True), (4.8, 9.6, False),
                           (9.6, 14.4, False), (14.4, 19.2, True)])
    out = apply_agent_coverage(edit_plan, scenes)

    faceless = [window for window in out["windows"]
                if window["coverage"] == "full_broll"]
    assert [window["phrase_ids"] for window in faceless] == [
        ["phrase-002", "phrase-003"], ["phrase-004", "phrase-005"]]
    report = validate_edit_plan(out, require_final=True,
                                require_asset_files=False)
    assert report["all_pass"] is True, report["errors"]


def test_план_без_отказов_агента_окна_не_склеивает():
    """Склейка живёт только на пути работы 9 и только там, где ведущей лишил
    сам агент. План, где отказов нет, обязан остаться с прежними окнами: общий
    путь `editplan` (сегодняшний прод) этих чисел не меняет."""
    edit_plan = _fast_edit_plan(8)
    scenes = _fast_scenes([(0.0, 9.6, True), (9.6, 19.2, True)])
    out = apply_agent_coverage(edit_plan, scenes)

    assert [window["phrase_ids"] for window in out["windows"]] == [
        window["phrase_ids"] for window in edit_plan["windows"]]
    assert out["agent_coverage"]["changed_phrases"] == 0
    assert out["agent_coverage"]["restored_windows"] == []


def test_короткий_кусок_вставки_возвращается_ведущей_а_не_роняет_заказ():
    """Внутри сцены агента фразы приходят с разным покрытием: ту, где ведущей и
    так нет (`hyperframes`), отказ не трогает. Тогда сцена делится на кусок
    схемы и кусок вставки, и второй бывает короче `MIN_FULLSCREEN_S` — а такой
    план валидатор заворачивает уже в `build_avatar_render_plan`, то есть с
    оплаченной озвучкой. Спрашивать агента там некого, поэтому короткий кусок
    возвращается ведущей."""
    # Сцена 4,8–12,0 с: кадр первой её фразы держит схема (4,8 с), второй
    # остаётся 2,4 с — короче порога.
    edit_plan = _fast_edit_plan(
        hidden={2}, durations=[2.4, 2.4, 4.8, 2.4, 2.4, 2.4, 2.4, 2.4])
    scenes = _fast_scenes([(0.0, 4.8, True), (4.8, 12.0, False),
                           (12.0, 21.6, True)])

    out = apply_agent_coverage(edit_plan, scenes)

    by_id = {phrase["id"]: phrase for phrase in out["phrases"]}
    assert by_id["phrase-002"]["coverage"] == "hyperframes"  # схему не трогаем
    assert by_id["phrase-003"]["coverage"] == "avatar"       # вернули ведущей
    assert out["agent_coverage"]["restored_windows"], (
        "возврат короткого куска не попал в отчёт")
    report = validate_edit_plan(out, require_final=True,
                                require_asset_files=False)
    assert report["all_pass"] is True, report["errors"]


def test_схема_в_сцене_с_ведущей_не_считается_пропажей_лица():
    """Хвост между гейтом D32 и валидатором: гейт считает пропажу лица по
    сценам, а `validate_edit_plan` ведёт отсчёт и по окнам `hyperframes`
    (editplan.py:2548-2556). Если бы схема внутри сцены с `avatarNeeded: true`
    оставалась без ведущей, гейт насчитал бы меньше валидатора — и сборка
    падала бы уже с оплаченной озвучкой, а гейт этого плана не заворачивал.

    Не падает потому, что такую фразу сцена с ведущей забирает себе
    (`apply_agent_coverage`), и отсчёт валидатора сбрасывается ровно там, где
    его сбрасывает гейт. Здесь это и меряется: два куска по 7,2 с без ведущей
    разделены одной фразой схемы, и вместе они дали бы 16,8 с — больше
    `MAX_FACE_ABSENCE_S`.
    """
    edit_plan = _fast_edit_plan(10, hidden={5})
    scenes = _fast_scenes([(0.0, 4.8, True), (4.8, 12.0, False),
                           (12.0, 14.4, True), (14.4, 21.6, False),
                           (21.6, 24.0, True)])

    out = apply_agent_coverage(edit_plan, scenes)

    by_id = {phrase["id"]: phrase for phrase in out["phrases"]}
    assert by_id["phrase-005"]["coverage"] == "avatar", (
        "схема в сцене с ведущей осталась без лица — гейт D32 считает меньше "
        "валидатора, и такой план падает после оплаты озвучки")
    середина = _window_of(out, "phrase-005")
    assert середина["coverage"] == "avatar"
    assert середина["effect"] == {"type": "none"}, (
        "окно рассказывает про себя две вещи: покрытие ведущей и эффект схемы")
    report = validate_edit_plan(out, require_final=True,
                                require_asset_files=False)
    assert report["all_pass"] is True, report["errors"]
    build_avatar_render_plan(out, _config(), master_audio_sha256="sha")


def test_цель_бюджета_ниже_потолка_на_ручки_кусков():
    """Пункт 5: агент целится в число, которое меряется сложением длительностей
    фраз, а гейт судит секунды ЗАКАЗА — с ручками по краям каждого куска.
    Считается это в одном месте: задание (`hf_brief`) и гейт (`hf_render`)
    читают одну функцию, иначе агент увидит в задании одно число, а в причине
    пересдачи другое."""
    from reels_factory.avatar_islands import avatar_budget_targets
    from reels_factory.editplan import MAX_FACE_ABSENCE_S
    from reels_factory.hf_montage import (AVATAR_ON_SCREEN_HARD_MAX,
                                          AVATAR_ON_SCREEN_MAX)

    settings = {"handle_seconds": 0.2}
    targets = avatar_budget_targets(56.1, settings)

    assert targets["ceiling_seconds"] == pytest.approx(56.1 * AVATAR_ON_SCREEN_MAX)
    # Граница отказа — отдельное число и отдельный ключ: задание называет
    # агенту цель и границу разными предложениями, а гейт судит по границе.
    assert targets["hard_ceiling_seconds"] == pytest.approx(
        56.1 * AVATAR_ON_SCREEN_HARD_MAX)
    assert targets["max_ratio"] == AVATAR_ON_SCREEN_MAX
    assert targets["hard_max_ratio"] == AVATAR_ON_SCREEN_HARD_MAX
    assert AVATAR_ON_SCREEN_MAX < AVATAR_ON_SCREEN_HARD_MAX
    assert targets["pieces"] == math.ceil(56.1 / MAX_FACE_ABSENCE_S) + 1
    assert targets["target_seconds"] == pytest.approx(
        targets["ceiling_seconds"] - 2 * 0.2 * targets["pieces"])
    # Граница, переведённая в мерку агента: те же ручки, вычтенные из границы.
    # Сверка в задании идёт СЧЁТОМ АГЕНТА (сложение длительностей фраз), и
    # пункт, названный секундами заказа, обещал бы проход плану, который гейт
    # заворачивает, — ровно на ручки.
    assert targets["hard_target_seconds"] == pytest.approx(
        targets["hard_ceiling_seconds"] - 2 * 0.2 * targets["pieces"])
    assert targets["target_seconds"] < targets["hard_target_seconds"], (
        "цель и граница в счёте агента совпали — допуск исчез")
    assert targets["hard_target_seconds"] < targets["hard_ceiling_seconds"]
    # Ни одно из чисел не уходит в минус на коротком ролике — иначе агенту
    # называли бы отрицательные секунды.
    короткий = avatar_budget_targets(1.0, {"handle_seconds": 1.0})
    assert короткий["target_seconds"] == 0.0
    assert короткий["hard_target_seconds"] == 0.0
