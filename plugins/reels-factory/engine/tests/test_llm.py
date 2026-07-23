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

    r = ClaudeSkillRunner(plugin_dir=Path("C:/plug/reels-factory"),
                          config_dir=tmp_path / "profile")
    out = r.run_skill("humanizing-speech", payload)

    assert out == '{"ok": true}'
    assert "--plugin-dir" in captured["cmd"]
    i = captured["cmd"].index("--plugin-dir")
    assert captured["cmd"][i + 1] == "C:/plug/reels-factory"
    assert captured["input"].startswith("/reels-factory:humanizing-speech ")
    assert str(payload).replace("\\", "/") in captured["input"].replace("\\", "/")


def test_скилл_зовётся_в_изоляции(monkeypatch, tmp_path):
    """Чистая комната: без чужих настроек, MCP и авто-памяти."""
    captured = {}

    class P:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["env"] = kw.get("env")
        return P()

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-платный")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "тоже-платный")

    profile = tmp_path / "profile"
    r = ClaudeSkillRunner(plugin_dir=Path("C:/plug/reels-factory"), config_dir=profile)
    r.run_skill("judging-script", tmp_path / "task.json")

    cmd, env = captured["cmd"], captured["env"]
    i = cmd.index("--setting-sources")
    assert cmd[i + 1] == ""
    assert "--strict-mcp-config" in cmd
    assert env["CLAUDE_CONFIG_DIR"] == str(profile)
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert profile.is_dir()


def test_ошибка_входа_из_stdout_попадает_в_сообщение(monkeypatch, tmp_path):
    class P:
        returncode = 1
        stdout = "Failed to authenticate: OAuth session expired"
        stderr = ""

    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: P())

    r = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    with pytest.raises(RuntimeError, match="OAuth session expired"):
        r.run_skill("judging-script", tmp_path / "task.json")


def test_fake_skill_runner_records_calls(tmp_path):
    f = FakeSkillRunner(['{"a": 1}'])
    out = f.run_skill("judging-script", tmp_path / "x.json")
    assert json.loads(out) == {"a": 1}
    assert f.calls == [("judging-script", tmp_path / "x.json")]
