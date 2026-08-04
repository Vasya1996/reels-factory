"""Сборка композиции агентом под скилами HeyGen.

Скил — инструкция для агента, а не библиотека, поэтому композицию собирает
headless-сессия. В отличие от ClaudeSkillRunner здесь нужен ОБЫЧНЫЙ профиль
пользователя: скилы HeyGen лежат в ~/.claude/skills, а изолированный профиль
их не видит.

Заходим через парадную дверь /hyperframes: она определяет намерение и сама
подключает talking-head-recut, media-use и остальные.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

PROMPT = """/hyperframes

Смонтируй рилс по заданию. Задание — файл BRIEF.md в текущей папке.
Прочитай его целиком и следуй ему буквально: числа в нём не рекомендации,
а границы.

Материал уже готов в public/. Своё распознавание речи не запускай, картинки
сам не ищи, композицию не собирай — это делает код по твоему плану.

Верни один файл `storyboard.json` в формате из задания. Разметку не пиши
вовсе: ни HTML, ни CSS, ни JavaScript, ни файла, ни строки. Ничего не
спрашивай — все решения принимай сам."""

TIMEOUT_S = 1800

#: Что сессии разрешено. Bash нужен ради их же инструментов — media-use ищет
#: картинки скриптом на node, каталог блоков ставится через npx hyperframes.
#: Остальное — чтение и правка файлов композиции в своей рабочей папке.
AGENT_TOOLS = ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill",
               "TodoWrite")


class HeyGenAgentRunner:
    """Headless-сессия в обычном профиле, с правом писать файлы."""

    def __init__(self, timeout_s: int = TIMEOUT_S, model: str | None = None,
                 effort: str | None = None):
        self.timeout_s = timeout_s
        self.exe = shutil.which("claude") or "claude"
        # Замер себестоимости требует одного и того же задания на разных
        # моделях. Без явного выбора headless-сессия берёт модель по умолчанию,
        # и сравнить Sonnet 5 с Opus 5 нечем. Пусто — модель не навязываем.
        self.model = model or os.environ.get("REELS_AGENT_MODEL") or None
        # Глубина рассуждения сессии. По умолчанию Sonnet 5 работает на `high`,
        # и на плане монтажа это видно: 42 тысячи токенов на выходе и четверть
        # часа времени, притом что решений в плане десяток. Задание сузилось до
        # раскадровки и коротких фрагментов, думать над ним столько незачем.
        self.effort = effort or os.environ.get("REELS_AGENT_EFFORT") or None
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
             # Без явного разрешения Bash сессия получает на `node` и `npx`
             # ответ «This command requires approval» и молча остаётся без
             # инструментов: ни подобрать картинку через media-use, ни
             # заглянуть в каталог блоков. Именно так выходили пустые ролики —
             # агент не отказывался работать, он рисовал заглушки сам, потому
             # что все команды ему отбивало. acceptEdits покрывает только
             # правку файлов.
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
        self.runs.append({
            "duration_ms": obj.get("duration_ms"),
            "num_turns": obj.get("num_turns"),
            "cost_usd": cost,
            "usage": obj.get("usage"),
            "model": self.model,
        })
        return obj.get("result", "")


def plan_with_agent(rdir, *, runner=None) -> dict:
    """Попросить агента спланировать монтаж. Возвращает раскадровку."""
    rdir = Path(rdir).resolve()
    if not (rdir / "BRIEF.md").exists():
        raise RuntimeError(f"нет BRIEF.md в {rdir}")

    runner = runner or HeyGenAgentRunner()
    runner.run(PROMPT, cwd=rdir)

    storyboard = rdir / "storyboard.json"
    if not storyboard.exists():
        raise RuntimeError(f"агент не вернул {storyboard}")
    board = json.loads(storyboard.read_text(encoding="utf-8"))
    if not (board.get("cards") or []):
        raise RuntimeError("в раскадровке нет ни одной карточки")
    return board
