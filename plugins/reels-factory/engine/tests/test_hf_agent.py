"""Монтаж планирует агент под скилами HeyGen; композицию собирает наш код."""
import json

import pytest

from reels_factory.hf_agent import plan_with_agent

_BOARD = {"cards": [{"id": "card-01", "startSec": 0, "endSec": 3}]}


class _Runner:
    def __init__(self, rdir, make_files=True):
        self.rdir, self.make_files, self.prompts = rdir, make_files, []
        self.total_cost_usd = 0.0

    def run(self, prompt: str, cwd=None) -> str:
        self.prompts.append(prompt)
        if self.make_files:
            (self.rdir / "storyboard.json").write_text(json.dumps(_BOARD),
                                                       encoding="utf-8")
        return "готово"


def test_вход_через_парадную_дверь(tmp_path):
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    runner = _Runner(tmp_path)
    plan_with_agent(tmp_path, runner=runner)
    assert runner.prompts and runner.prompts[0].lstrip().startswith("/hyperframes")


def test_раскадровка_возвращается(tmp_path):
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    assert plan_with_agent(tmp_path, runner=_Runner(tmp_path)) == _BOARD


def test_без_раскадровки_ошибка(tmp_path):
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    with pytest.raises(RuntimeError, match="storyboard"):
        plan_with_agent(tmp_path, runner=_Runner(tmp_path, make_files=False))


def test_пустая_раскадровка_ошибка(tmp_path):
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    runner = _Runner(tmp_path)
    runner.run = lambda prompt, cwd=None: (
        (tmp_path / "storyboard.json").write_text('{"cards": []}',
                                                  encoding="utf-8"), "готово")[1]
    with pytest.raises(RuntimeError, match="ни одной карточки"):
        plan_with_agent(tmp_path, runner=runner)


def test_без_задания_ошибка(tmp_path):
    with pytest.raises(RuntimeError, match="BRIEF"):
        plan_with_agent(tmp_path, runner=_Runner(tmp_path))


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


# ---------- выбор модели ----------
#
# Замер себестоимости требует прогнать одно и то же задание на разных моделях.
# Без флага --model headless-сессия берёт модель по умолчанию, и сравнить
# Sonnet 5 с Opus 5 на одном материале нечем.

def _fake_run(seen):
    def run(cmd, **kw):
        seen["cmd"] = [str(c) for c in cmd]

        class P:
            returncode = 0
            stdout = json.dumps({"result": "ок", "total_cost_usd": 0.01})
            stderr = ""

        return P()
    return run


def test_модель_не_задана_флага_нет(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")
    monkeypatch.delenv("REELS_AGENT_MODEL", raising=False)
    seen = {}
    monkeypatch.setattr(hf_agent.subprocess, "run", _fake_run(seen))

    hf_agent.HeyGenAgentRunner().run("/hyperframes", cwd=tmp_path)

    assert "--model" not in seen["cmd"]


def test_модель_из_переменной_окружения(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")
    monkeypatch.setenv("REELS_AGENT_MODEL", "claude-sonnet-5")
    seen = {}
    monkeypatch.setattr(hf_agent.subprocess, "run", _fake_run(seen))

    hf_agent.HeyGenAgentRunner().run("/hyperframes", cwd=tmp_path)

    assert seen["cmd"][seen["cmd"].index("--model") + 1] == "claude-sonnet-5"


def test_модель_явным_аргументом_бьёт_окружение(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")
    monkeypatch.setenv("REELS_AGENT_MODEL", "claude-sonnet-5")
    seen = {}
    monkeypatch.setattr(hf_agent.subprocess, "run", _fake_run(seen))

    hf_agent.HeyGenAgentRunner(model="claude-opus-5").run("/hyperframes", cwd=tmp_path)

    assert seen["cmd"][seen["cmd"].index("--model") + 1] == "claude-opus-5"


# ---------- глубина рассуждения ----------
#
# На `high` (умолчание Sonnet 5) сессия отдала 42 тысячи токенов выхода и
# заняла четверть часа на плане из десяти карточек. Регулятор нужен, чтобы
# мерить это, а не гадать.

def test_усилие_не_задано_флага_нет(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")
    monkeypatch.delenv("REELS_AGENT_EFFORT", raising=False)
    seen = {}
    monkeypatch.setattr(hf_agent.subprocess, "run", _fake_run(seen))

    hf_agent.HeyGenAgentRunner().run("/hyperframes", cwd=tmp_path)

    assert "--effort" not in seen["cmd"]


def test_усилие_из_переменной_окружения(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")
    monkeypatch.setenv("REELS_AGENT_EFFORT", "medium")
    seen = {}
    monkeypatch.setattr(hf_agent.subprocess, "run", _fake_run(seen))

    hf_agent.HeyGenAgentRunner().run("/hyperframes", cwd=tmp_path)

    assert seen["cmd"][seen["cmd"].index("--effort") + 1] == "medium"
