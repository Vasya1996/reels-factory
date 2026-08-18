"""Монтаж планирует агент под скилами HeyGen; композицию собирает наш код."""
import json

import pytest

from reels_factory.hf_agent import AgentPlanMissing, plan_with_agent

_BOARD = {"scenes": [{"id": "s-01", "intent": "и", "phrases": [0, 1],
                      "presenter": "full", "insert": None}]}


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
    """Дефект 4: ход без плана — причина пересдачи, и тип у неё свой.

    Общим `RuntimeError` этот случай не отличить от упавшего процесса `claude`,
    а зовущий обязан их различать: пустой ход стоит переспроса, авария
    окружения — нет.
    """
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    with pytest.raises(AgentPlanMissing, match="storyboard"):
        plan_with_agent(tmp_path, runner=_Runner(tmp_path, make_files=False))


def test_пустая_раскадровка_ошибка(tmp_path):
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    runner = _Runner(tmp_path)
    runner.run = lambda prompt, cwd=None: (
        (tmp_path / "storyboard.json").write_text('{"scenes": []}',
                                                  encoding="utf-8"), "готово")[1]
    with pytest.raises(AgentPlanMissing, match="ни одной сцены"):
        plan_with_agent(tmp_path, runner=runner)


def test_упавшая_сессия_пересдачей_не_считается(tmp_path):
    """Дефект 4: переспрашивать по аварии окружения нечего — второй заход
    упрётся в то же самое. Под пересдачу подпадает только пустой ответ."""
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    runner = _Runner(tmp_path)
    runner.run = lambda prompt, cwd=None: (_ for _ in ()).throw(
        RuntimeError("агент-сборщик упал (127): claude: not found"))
    with pytest.raises(RuntimeError, match="not found") as упало:
        plan_with_agent(tmp_path, runner=runner)
    assert not isinstance(упало.value, AgentPlanMissing)


def test_без_задания_ошибка(tmp_path):
    """Нет BRIEF.md — это наша ошибка, а не пустой ход агента: пересдавать
    нечего, пока задания на диске нет."""
    with pytest.raises(RuntimeError, match="BRIEF") as упало:
        plan_with_agent(tmp_path, runner=_Runner(tmp_path))
    assert not isinstance(упало.value, AgentPlanMissing)


def test_после_заказа_материал_назван_готовым(tmp_path):
    """В сборке клипы, звук и тайминги действительно лежат в `public/` — их
    кладёт `prepare()` до вызова агента."""
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    runner = _Runner(tmp_path)
    plan_with_agent(tmp_path, runner=runner)
    assert "уже лежит в `public/`" in runner.prompts[0]


def test_на_раннем_шаге_материала_ещё_нет(tmp_path):
    """Пункт 5: план идёт ДО заказа аватара, и `public/` в этот момент пуста —
    клипы и звук кладёт `prepare()` уже в сборке. Обещание готового материала
    гонит сессию искать файлы, которых на диске не будет."""
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    runner = _Runner(tmp_path)
    plan_with_agent(tmp_path, runner=runner, avatar_ordered=False)
    ход = runner.prompts[0]
    assert ход.lstrip().startswith("/hyperframes")
    assert "пока пуста" in ход
    assert "уже" not in ход.split("BRIEF.md")[-1]


def test_прошлый_ответ_агента_не_сходит_за_новый(tmp_path):
    """Пункт 7: пересдачу агент отрабатывает в той же папке. `storyboard.json`
    прошлой попытки, оставшийся на диске, прошёл бы проверку как свежий ответ —
    и сборка поехала бы по плану, который только что завернули."""
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    (tmp_path / "storyboard.json").write_text(json.dumps(_BOARD),
                                              encoding="utf-8")
    with pytest.raises(RuntimeError, match="storyboard"):
        plan_with_agent(tmp_path, runner=_Runner(tmp_path, make_files=False))
    assert not (tmp_path / "storyboard.json").exists()


def test_право_на_bash_объяснено_настоящей_причиной():
    """Пункт 9: комментарий оправдывал Bash инструментами, которых на шаге
    плана нет — media-use и `npx hyperframes add` работают в сборке, а не в
    планировании. Настоящее основание — их же роутер: четвёртым шагом он
    ставит и обновляет скилл маршрута через `npx hyperframes skills update`
    (skills/hyperframes/SKILL.md:78-84 на пине 0.7.84)."""
    import inspect

    from reels_factory import hf_agent

    исходник = inspect.getsource(hf_agent)
    assert "skills update" in исходник
    assert "media-use" not in исходник
    assert "hyperframes add" not in исходник


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


def test_модель_названа_явно_а_не_взята_по_умолчанию(monkeypatch, tmp_path):
    """Умолчание CLI меняется без нашего ведома, а вместе с ним и цена ролика:
    себестоимость считается по прайсу модели, которая работала."""
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")
    monkeypatch.delenv("REELS_AGENT_MODEL", raising=False)
    seen = {}
    monkeypatch.setattr(hf_agent.subprocess, "run", _fake_run(seen))

    hf_agent.HeyGenAgentRunner().run("/hyperframes", cwd=tmp_path)

    cmd = seen["cmd"]
    assert cmd[cmd.index("--model") + 1] == hf_agent.MODEL == "claude-sonnet-5"


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
# заняла четверть часа на плане из десяти сцен. Регулятор нужен, чтобы
# мерить это, а не гадать.

def test_усилие_по_умолчанию_среднее(monkeypatch, tmp_path):
    """На `high` прогон 11 дал два выброшенных хода по 64 000 токенов и
    27 минут без плана; на `medium` прогон 13 сдал план за десять минут."""
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")
    monkeypatch.delenv("REELS_AGENT_EFFORT", raising=False)
    seen = {}
    monkeypatch.setattr(hf_agent.subprocess, "run", _fake_run(seen))

    hf_agent.HeyGenAgentRunner().run("/hyperframes", cwd=tmp_path)

    assert seen["cmd"][seen["cmd"].index("--effort") + 1] == "medium"


def test_усилие_из_переменной_окружения(monkeypatch, tmp_path):
    """Мерить на другом материале — той же ручкой, не правкой кода."""
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")
    monkeypatch.setenv("REELS_AGENT_EFFORT", "high")
    seen = {}
    monkeypatch.setattr(hf_agent.subprocess, "run", _fake_run(seen))

    hf_agent.HeyGenAgentRunner().run("/hyperframes", cwd=tmp_path)

    assert seen["cmd"][seen["cmd"].index("--effort") + 1] == "high"


# ---------- общий кошелёк сборки ----------
#
# Одну сборку обслуживают сессии на разных моделях: план монтажа — Sonnet 5,
# отбор бироллов — Haiku 4.5. Считать их расход надо вместе, а вести одной
# обёрткой нельзя: она несёт модель и глубину рассуждения, и общая обёртка
# пересадила бы судью на дорогую модель. Общее у них только одно — кошелёк.

def _fake_run_с_ценой(seen, cost=0.01, tokens=1000):
    def run(cmd, **kw):
        seen.append([str(c) for c in cmd])

        class P:
            returncode = 0
            stdout = json.dumps({"result": "ок", "total_cost_usd": cost,
                                 "usage": {"output_tokens": tokens}})
            stderr = ""

        return P()
    return run


def test_прогоны_разных_сессий_ложатся_в_один_кошелёк(monkeypatch, tmp_path):
    """Планировщик и судья складывают расход в один кошелёк, но каждый остаётся
    на своей модели — иначе работа Haiku посчитается по ставке Sonnet."""
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")
    monkeypatch.delenv("REELS_AGENT_MODEL", raising=False)
    команды: list[list[str]] = []
    monkeypatch.setattr(hf_agent.subprocess, "run", _fake_run_с_ценой(команды))

    кошелёк = hf_agent.AgentSpend()
    hf_agent.HeyGenAgentRunner(spend=кошелёк).run("/hyperframes", cwd=tmp_path)
    hf_agent.HeyGenAgentRunner(model="claude-haiku-4-5",
                               spend=кошелёк).run("суд", cwd=tmp_path)

    assert [run["model"] for run in кошелёк.runs] == ["claude-sonnet-5",
                                                      "claude-haiku-4-5"]
    assert кошелёк.total_cost_usd == pytest.approx(0.02)
    assert [c[c.index("--model") + 1] for c in команды] == ["claude-sonnet-5",
                                                            "claude-haiku-4-5"]


def test_кошелёк_помнит_токены_каждого_прогона(monkeypatch, tmp_path):
    """Под подпиской CLI присылает нулевую стоимость, и счёт остаётся только
    по токенам: значит `usage` обязан доехать до кошелька."""
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")
    monkeypatch.setattr(hf_agent.subprocess, "run",
                        _fake_run_с_ценой([], cost=0.0, tokens=1234))

    кошелёк = hf_agent.AgentSpend()
    hf_agent.HeyGenAgentRunner(spend=кошелёк).run("/hyperframes", cwd=tmp_path)

    assert кошелёк.total_cost_usd == 0.0
    assert кошелёк.runs[0]["usage"]["output_tokens"] == 1234


def test_без_кошелька_обёртка_работает_как_прежде(monkeypatch, tmp_path):
    """Кошелёк необязателен: консольные прогоны и тесты зовут обёртку без него."""
    from reels_factory import hf_agent

    monkeypatch.setattr(hf_agent.Path, "home", lambda: tmp_path / "нет-профиля")
    monkeypatch.setattr(hf_agent.subprocess, "run", _fake_run_с_ценой([]))

    раннер = hf_agent.HeyGenAgentRunner()
    раннер.run("/hyperframes", cwd=tmp_path)

    assert раннер.total_cost_usd == pytest.approx(0.01)
    assert len(раннер.runs) == 1
