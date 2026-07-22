import json
import pytest
from reels_factory.llm import FakeSkillRunner
from reels_factory.humanize import humanize_scenario, HumanizeError
from reels_factory.humanize import judge_scenario, refine_loop

SC = {"mode": "verbatim", "blocks": [
    {"role": "hook", "start": 0.0, "end": 2.0, "speech": "Мы внедрили Microsoft CRM."},
    {"role": "development", "start": 2.0, "end": 5.0, "speech": "Продажи выросли."},
]}


def test_humanize_writes_task_and_applies_reply(tmp_path):
    reply = json.dumps({"blocks": [
        {"role": "hook", "speech": "Мы внедрили Майкрософт Си-Ар-Эм."},
        {"role": "development", "speech": "Продажи выросли."},
    ]}, ensure_ascii=False)
    runner = FakeSkillRunner([reply])

    out = humanize_scenario(runner, tmp_path, SC, mode="phonetics", language="ru")

    assert out["blocks"][0]["speech"] == "Мы внедрили Майкрософт Си-Ар-Эм."
    assert out["blocks"][0]["start"] == 0.0  # тайминги сохранены
    skill, payload_path = runner.calls[0]
    assert skill == "humanizing-speech"
    task = json.loads(payload_path.read_text(encoding="utf-8"))
    assert task["mode"] == "phonetics"
    assert task["language"] == "ru"
    assert [b["role"] for b in task["blocks"]] == ["hook", "development"]


def test_humanize_rejects_block_mismatch(tmp_path):
    reply = json.dumps({"blocks": [{"role": "hook", "speech": "х"}]})
    runner = FakeSkillRunner([reply])
    with pytest.raises(HumanizeError):
        humanize_scenario(runner, tmp_path, SC, mode="polish", language="ru")


def test_humanize_rejects_bad_mode(tmp_path):
    with pytest.raises(HumanizeError):
        humanize_scenario(FakeSkillRunner([]), tmp_path, SC, mode="x", language="ru")


TASK = {"idea": "как мы подняли продажи", "length_s": 30}


def _blocks_reply(suffix=""):
    return json.dumps({"blocks": [
        {"role": "hook", "speech": "Хук" + suffix},
        {"role": "development", "speech": "Развитие" + suffix},
    ]}, ensure_ascii=False)


VERDICT_FAIL = json.dumps({"pass": False,
                           "scores": {"hook": False},
                           "issues": [{"criterion": "hook", "where": "Хук",
                                       "what": "не цепляет", "fix": "начни с цифры"}]},
                          ensure_ascii=False)
VERDICT_PASS = json.dumps({"pass": True, "scores": {"hook": True}, "issues": []},
                          ensure_ascii=False)


def test_judge_scenario_parses_verdict(tmp_path):
    runner = FakeSkillRunner([VERDICT_PASS])
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 2.0, "speech": "х"}]}
    v = judge_scenario(runner, tmp_path, sc, TASK, "ru")
    assert v["pass"] is True
    assert runner.calls[0][0] == "judging-script"


def test_refine_loop_retries_until_pass(tmp_path):
    sc = {"blocks": [
        {"role": "hook", "start": 0.0, "end": 2.0, "speech": "а"},
        {"role": "development", "start": 2.0, "end": 4.0, "speech": "б"},
    ]}
    runner = FakeSkillRunner([
        _blocks_reply(" v1"), VERDICT_FAIL,   # круг 1: polish + брак
        _blocks_reply(" v2"), VERDICT_PASS,   # круг 2: polish с претензиями + pass
    ])
    final, verdict = refine_loop(runner, tmp_path, sc, TASK, "ru", max_rounds=2)
    assert verdict["pass"] is True
    assert final["blocks"][0]["speech"] == "Хук v2"
    # претензии судьи дошли до редактора на 2-м круге
    second_polish_task = json.loads(runner.calls[2][1].read_text(encoding="utf-8"))
    assert second_polish_task.get("issues")


def test_refine_loop_returns_last_on_exhaust(tmp_path):
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 2.0, "speech": "а"}]}
    runner = FakeSkillRunner([
        json.dumps({"blocks": [{"role": "hook", "speech": "v1"}]}), VERDICT_FAIL,
        json.dumps({"blocks": [{"role": "hook", "speech": "v2"}]}), VERDICT_FAIL,
    ])
    final, verdict = refine_loop(runner, tmp_path, sc, TASK, "ru", max_rounds=2)
    assert verdict["pass"] is False
    assert final["blocks"][0]["speech"] == "v2"
