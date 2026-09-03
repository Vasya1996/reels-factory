import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from reels_factory.llm import (FakeRunner, ClaudeCliRunner, ClaudeSkillRunner,
                               FakeSkillRunner)


def test_fake_runner_отдаёт_по_очереди_и_копит_промпты():
    r = FakeRunner(["a", "b"])
    assert r.run("p1") == "a"
    assert r.run("p2") == "b"
    assert r.prompts == ["p1", "p2"]


def test_вызов_движка_идёт_в_изоляции(monkeypatch, tmp_path):
    """Чужой профиль машины не должен ронять сборку.

    22.08 на проде `claude -p` падал кодом 1 на любом промпте: в общем профиле
    лежало правило `Write(//root/ward/**)` от соседнего проекта. Сценарий,
    визуальный директор и жесты ходят через этот раннер.
    """
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["env"] = kw.get("env")
        return SimpleNamespace(returncode=0, stdout="ок", stderr="")

    monkeypatch.setattr("reels_factory.llm.subprocess.run", fake_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-платный")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "тоже-платный")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "токен-подписки")

    profile = tmp_path / "profile"
    assert ClaudeCliRunner(config_dir=profile).run("промпт") == "ок"

    cmd, env = captured["cmd"], captured["env"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in cmd
    assert env["CLAUDE_CONFIG_DIR"] == str(profile)
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    # Платный ключ приоритетнее подписки — иначе вызовы уедут на API...
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    # ...а токен подписки приходит окружением и обязан дожить до CLI.
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "токен-подписки"
    assert profile.is_dir()


def test_токен_подписки_берётся_из_файла_когда_переменной_нет(monkeypatch, tmp_path):
    """Чистый профиль не хранит вход: без токена CLI отвечает «OAuth session
    expired». На проде переменная приходит из bot.env, на машине разработчика
    её нет — тогда годовой токен читается из файла (как в hf_agent.py:171)."""
    captured = {}

    def fake_run(cmd, **kw):
        captured["env"] = kw.get("env")
        return SimpleNamespace(returncode=0, stdout="ок", stderr="")

    monkeypatch.setattr("reels_factory.llm.subprocess.run", fake_run)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    файл = tmp_path / "oauth-token"
    файл.write_text("годовой-токен\n", encoding="utf-8")
    monkeypatch.setattr("reels_factory.llm.OAUTH_TOKEN_FILE", файл)

    ClaudeCliRunner(config_dir=tmp_path / "p").run("промпт")
    assert captured["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "годовой-токен"


def test_схема_ответа_переживает_изоляцию(monkeypatch, tmp_path):
    """Жест выбирается из enum-а: `--json-schema` едет вместе с флагами."""
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout='{"жест": "точка"}', stderr="")

    monkeypatch.setattr("reels_factory.llm.subprocess.run", fake_run)
    schema = {"type": "object", "properties": {"жест": {"enum": ["точка"]}}}

    ClaudeCliRunner(json_schema=schema, config_dir=tmp_path / "p").run("промпт")

    cmd = captured["cmd"]
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == schema
    assert cmd[cmd.index("--tools") + 1] == ""


@pytest.mark.parametrize("вывод, кусок_причины", [
    ("Failed to authenticate: OAuth session expired",
     "CLAUDE_CODE_OAUTH_TOKEN"),
    ("Permission allow rule (settings.json): Write(//root/ward/**) is not "
     "matched by file permission checks",
     "чужого профиля"),
    ("error: unknown option '--tools'", "claude --help"),
])
def test_отказ_называет_причину(monkeypatch, tmp_path, вывод, кусок_причины):
    """В журнале службы должно быть видно, что чинить, а не «code 1»."""
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        # ошибки входа CLI печатает в stdout, а не в stderr
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout=вывод, stderr=""),
    )
    with pytest.raises(RuntimeError) as exc:
        ClaudeCliRunner(config_dir=tmp_path / "p").run("промпт")
    assert кусок_причины in str(exc.value)
    assert вывод[:40] in str(exc.value)


@pytest.mark.slow
def test_claude_cli_живой_вызов():
    r = ClaudeCliRunner(timeout_s=120)
    out = r.run("Ответь ровно одним словом без знаков препинания: пингвин")
    assert "пингвин" in out.lower()


def test_claude_skill_runner_builds_command(monkeypatch, tmp_path):
    captured = {}

    class P:
        returncode = 0
        stdout = '{"result": "{\\"ok\\": true}", "total_cost_usd": 0.01}'
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


def test_run_skill_сужает_набор_инструментов_флагом_tools(monkeypatch, tmp_path):
    """Задача 12: `--allowedTools` только снимает вопрос разрешения, набор
    видимых моделью инструментов им не сужается (code.claude.com/docs/en/
    cli-reference: «To restrict which tools are available, use --tools
    instead»). Без `--tools` модель видела WebFetch и на материале со ссылкой
    просила доступ вместо JSON — 5 факапов у 4 людей 2-3 сентября."""
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"result": "ок", "total_cost_usd": 0.0}),
            stderr="",
        )

    monkeypatch.setattr("reels_factory.llm.subprocess.run", fake_run)
    ClaudeSkillRunner(config_dir=tmp_path / "profile").run_skill(
        "writing-scenario", tmp_path / "p.json")

    cmd = captured["cmd"]
    assert "--allowedTools" in cmd  # снятие вопроса остаётся как было
    i = cmd.index("--tools")
    assert cmd[i + 1] == "Read,Glob,Grep"


def test_run_skill_с_json_schema_читает_structured_output(monkeypatch, tmp_path):
    """`--json-schema` едет вместе с прочими флагами, а ответ достаётся из
    поля structured_output конверта CLI (docs/en/agent-sdk/structured-outputs:
    «the result message includes a structured_output field»)."""
    captured = {}
    schema = {"type": "object", "properties": {"blocks": {"type": "array"}}}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "subtype": "success", "is_error": False,
                "structured_output": {"blocks": [{"role": "hook", "speech": "х"}]},
                "total_cost_usd": 0.01,
            }),
            stderr="",
        )

    monkeypatch.setattr("reels_factory.llm.subprocess.run", fake_run)
    r = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    out = r.run_skill("writing-scenario", tmp_path / "p.json", json_schema=schema)

    cmd = captured["cmd"]
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == schema
    assert json.loads(out) == {"blocks": [{"role": "hook", "speech": "х"}]}


def test_run_skill_без_structured_output_при_success_считается_отказом(monkeypatch, tmp_path):
    """docs/en/agent-sdk/structured-outputs, «Error handling»: success без
    structured_output бывает и без сбоя валидации — «Treat that case as a
    failure as well». Тут это RuntimeError, чтобы `_skill_json` (scenario.py)
    завёл его в свой повтор, как и любой другой отказ вызова."""
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"subtype": "success", "is_error": False,
                               "total_cost_usd": 0.0}),
            stderr="",
        ),
    )
    r = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    with pytest.raises(RuntimeError, match="structured_output"):
        r.run_skill("writing-scenario", tmp_path / "p.json",
                    json_schema={"type": "object"})


def test_скилл_зовётся_в_изоляции(monkeypatch, tmp_path):
    """Чистая комната: без чужих настроек, MCP и авто-памяти."""
    captured = {}

    class P:
        returncode = 0
        stdout = '{"result": "ok", "total_cost_usd": 0.01}'
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


def test_скилл_возвращает_текст_из_json(monkeypatch, tmp_path):
    payload = json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "result": "готовый текст сценария",
        "total_cost_usd": 0.0342,
    })
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=payload, stderr=""),
    )
    runner = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    assert runner.run_skill("script", "payload.json") == "готовый текст сценария"
    assert runner.last_cost_usd == 0.0342


def test_скилл_просит_json_формат(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"result": "ок", "total_cost_usd": 0.01}),
            stderr="",
        )

    monkeypatch.setattr("reels_factory.llm.subprocess.run", fake_run)
    ClaudeSkillRunner(config_dir=tmp_path / "profile").run_skill("script", "p.json")
    assert "--output-format" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("--output-format") + 1] == "json"


def test_шум_перед_json_не_ломает_разбор(monkeypatch, tmp_path):
    # node и прочие подпроцессы пишут в тот же stdout; берём последний
    # JSON-объект, а не весь поток целиком.
    noisy = 'npm warn something\n' + json.dumps({"result": "ок", "total_cost_usd": 0.02})
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=noisy, stderr=""),
    )
    runner = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    assert runner.run_skill("script", "p.json") == "ок"
    assert runner.last_cost_usd == 0.02


def test_стоимость_нескольких_вызовов_суммируется(monkeypatch, tmp_path):
    # Один runner обслуживает генерацию, хуманизатор и судью подряд —
    # по last_cost_usd видно только последний вызов.
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"result": "ок", "total_cost_usd": 0.01}),
            stderr="",
        ),
    )
    runner = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    runner.run_skill("script", "p.json")
    runner.run_skill("humanizing-speech", "p.json")
    runner.run_skill("judge", "p.json")
    assert runner.last_cost_usd == 0.01
    assert round(runner.total_cost_usd, 4) == 0.03


def test_прогоны_помнят_токены_и_модель(monkeypatch, tmp_path):
    """Под подпиской CLI присылает нулевую стоимость, и единственный честный
    счёт остаётся по токенам — значит `usage` каждого вызова надо сохранить."""
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"result": "ок", "total_cost_usd": 0.0,
                               "model": "claude-sonnet-5",
                               "usage": {"input_tokens": 700,
                                         "output_tokens": 2100}}),
            stderr="",
        ),
    )
    runner = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    runner.run_skill("script", "p.json")
    runner.run_skill("judge", "p.json")

    assert runner.total_cost_usd == 0.0
    assert [run["usage"]["output_tokens"] for run in runner.runs] == [2100, 2100]
    assert {run["model"] for run in runner.runs} == {"claude-sonnet-5"}


def test_невалидный_json_падает_понятной_ошибкой(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="не json вовсе", stderr=""),
    )
    runner = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    try:
        runner.run_skill("script", "p.json")
    except RuntimeError as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("ожидали RuntimeError")


def test_ошибка_выполнения_не_уезжает_как_ответ_скилла(monkeypatch, tmp_path):
    """is_error=True при коде 0: текст ошибки CLI — не сценарий."""
    envelope = json.dumps({
        "type": "result", "subtype": "success", "is_error": True,
        "result": "Failed to authenticate: OAuth session expired",
        "total_cost_usd": 0.0,
    })
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=envelope, stderr=""),
    )
    runner = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    with pytest.raises(RuntimeError, match="OAuth session expired"):
        runner.run_skill("writing-scenario", "p.json")


def test_отказ_инструмента_виден_в_ошибке(monkeypatch, tmp_path):
    envelope = json.dumps({
        "subtype": "error_max_turns", "is_error": True,
        "permission_denials": [{"tool_name": "Read"}],
        "total_cost_usd": 0.02,
    })
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=envelope, stderr=""),
    )
    runner = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    with pytest.raises(RuntimeError) as exc:
        runner.run_skill("writing-scenario", "p.json")
    assert "error_max_turns" in str(exc.value)
    assert "Read" in str(exc.value)
    # вызов всё равно оплачен — трата должна попасть в журнал
    assert runner.total_cost_usd == 0.02


def test_конверт_без_result_падает(monkeypatch, tmp_path):
    envelope = json.dumps({"subtype": "success", "is_error": False,
                           "total_cost_usd": 0.01})
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=envelope, stderr=""),
    )
    runner = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    with pytest.raises(RuntimeError, match="без поля result"):
        runner.run_skill("writing-scenario", "p.json")
