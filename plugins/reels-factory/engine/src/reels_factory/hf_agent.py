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

TIMEOUT_S = 3600


class HeyGenAgentRunner:
    """Headless-сессия в обычном профиле, с правом писать файлы."""

    def __init__(self, timeout_s: int | None = None):
        env_timeout = os.environ.get("RF_HF_AGENT_TIMEOUT_S", "").strip()
        self.timeout_s = int(
            timeout_s if timeout_s is not None else env_timeout or TIMEOUT_S
        )
        self.exe = shutil.which("claude") or "claude"
        self.total_cost_usd = 0.0

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
        log_path = (Path(cwd) if cwd else Path.cwd()) / "agent.log"
        try:
            result = subprocess.run(
                [self.exe, "-p", "--output-format", "json",
                 "--permission-mode", "acceptEdits"],
                input=prompt, capture_output=True, text=True, encoding="utf-8",
                timeout=self.timeout_s, env=env, cwd=str(cwd) if cwd else None,
            )
        except subprocess.TimeoutExpired as exc:
            partial_stdout = exc.output or ""
            partial_stderr = exc.stderr or ""
            log_path.write_text(
                str(partial_stdout) + "\n--- stderr ---\n" + str(partial_stderr),
                encoding="utf-8",
            )
            raise RuntimeError(
                f"агент-сборщик не уложился в {self.timeout_s} с; "
                f"частичный вывод в {log_path}"
            ) from exc
        log_path.write_text(
            (result.stdout or "") + "\n--- stderr ---\n" + (result.stderr or ""),
            encoding="utf-8",
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
