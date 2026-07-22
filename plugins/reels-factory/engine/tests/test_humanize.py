import json
import pytest
from reels_factory.llm import FakeSkillRunner
from reels_factory.humanize import humanize_scenario, HumanizeError

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
