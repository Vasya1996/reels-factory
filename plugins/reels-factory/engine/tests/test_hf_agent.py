"""Композицию собирает агент под скилами HeyGen, а не наш код."""
import json

import pytest

from reels_factory.hf_agent import build_with_agent


class _Runner:
    def __init__(self, rdir, make_files=True):
        self.rdir, self.make_files, self.prompts = rdir, make_files, []
        self.total_cost_usd = 0.0

    def run(self, prompt: str, cwd=None) -> str:
        self.prompts.append(prompt)
        if self.make_files:
            (self.rdir / "public").mkdir(parents=True, exist_ok=True)
            (self.rdir / "public" / "index.html").write_text("<html></html>", encoding="utf-8")
            (self.rdir / "storyboard.json").write_text(json.dumps({"cards": []}),
                                                       encoding="utf-8")
        return "готово"


def test_вход_через_парадную_дверь(tmp_path):
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    runner = _Runner(tmp_path)
    build_with_agent(tmp_path, runner=runner)
    assert runner.prompts and runner.prompts[0].lstrip().startswith("/hyperframes")


def test_раскадровка_возвращается(tmp_path):
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    assert build_with_agent(tmp_path, runner=_Runner(tmp_path)) == {"cards": []}


def test_без_композиции_ошибка(tmp_path):
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    with pytest.raises(RuntimeError, match="index.html"):
        build_with_agent(tmp_path, runner=_Runner(tmp_path, make_files=False))


def test_без_задания_ошибка(tmp_path):
    with pytest.raises(RuntimeError, match="BRIEF"):
        build_with_agent(tmp_path, runner=_Runner(tmp_path))


def test_команда_видит_обычный_профиль_и_права(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    # На этой машине ~/.reels-factory/oauth-token существует по-настоящему;
    # без этого monkeypatch тест читал бы реальный файл токена подписки.
    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["env"] = kw.get("env") or {}
        seen["cwd"] = kw.get("cwd")

        class P:
            returncode = 0
            stdout = json.dumps({"result": "ок", "total_cost_usd": 0.02})
            stderr = ""

        return P()

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_run)
    runner = hf_agent.HeyGenAgentRunner()
    runner.run("/hyperframes привет", cwd=tmp_path)

    assert "CLAUDE_CONFIG_DIR" not in seen["env"]
    assert "--setting-sources" not in " ".join(map(str, seen["cmd"]))
    assert "acceptEdits" in " ".join(map(str, seen["cmd"]))
    assert str(seen["cwd"]) == str(tmp_path)
    assert runner.total_cost_usd == 0.02


def test_headless_подхватывает_токен_подписки(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    token_dir = tmp_path / ".reels-factory"
    token_dir.mkdir()
    (token_dir / "oauth-token").write_text("fake-token-123", encoding="utf-8")

    seen = {}

    def fake_run(cmd, **kw):
        seen["env"] = kw.get("env") or {}

        class P:
            returncode = 0
            stdout = json.dumps({"result": "ок", "total_cost_usd": 0.0})
            stderr = ""

        return P()

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_run)
    runner = hf_agent.HeyGenAgentRunner()
    runner.run("/hyperframes привет", cwd=tmp_path)

    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "fake-token-123"


def test_headless_не_перекрывает_существующий_токен(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "уже-стоит")
    token_dir = tmp_path / ".reels-factory"
    token_dir.mkdir()
    (token_dir / "oauth-token").write_text("fake-token-123", encoding="utf-8")

    seen = {}

    def fake_run(cmd, **kw):
        seen["env"] = kw.get("env") or {}

        class P:
            returncode = 0
            stdout = json.dumps({"result": "ок", "total_cost_usd": 0.0})
            stderr = ""

        return P()

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_run)
    runner = hf_agent.HeyGenAgentRunner()
    runner.run("/hyperframes привет", cwd=tmp_path)

    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "уже-стоит"


def test_вывод_сессии_пишется_в_лог(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    def fake_run(cmd, **kw):
        class P:
            returncode = 0
            stdout = 'шум\n{"result": "ок", "total_cost_usd": 0.1}'
            stderr = "warn"

        return P()

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_run)
    hf_agent.HeyGenAgentRunner().run("/hyperframes х", cwd=tmp_path)
    log = (tmp_path / "agent.log").read_text(encoding="utf-8")
    assert "шум" in log and "warn" in log


def test_таймаут_из_окружения(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    monkeypatch.setenv("RF_HF_AGENT_TIMEOUT_S", "120")
    seen = {}

    def fake_run(cmd, **kw):
        seen["timeout"] = kw.get("timeout")

        class P:
            returncode = 0
            stdout = '{"result": "ок"}'
            stderr = ""

        return P()

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_run)
    hf_agent.HeyGenAgentRunner().run("х", cwd=tmp_path)
    assert seen["timeout"] == 120


def test_таймаут_даёт_понятную_ошибку_с_логом(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    def fake_run(cmd, **kw):
        raise hf_agent.subprocess.TimeoutExpired(
            cmd="claude", timeout=1, output="частичный вывод"
        )

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="agent.log"):
        hf_agent.HeyGenAgentRunner(timeout_s=1).run("х", cwd=tmp_path)
    assert "частичный вывод" in (
        tmp_path / "agent.log"
    ).read_text(encoding="utf-8")
