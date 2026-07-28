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

Собери композицию по заданию. Задание — файл BRIEF.md в текущей папке.
Прочитай его целиком и следуй ему буквально: числа в нём не рекомендации,
а границы.

Материал уже готов в public/. Своё распознавание речи не запускай.

Верни ровно два файла: public/index.html и storyboard.json в формате из
задания. Ничего не спрашивай — все решения принимай сам."""

TIMEOUT_S = 1800


class HeyGenAgentRunner:
    """Headless-сессия в обычном профиле, с правом писать файлы."""

    def __init__(self, timeout_s: int = TIMEOUT_S):
        self.timeout_s = timeout_s
        self.exe = shutil.which("claude") or "claude"
        self.total_cost_usd = 0.0

    def run(self, prompt: str, cwd=None) -> str:
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env.pop("CLAUDE_CONFIG_DIR", None)  # нужен обычный профиль со скилами
        result = subprocess.run(
            [self.exe, "-p", "--output-format", "json",
             "--permission-mode", "acceptEdits"],
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
        return obj.get("result", "")


def build_with_agent(rdir, *, runner=None) -> dict:
    """Попросить агента собрать композицию. Возвращает раскадровку."""
    rdir = Path(rdir).resolve()
    if not (rdir / "BRIEF.md").exists():
        raise RuntimeError(f"нет BRIEF.md в {rdir}")

    runner = runner or HeyGenAgentRunner()
    runner.run(PROMPT, cwd=rdir)

    composition = rdir / "public" / "index.html"
    if not composition.exists():
        raise RuntimeError(f"агент не вернул {composition}")
    storyboard = rdir / "storyboard.json"
    if not storyboard.exists():
        raise RuntimeError(f"агент не вернул {storyboard}")
    return json.loads(storyboard.read_text(encoding="utf-8"))
