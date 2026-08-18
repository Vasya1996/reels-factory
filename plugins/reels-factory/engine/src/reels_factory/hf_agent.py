"""Сборка композиции агентом под скилами HeyGen.

Скил — инструкция для агента, а не библиотека, поэтому композицию собирает
headless-сессия. В отличие от ClaudeSkillRunner здесь нужен ОБЫЧНЫЙ профиль
пользователя: скилы HeyGen лежат в ~/.claude/skills, а изолированный профиль
их не видит.

Заходим через парадную дверь /hyperframes. Намерение она в нашем случае не
определяет: BRIEF.md уже лежит на месте, а для этого состояния её таблица велит
прочитать `workflow` и `flow` из шапки и сразу исполнять названный маршрут, не
задавая вопросов брифа (SKILL.md:28). Маршрут задаёт hf_brief.WORKFLOW.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

#: Прежняя редакция добавляла «следуй буквально: числа не рекомендации, а
#: границы». Строку сняли: часть чисел задания — ориентиры («сцена живёт 1,5–4
#: секунды»), а модель этого поколения исполняет такую приписку дословно и
#: ужимает план под цифру («the model may follow that instruction literally»,
#: prompt-engineering/prompting-claude-opus-5). Где число жёсткое, сказано на
#: месте самого числа.
PROMPT = """/hyperframes

Смонтируй рилс по заданию. Задание — файл BRIEF.md в текущей папке: прочитай
его целиком и начни с раздела «Порядок работы». {material}"""

#: Чем занята `public/` на этом шаге. Ситуации две, и называть их одинаково
#: нельзя: на раннем шаге (план ДО заказа аватара) клипов и звука там ещё нет —
#: их кладёт `prepare()` уже в сборке, после того как HeyGen снимет ведущую
#: ровно по этому плану. Обещание готового материала стоит сессии ходов: она
#: идёт искать файлы, которых на диске не будет.
MATERIAL_READY = ("Материал — клипы ведущей, `voice.wav` и `words.json` — уже "
                  "лежит в `public/`.")
MATERIAL_LATER = ("Ведущую снимут у HeyGen по этому плану, поэтому `public/` "
                  "пока пуста: планируй по фразам озвучки из задания — их "
                  "номера, роли и длительности там перечислены.")


def prompt_for(avatar_ordered: bool) -> str:
    """Первый ход сессии под ситуацию шага."""
    return PROMPT.format(
        material=MATERIAL_READY if avatar_ordered else MATERIAL_LATER)

#: Автономность и границы работы — в системный промпт, а не в задание: их же
#: дока говорит, что текст пользовательского хода весит меньше того же текста
#: в системном промпте (code.claude.com/docs/en/agent-sdk/modifying-system-prompts),
#: а формулировки взяты у них же, со страницы про автономные прогоны
#: (build-with-claude/prompt-engineering/prompting-claude-fable-5).
#:
#: `--append-system-prompt`, а не `--system-prompt`: полная замена отбирает у
#: сессии их собственные инструкции по инструментам и безопасности, и чинить их
#: пришлось бы нам («You take responsibility for replacing the tool guidance and
#: safety instructions your agent still needs», там же).
SYSTEM_PROMPT = """Ты режиссёр монтажа вертикальных рилсов: решаешь, что
показать в каждой сцене.

Ты работаешь автономно: человек не смотрит за прогоном и не может ответить на
вопрос по ходу дела. Все решения принимай сам. Перед тем как закончить ход,
посмотри на последний абзац: если это план, вопрос или обещание сделать
(«сейчас соберу», «дай знать») — сделай эту работу сейчас же, инструментами.
Заканчивай ход готовыми файлами.

Сделай ровно то, что просит задание, в его объёме: не берись за работу, которую
задание отдало коду, и не расширяй её сам.

Твой ответ — два файла на диске, `storyboard.json` и `frame.md`. Текст в чат
никто не читает: держи его коротким."""

TIMEOUT_S = 1800

#: Глубина рассуждения по умолчанию. Обоснование — в комментарии к `effort`.
EFFORT = "medium"

#: Модель плана монтажа. Обоснование — в комментарии к `self.model`.
MODEL = "claude-sonnet-5"

#: Что сессии разрешено. Bash нужен их собственному маршруту: роутер
#: `/hyperframes` четвёртым шагом ставит и обновляет скилл маршрута командой
#: `npx hyperframes skills update <workflow-name>` и требует показать ошибку,
#: а не собирать маршрут по памяти («If the command fails, surface the error;
#: do not reconstruct the workflow from memory», skills/hyperframes/SKILL.md:78-84
#: на пине 0.7.84). Остальное — чтение и правка файлов в своей рабочей папке.
AGENT_TOOLS = ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill",
               "TodoWrite")


class AgentPlanMissing(RuntimeError):
    """Ход закончился, а плана на диске нет — или он пуст.

    Отдельный тип, потому что зовущему это не авария, а причина пересдачи:
    сессия обрывается по своим причинам (потолок вывода, истёкшее время), и
    второй заход обычно отвечает. Наследуемся от `RuntimeError`: вызывающий,
    который ловит его целиком, работает как прежде.

    Упавший процесс `claude` под этот тип не подпадает намеренно — это авария
    окружения, и переспрос по ней ничего не чинит.
    """


class AgentSpend:
    """Общий кошелёк сборки: куда все её сессии складывают свой расход.

    Одну сборку обслуживают сессии на разных моделях — план монтажа на Sonnet 5
    и суд бироллов на Haiku 4.5 (`judge_previews` в `hf_media.py`). Обёртка
    несёт модель и глубину рассуждения, поэтому вести обе одной нельзя: судья
    пересел бы на дорогую модель, а его прогоны посчитались бы по её ставке.
    Общее у них ровно одно — счёт, и он живёт здесь.

    Сессии судьи идут параллельно (`pool.map` в `_resolve_videos`), поэтому
    добавление под локом: список у CPython потокобезопасен и сам, а `+=` на
    сумме — нет, и полагаться на порядок байткода тут незачем.
    """

    def __init__(self) -> None:
        self.total_cost_usd = 0.0
        self.runs: list[dict] = []
        self._lock = threading.Lock()

    def add(self, run: dict, cost_usd: float = 0.0) -> None:
        with self._lock:
            self.runs.append(run)
            self.total_cost_usd += float(cost_usd or 0.0)


class HeyGenAgentRunner:
    """Headless-сессия в обычном профиле, с правом писать файлы."""

    def __init__(self, timeout_s: int = TIMEOUT_S, model: str | None = None,
                 effort: str | None = None, spend: AgentSpend | None = None):
        self.timeout_s = timeout_s
        # Кошелёк сборки, если она его завела. Своя пара `total_cost_usd`/`runs`
        # остаётся при любом раскладе: по ней мерят один прогон в консоли.
        self.spend = spend
        self.exe = shutil.which("claude") or "claude"
        # Замер себестоимости требует одного и того же задания на разных
        # моделях, поэтому модель называется явно, а не берётся по умолчанию:
        # умолчание CLI меняется без нашего ведома, и вместе с ним меняется
        # цена ролика, посчитанная по прайсу этой модели. Переменная окружения
        # перекрывает — так и меряют Sonnet 5 против Opus 5.
        self.model = model or os.environ.get("REELS_AGENT_MODEL") or MODEL
        # Глубина рассуждения сессии. По умолчанию Sonnet 5 работает на `high`,
        # и на плане монтажа это видно. Замерено на одном материале:
        #
        #   high    — прогон 11: два хода подряд по 64 000 токенов размышления,
        #             оба упёрлись в потолок вывода и были выброшены, 27 минут
        #             и ни строчки плана;
        #   medium  — прогон 13: план за 10 минут, 5 ходов, 55 тысяч токенов,
        #             все гейты зелёные с первой попытки.
        #
        # Решений в плане десяток, думать над ним больше незачем. Переменная
        # окружения перекрывает — на другом материале мерить заново.
        self.effort = effort or os.environ.get("REELS_AGENT_EFFORT") or EFFORT
        self.total_cost_usd = 0.0
        self.runs: list[dict] = []

    def run(self, prompt: str, cwd=None) -> str:
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env.pop("CLAUDE_CONFIG_DIR", None)  # нужен обычный профиль со скилами
        # Headless-вызов не умеет продлевать интерактивную OAuth-сессию:
        # без CLAUDE_CODE_OAUTH_TOKEN он падает «OAuth session expired», даже
        # когда десктопная сессия жива. Годовой токен подписки (claude
        # setup-token) уже лежит рядом с профилем бота.
        token_file = Path.home() / ".reels-factory" / "oauth-token"
        if not env.get("CLAUDE_CODE_OAUTH_TOKEN") and token_file.exists():
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token_file.read_text(
                encoding="utf-8").strip()
        model_args = ["--model", self.model] if self.model else []
        if self.effort:
            model_args += ["--effort", self.effort]
        result = subprocess.run(
            [self.exe, "-p", "--output-format", "json",
             "--permission-mode", "acceptEdits",
             "--append-system-prompt", SYSTEM_PROMPT,
             # Без явного разрешения Bash сессия получает на `node` и `npx`
             # ответ «This command requires approval» и молча остаётся без
             # своего же маршрута: `npx hyperframes skills update` не проходит.
             # Именно так выходили пустые ролики — агент не отказывался
             # работать, он рисовал заглушки сам, потому что все команды ему
             # отбивало. acceptEdits покрывает только правку файлов.
             "--allowedTools", *AGENT_TOOLS, *model_args],
            input=prompt, capture_output=True, text=True, encoding="utf-8",
            timeout=self.timeout_s, env=env, cwd=str(cwd) if cwd else None,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"агент-сборщик упал ({result.returncode}): "
                f"{(result.stderr or result.stdout)[:500]}")
        text = (result.stdout or "").strip()
        obj = json.loads(text[text.index("{"):])
        if obj.get("is_error"):
            raise RuntimeError(f"агент-сборщик вернул ошибку: {obj.get('result')}")
        cost = obj.get("total_cost_usd")
        if cost:
            self.total_cost_usd += float(cost)
        # Себестоимость прогона считают по этим числам, а не по ощущению:
        # сколько ходов сделала сессия, сколько токенов прочла и написала.
        # Под подпиской `total_cost_usd` бывает нулевым, и тогда единственный
        # честный счёт — токены.
        run = {
            "duration_ms": obj.get("duration_ms"),
            "num_turns": obj.get("num_turns"),
            "cost_usd": cost,
            "usage": obj.get("usage"),
            "model": self.model,
        }
        self.runs.append(run)
        if self.spend is not None:
            self.spend.add(run, cost or 0.0)
        return obj.get("result", "")


def plan_with_agent(rdir, *, runner=None, avatar_ordered: bool = True) -> dict:
    """Попросить агента спланировать монтаж. Возвращает раскадровку.

    Обёртку заводит вызывающий и отдаёт её вместе с кошельком ролика
    (`HeyGenAgentRunner(spend=…)`): обе точки входа — `plan_before_avatar` и
    `assemble_hyperframes` — делают именно так. Умолчание `runner=None` заводит
    сессию БЕЗ кошелька, и её расход (по замеру $0,45 за ролик) остаётся при
    функции, то есть мимо счёта пользователя. Годится оно только там, где счёта
    нет вовсе, — в ручном прогоне из консоли.

    `avatar_ordered=False` — план ДО заказа аватара: клипов и звука в `public/`
    ещё нет, и первый ход говорит об этом прямо.

    Ход, закончившийся без плана, поднимает `AgentPlanMissing` — по нему
    вызывающий даёт пересдачу, а не роняет сборку (`plan_before_avatar`).
    """
    rdir = Path(rdir).resolve()
    if not (rdir / "BRIEF.md").exists():
        raise RuntimeError(f"нет BRIEF.md в {rdir}")

    storyboard = rdir / "storyboard.json"
    # Прошлый ответ снимаем ДО запуска: пересдачу агент отрабатывает в той же
    # папке, и файл прошлой попытки прошёл бы проверку ниже как новый ответ —
    # сборка поехала бы по плану, который только что завернули. Пусто на диске
    # значит «агент не ответил», и это видно сразу.
    storyboard.unlink(missing_ok=True)

    runner = runner or HeyGenAgentRunner()
    runner.run(prompt_for(avatar_ordered), cwd=rdir)

    if not storyboard.exists():
        raise AgentPlanMissing(f"агент не вернул {storyboard}")
    board = json.loads(storyboard.read_text(encoding="utf-8"))
    if not (board.get("scenes") or []):
        raise AgentPlanMissing("в раскадровке нет ни одной сцены")
    # Нетронутая копия плана. `storyboard.json` сборка переписывает — дописывает
    # секунды и снимает `phrases`, — и пересборка без агента читала бы уже не
    # план, а его отпечаток: диапазонов фраз там нет, разложить нечего.
    (rdir / "plan.json").write_text(
        json.dumps(board, ensure_ascii=False, indent=1), encoding="utf-8")
    return board
