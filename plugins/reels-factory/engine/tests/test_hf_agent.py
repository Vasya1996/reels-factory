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
