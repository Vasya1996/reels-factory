"""Абстракция LLM-шага. Реализация — локальный Claude Code headless (claude -p);
API-ключ не нужен. Переключение на API позже — заменой реализации LLMRunner.
"""
import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol


class LLMRunner(Protocol):
    def run(self, prompt: str) -> str: ...


class ClaudeCliRunner:
    def __init__(self, timeout_s: int = 600, extra_args: list | None = None):
        self.timeout_s = timeout_s
        self.extra_args = list(extra_args or [])
        self.exe = shutil.which("claude") or "claude"

    def run(self, prompt: str) -> str:
        p = subprocess.run(
            [self.exe, "-p", "--output-format", "text", *self.extra_args],
            input=prompt, capture_output=True, text=True, encoding="utf-8",
            timeout=self.timeout_s,
        )
        if p.returncode != 0:
            raise RuntimeError(f"claude -p failed (code {p.returncode}): {p.stderr[:500]}")
        return p.stdout


class FakeRunner:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def run(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


class SkillRunner(Protocol):
    def run_skill(self, skill: str, payload_path) -> str: ...


# Отдельный профиль Claude Code для вызовов движка: скилл должен работать в
# чистой комнате, без личных CLAUDE.md, хуков, плагинов и памяти разработчика.
SKILL_PROFILE_DIR = Path.home() / ".reels-factory" / "claude"


class ClaudeSkillRunner:
    """Вызов скилла плагина: claude -p "/reels-factory:<skill> <payload>".

    Скилл разворачивается в промпт детерминированно (headless-механизм
    Claude Code); --plugin-dir гарантирует загрузку локального плагина.

    Изоляция: свой CLAUDE_CONFIG_DIR + --setting-sources "" (ни user, ни
    project, ни local настроек) + --strict-mcp-config (ноль MCP) + выключенная
    авто-память. ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN вычищаются: они
    приоритетнее подписки и молча перевели бы вызовы на платный API.
    """

    def __init__(self, plugin_dir=None, timeout_s: int = 600, config_dir=None):
        from reels_factory.config import PLUGIN_DIR
        if plugin_dir is not None:
            # Preserve path format: use as_posix() for Path objects to avoid Windows backslash conversion
            self.plugin_dir = plugin_dir.as_posix() if hasattr(plugin_dir, 'as_posix') else str(plugin_dir)
        else:
            self.plugin_dir = str(PLUGIN_DIR)
        self.config_dir = Path(config_dir) if config_dir else SKILL_PROFILE_DIR
        self.timeout_s = timeout_s
        self.exe = shutil.which("claude") or "claude"

    def _env(self) -> dict:
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env["CLAUDE_CONFIG_DIR"] = str(self.config_dir)
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        return env

    def run_skill(self, skill: str, payload_path) -> str:
        prompt = f"/reels-factory:{skill} {payload_path}"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        p = subprocess.run(
            [self.exe, "-p", "--output-format", "text",
             "--plugin-dir", self.plugin_dir,
             "--setting-sources", "", "--strict-mcp-config"],
            input=prompt, capture_output=True, text=True, encoding="utf-8",
            timeout=self.timeout_s, env=self._env(),
        )
        if p.returncode != 0:
            # ошибки входа CLI печатает в stdout, поэтому берём оба потока
            err = (p.stderr or "").strip() or (p.stdout or "").strip()
            raise RuntimeError(
                f"claude -p /{skill} failed (code {p.returncode}): {err[:500]}")
        return p.stdout


class FakeSkillRunner:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def run_skill(self, skill: str, payload_path) -> str:
        self.calls.append((skill, payload_path))
        return self.replies.pop(0)
