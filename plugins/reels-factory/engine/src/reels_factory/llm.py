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
