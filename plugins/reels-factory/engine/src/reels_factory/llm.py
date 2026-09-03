"""Абстракция LLM-шага. Реализация — локальный Claude Code headless (claude -p);
API-ключ не нужен. Переключение на API позже — заменой реализации LLMRunner.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol


class LLMRunner(Protocol):
    def run(self, prompt: str) -> str: ...


# Отдельный профиль Claude Code для вызовов движка: и скилл, и наш промпт
# должны работать в чистой комнате, без личных CLAUDE.md, хуков, плагинов и
# памяти разработчика.
SKILL_PROFILE_DIR = Path.home() / ".reels-factory" / "claude"

#: Годовой токен подписки для headless (`claude setup-token`), запасной вход.
#: На проде он приходит из bot.env; на машине разработчика переменной нет, и
#: без файла чистый профиль отвечает «OAuth session expired» — так же, как у
#: агента-сборщика (hf_agent.py:171).
OAUTH_TOKEN_FILE = Path.home() / ".reels-factory" / "oauth-token"


def _isolated_env(config_dir) -> dict:
    """Окружение вызова в чистой комнате, но с сохранённой подпиской.

    CLAUDE_CONFIG_DIR уводит вызов из личного профиля машины: настройки,
    история и плагины берутся оттуда (docs: settings, «To keep the
    home-directory files somewhere else, set CLAUDE_CONFIG_DIR»).
    ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN вычищаются: в print-режиме ключ
    приоритетнее подписки всегда («In non-interactive mode (-p), the key is
    always used when present», docs/en/env-vars) — вызовы молча уехали бы на
    платный API. Токен подписки живёт в CLAUDE_CODE_OAUTH_TOKEN (bot.env) и
    остаётся: он приходит окружением, а не настройками, и чистый профиль его
    не теряет.
    """
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    if not env.get("CLAUDE_CODE_OAUTH_TOKEN") and OAUTH_TOKEN_FILE.exists():
        env["CLAUDE_CODE_OAUTH_TOKEN"] = OAUTH_TOKEN_FILE.read_text(
            encoding="utf-8").strip()
    return env


#: Узнаваемые причины отказа `claude -p`. Разбирать чужие тексты ошибок в
#: общем виде не пытаемся: цель — чтобы в журнале службы было видно, что
#: чинить, а не пересказать CLI. По одному коду 1 протухший вход не отличить
#: от снятого флага, и обе поломки лечатся по-разному.
_ПРИЧИНЫ_ОТКАЗА = (
    (("oauth session expired", "failed to authenticate", "invalid api key",
      "please run /login", "credit balance"),
     "подписка не пускает: CLAUDE_CODE_OAUTH_TOKEN протух или не задан — "
     "перевыпустить `claude setup-token` и положить в bot.env"),
    (("permission allow rule", "permission deny rule", "invalid settings",
      "settings file"),
     "CLI не принял правила прав из файла настроек; наш вызов идёт с "
     'CLAUDE_CONFIG_DIR и --setting-sources "", значит настройки чужого '
     "профиля всё-таки прочитались — проверить флаги изоляции"),
    (("unknown option", "unknown or unexpected option", "error: option"),
     "этой версии CLI неизвестен флаг из нашей строки вызова — сверить с "
     "`claude --help` после обновления claude"),
)


def _объяснить_отказ(текст: str) -> str:
    низ = (текст or "").lower()
    for маркеры, причина in _ПРИЧИНЫ_ОТКАЗА:
        if any(маркер in низ for маркер in маркеры):
            return причина
    return ""


class ClaudeCliRunner:
    """`claude -p` с необязательным принуждением формы ответа.

    `json_schema` уезжает в флаг `--json-schema` (`claude --help`: "JSON Schema
    for structured output validation", только в print-режиме) — SDK сам
    валидирует ответ и переспрашивает модель при несовпадении. Так выбор из
    закрытого списка (enum жестов) держится на стороне CLI, а не на проверке
    постфактум. Схема задаётся на конструкторе, а не в `run`, чтобы подпись
    `LLMRunner.run` осталась прежней и тестовые фейки не переписывались.

    Изоляция — та же чистая комната, что у ClaudeSkillRunner, и по той же
    причине: 22.08 на проде вызов падал кодом 1 на любом промпте, потому что в
    общем профиле машины лежало правило `Write(//root/ward/**)` от чужого
    проекта, а свежий CLI требует `Edit(...)`. Через этот раннер идут сценарий,
    визуальный директор и жесты — чужая настройка роняла любую сборку.
    """

    def __init__(self, timeout_s: int = 600, extra_args: list | None = None,
                 json_schema: dict | None = None, config_dir=None):
        self.timeout_s = timeout_s
        self.extra_args = list(extra_args or [])
        self.json_schema = json_schema
        self.config_dir = Path(config_dir) if config_dir else SKILL_PROFILE_DIR
        self.exe = shutil.which("claude") or "claude"

    def run(self, prompt: str) -> str:
        args = [self.exe, "-p", "--output-format", "text"]
        if self.json_schema is not None:
            args += [
                "--json-schema",
                json.dumps(self.json_schema, ensure_ascii=False),
            ]
        args += [
            # Инструментов не даём ни одного: наши три вызова шлют промпт и
            # читают текст обратно, файлов не трогают. `--tools` — именно про
            # доступный набор, а не про разрешения («Restrict which built-in
            # tools Claude can use. Use "" to disable all»,
            # code.claude.com/docs/en/cli-reference); `--allowedTools` из
            # ClaudeSkillRunner решает другую задачу — что пускать без
            # вопроса. Проверено вживую 22.08 на claude 2.1.231: `--tools ""`
            # уживается с `--json-schema`, ответ приходит по схеме.
            # Исключение одно и оно мёртвое: broll_index.make_llm_describer
            # кладёт в промпт пути к кадрам и ждёт, что модель их прочитает —
            # вызывающего кода у него нет, а появится, ему нужен будет Read.
            "--tools", "",
            # Ни user, ни project, ни local настроек: ни CLAUDE.md, ни хуков,
            # ни чужих плагинов, ни правил прав из общего профиля.
            "--setting-sources", "",
            # Ноль MCP-серверов (своего --mcp-config мы не передаём).
            "--strict-mcp-config",
        ]
        self.config_dir.mkdir(parents=True, exist_ok=True)
        p = subprocess.run(
            [*args, *self.extra_args],
            input=prompt, capture_output=True, text=True, encoding="utf-8",
            timeout=self.timeout_s, env=_isolated_env(self.config_dir),
        )
        if p.returncode != 0:
            # Ошибки входа CLI печатает в stdout, а не в stderr — берём оба
            # потока, иначе в журнале остаётся пустая строка.
            err = (p.stderr or "").strip() or (p.stdout or "").strip()
            причина = _объяснить_отказ(err)
            raise RuntimeError(
                f"claude -p failed (code {p.returncode})"
                + (f" — {причина}" if причина else "")
                + f": {err[:500]}"
            )
        return p.stdout


class FakeRunner:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def run(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


class SkillRunner(Protocol):
    def run_skill(self, skill: str, payload_path,
                  json_schema: dict | None = None) -> str: ...


#: Права скилла: только чтение. Скиллы сценария держат свои правила в
#: справочниках рядом с SKILL.md и читают их по ходу; в чистой комнате
#: разрешений нет ни одного, и первый же `Read` возвращает «нужно
#: подтверждение» — сессия отвечает этой фразой вместо JSON, и путь «из сырья»
#: встаёт целиком. Писать им нечего: ответ уходит текстом.
SKILL_TOOLS = ("Read", "Glob", "Grep")


class ClaudeSkillRunner:
    """Вызов скилла плагина: claude -p "/reels-factory:<skill> <payload>".

    Скилл разворачивается в промпт детерминированно (headless-механизм
    Claude Code); --plugin-dir гарантирует загрузку локального плагина.

    Изоляция: свой CLAUDE_CONFIG_DIR + --setting-sources "" (ни user, ни
    project, ни local настроек) + --strict-mcp-config (ноль MCP) + выключенная
    авто-память. ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN вычищаются: они
    приоритетнее подписки и молча перевели бы вызовы на платный API.

    Формат ответа — json, а не text: только так CLI сообщает стоимость вызова,
    без которой Клода нечем учитывать в себестоимости рилса. Наружу отдаётся
    поле result, поэтому вызывающий код не меняется.
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
        self.last_cost_usd: float | None = None
        # Один runner обслуживает несколько скиллов подряд (генерация,
        # хуманизатор, судья), поэтому нужна и сумма: по last_cost_usd
        # видно только последний вызов, и остальные потерялись бы.
        self.total_cost_usd: float = 0.0
        # Под подпиской CLI присылает нулевую стоимость, и единственный честный
        # счёт остаётся по токенам (`claude_run_cost_usd` в billing.py) —
        # поэтому храним `usage` каждого вызова, а не только сумму.
        self.runs: list[dict] = []

    def _env(self) -> dict:
        # Метод остаётся: на него опирается _PromptRunner в bot.py.
        return _isolated_env(self.config_dir)

    @staticmethod
    def _extract_json(stdout: str) -> dict:
        """Последний JSON-объект из потока.

        Подпроцессы (node и прочие) пишут в тот же stdout, поэтому просто
        json.loads(stdout) ненадёжен.
        """
        text = (stdout or "").strip()
        for start in range(len(text)):
            if text[start] != "{":
                continue
            try:
                obj = json.loads(text[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
        raise RuntimeError(f"claude -p вернул не JSON: {text[:300]}")

    def run_skill(self, skill: str, payload_path,
                  json_schema: dict | None = None) -> str:
        prompt = f"/reels-factory:{skill} {payload_path}"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.exe, "-p", "--output-format", "json",
            "--plugin-dir", self.plugin_dir,
            "--allowedTools", *SKILL_TOOLS,
            # `--allowedTools` только снимает вопрос разрешения на эти три
            # инструмента — набор, который модель ВИДИТ, этим не сужается
            # (code.claude.com/docs/en/cli-reference, «--allowedTools»: «To
            # restrict which tools are available, use --tools instead»).
            # Без `--tools` модель видит и WebFetch: материал со ссылкой
            # заставлял её пытаться открыть URL, получать отказ и отвечать
            # просьбой о доступе вместо JSON — 5 факапов у 4 людей 2-3
            # сентября. `claude --help`: `--tools <tools...>` принимает
            # список одним аргументом через запятую («Bash,Edit,Read»).
            "--tools", ",".join(SKILL_TOOLS),
            "--setting-sources", "", "--strict-mcp-config",
        ]
        if json_schema is not None:
            cmd += ["--json-schema", json.dumps(json_schema, ensure_ascii=False)]
        p = subprocess.run(
            cmd,
            input=prompt, capture_output=True, text=True, encoding="utf-8",
            timeout=self.timeout_s, env=self._env(),
        )
        if p.returncode != 0:
            # ошибки входа CLI печатает в stdout, поэтому берём оба потока
            err = (p.stderr or "").strip() or (p.stdout or "").strip()
            raise RuntimeError(
                f"claude -p /{skill} failed (code {p.returncode}): {err[:500]}")
        obj = self._extract_json(p.stdout)
        cost = obj.get("total_cost_usd")
        self.last_cost_usd = float(cost) if cost is not None else None
        if self.last_cost_usd:
            self.total_cost_usd += self.last_cost_usd
        self.runs.append({
            "skill": skill,
            "cost_usd": cost,
            "usage": obj.get("usage"),
            # Модель называет сам ответ: скиллы зовутся без `--model`, поэтому
            # тут может стоять и None — тогда счёт идёт по ставке модели по
            # умолчанию (`claude_default_model`).
            "model": obj.get("model"),
        })
        # Свою ошибку (протухший вход, упёршийся лимит ходов, отказ) CLI кладёт
        # в то же поле result и не всегда меняет код возврата. Без этой проверки
        # текст ошибки уезжает дальше как ответ скилла, и вызывающий код
        # жалуется на «bad json» вместо настоящей причины.
        if obj.get("is_error"):
            denials = obj.get("permission_denials") or []
            raise RuntimeError(
                f"claude -p /{skill} вернул ошибку ({obj.get('subtype')}): "
                f"{str(obj.get('result') or '')[:500]}"
                + (f" отказано инструментам: {denials}" if denials else "")
            )
        if json_schema is not None:
            # docs/en/agent-sdk/structured-outputs, «Error handling»: success
            # без structured_output бывает и без сбоя валидации (например,
            # модель ничего не произвела) — «Treat that case as a failure as
            # well». RuntimeError уходит в тот же повтор `_skill_json`
            # (scenario.py), что и прочие сбои этого вызова.
            structured = obj.get("structured_output")
            if structured is None:
                raise RuntimeError(
                    f"claude -p /{skill}: success без structured_output "
                    f"(--json-schema задан): {str(obj)[:300]}")
            return json.dumps(structured, ensure_ascii=False)
        if "result" not in obj:
            raise RuntimeError(
                f"claude -p /{skill}: ответ без поля result: {str(obj)[:300]}")
        return obj["result"]


class FakeSkillRunner:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def run_skill(self, skill: str, payload_path,
                  json_schema: dict | None = None) -> str:
        self.calls.append((skill, payload_path))
        return self.replies.pop(0)
