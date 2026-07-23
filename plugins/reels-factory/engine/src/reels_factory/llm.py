"""Абстракция LLM-шага. Реализация — локальный Claude Code headless (claude -p);
API-ключ не нужен. Переключение на API позже — заменой реализации LLMRunner.
"""
import shutil
import subprocess
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


class ClaudeSkillRunner:
    """Вызов скилла плагина: claude -p "/reels-factory:<skill> <payload>".

    Скилл разворачивается в промпт детерминированно (headless-механизм
    Claude Code); --plugin-dir гарантирует загрузку локального плагина.
    """

    def __init__(self, plugin_dir=None, timeout_s: int = 600):
        from reels_factory.config import PLUGIN_DIR
        if plugin_dir is not None:
            # Preserve path format: use as_posix() for Path objects to avoid Windows backslash conversion
            self.plugin_dir = plugin_dir.as_posix() if hasattr(plugin_dir, 'as_posix') else str(plugin_dir)
        else:
            self.plugin_dir = str(PLUGIN_DIR)
        self.timeout_s = timeout_s
        self.exe = shutil.which("claude") or "claude"

    def run_skill(self, skill: str, payload_path) -> str:
        prompt = f"/reels-factory:{skill} {payload_path}"
        p = subprocess.run(
            [self.exe, "-p", "--output-format", "text",
             "--plugin-dir", self.plugin_dir],
            input=prompt, capture_output=True, text=True, encoding="utf-8",
            timeout=self.timeout_s,
        )
        if p.returncode != 0:
            raise RuntimeError(
                f"claude -p /{skill} failed (code {p.returncode}): {p.stderr[:500]}")
        return p.stdout


class FakeSkillRunner:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def run_skill(self, skill: str, payload_path) -> str:
        self.calls.append((skill, payload_path))
        return self.replies.pop(0)
