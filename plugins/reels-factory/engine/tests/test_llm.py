import json
from pathlib import Path
import pytest
from reels_factory.llm import FakeRunner, ClaudeCliRunner, ClaudeSkillRunner, FakeSkillRunner


def test_fake_runner_отдаёт_по_очереди_и_копит_промпты():
    r = FakeRunner(["a", "b"])
    assert r.run("p1") == "a"
    assert r.run("p2") == "b"
    assert r.prompts == ["p1", "p2"]


@pytest.mark.slow
def test_claude_cli_живой_вызов():
    r = ClaudeCliRunner(timeout_s=120)
    out = r.run("Ответь ровно одним словом без знаков препинания: пингвин")
    assert "пингвин" in out.lower()


def test_claude_skill_runner_builds_command(monkeypatch, tmp_path):
    captured = {}

    class P:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["input"] = kw.get("input")
        return P()

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)
    payload = tmp_path / "task.json"
    payload.write_text("{}", encoding="utf-8")

    r = ClaudeSkillRunner(plugin_dir=Path("C:/plug/reels-factory"))
    out = r.run_skill("humanizing-speech", payload)

    assert out == '{"ok": true}'
    assert "--plugin-dir" in captured["cmd"]
    i = captured["cmd"].index("--plugin-dir")
    assert captured["cmd"][i + 1] == "C:/plug/reels-factory"
    assert captured["input"].startswith("/reels-factory:humanizing-speech ")
    assert str(payload).replace("\\", "/") in captured["input"].replace("\\", "/")


def test_fake_skill_runner_records_calls(tmp_path):
    f = FakeSkillRunner(['{"a": 1}'])
    out = f.run_skill("judging-script", tmp_path / "x.json")
    assert json.loads(out) == {"a": 1}
    assert f.calls == [("judging-script", tmp_path / "x.json")]
