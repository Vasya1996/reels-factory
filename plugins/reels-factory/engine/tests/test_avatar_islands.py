import copy
import hashlib
import json
from pathlib import Path

import pytest

from reels_factory.avatar_islands import (
    RENDER_MANIFEST_FILENAME,
    RENDER_PLAN_FILENAME,
    build_avatar_render_plan,
    render_avatar_islands,
    validate_avatar_render_plan,
)
from reels_factory.editplan import EDIT_PLAN_FORMAT_VERSION


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


def test_validator_detects_duplicate_visible_phrase():
    edit_plan = _final_edit_plan(30)
    plan = build_avatar_render_plan(edit_plan, _config())
    plan["shots"][1]["phrase_ids"].append(plan["shots"][0]["phrase_ids"][0])
    report = validate_avatar_render_plan(plan, edit_plan)
    assert report["all_pass"] is False
    assert any("ровно один раз" in error for error in report["errors"])
