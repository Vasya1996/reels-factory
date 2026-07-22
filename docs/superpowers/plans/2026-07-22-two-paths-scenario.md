# Two Paths Scenario Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Два пути создания сценария рилса — «дословно» (текст пользователя без правок + фонетика) и «из сырья» (идеи → генерация → хуманизация → судья) — с языками ru/kk.

**Architecture:** Диалоговые шаги — в чат-скиллах плагина; повторяемые LLM-шаги — скиллы с `disable-model-invocation: true`, вызываемые движком через `claude -p "/reels-factory:<имя> <путь-к-заданию>"`. Задание пишется файлом в workdir. Код движка проверяет только целостность; качество — LLM-судья по бинарной рубрике с авторетраями.

**Tech Stack:** Python 3.11+ (engine, pytest), Claude Code skills (markdown), faster-whisper, ElevenLabs (существующее).

**Спецификация:** `docs/superpowers/specs/2026-07-21-two-paths-scenario-design.md`

## Global Constraints

- Ветка `feat/vasya-two-paths-scenario`; PR только после «ок» пользователя.
- НЕ трогать: `ingest.py`, `compose.py`, `render.py`, `captions.py` (зона Юли).
- CLI-команда `script` в движке остаётся как есть (не ломаем код), но из пользовательского чат-скилла research-цикл УБИРАЕТСЯ: пользователю доступны ровно два пути.
- Пользователь НИКОГДА не вводит команды сам: после выбора пути и передачи текста/сырья все CLI-команды выполняет Клод (чат-скилл) автоматически в нужном порядке.
- Тесты: `python -m pytest` из `plugins/reels-factory/engine`, LLM всегда подменяется фейками.
- Текст пользователя в пути 1 не меняется ни на букву (кроме фонетики LLM-шагом).
- Никаких платных вызовов в тестах и скиллах без явного «ок» пользователя.
- Все пути в скиллах — прямые слэши; тела SKILL.md < 500 строк.
- Версии в `plugin.json`/`pyproject.toml`/`marketplace.json` НЕ бампать (только релизы).

**Все пути файлов ниже — от корня репозитория.** Движковые файлы:
`plugins/reels-factory/engine/src/reels_factory/`, тесты
`plugins/reels-factory/engine/tests/`, скиллы `plugins/reels-factory/skills/`.

---

### Task 1: Конфиг — cta_phrase опционален, новые поля language и heygen_price_per_s

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/config.py:83-89`
- Test: `plugins/reels-factory/engine/tests/test_config.py` (создать)

**Interfaces:**
- Produces: `load_config()` больше не требует `product.cta_phrase`; возвращает опциональные `cfg["language"]` (по умолчанию "ru") и `cfg["heygen_price_per_s"]` (None если нет).

- [ ] **Step 1: Write the failing tests**

`plugins/reels-factory/engine/tests/test_config.py`:

```python
import pytest
import yaml
from reels_factory.config import load_config, ConfigError


def _write_cfg(tmp_path, cfg):
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return p


BASE = {
    "theme": "тема",
    "format": "fullscreen",
    "voice_id": "v1",
    "persona": {"description": "эксперт"},
    "product": {"name": "Продукт"},
}


def test_cta_phrase_optional(tmp_path):
    p = _write_cfg(tmp_path, BASE)
    cfg = load_config(p)  # не должно бросить ConfigError
    assert cfg["product"]["name"] == "Продукт"


def test_language_default_ru(tmp_path):
    p = _write_cfg(tmp_path, BASE)
    cfg = load_config(p)
    assert cfg["language"] == "ru"


def test_language_kk_passthrough(tmp_path):
    p = _write_cfg(tmp_path, {**BASE, "language": "kk"})
    cfg = load_config(p)
    assert cfg["language"] == "kk"


def test_language_invalid_rejected(tmp_path):
    p = _write_cfg(tmp_path, {**BASE, "language": "en-US-x"})
    with pytest.raises(ConfigError):
        load_config(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run (из `plugins/reels-factory/engine`): `python -m pytest tests/test_config.py -v`
Expected: FAIL — `test_cta_phrase_optional` падает с ConfigError про cta_phrase, `test_language_*` падают на KeyError/отсутствии валидации.

- [ ] **Step 3: Implement**

В `config.py` заменить блок проверки product (строки 83-89):

```python
    product = cfg.get("product") or {}
    if not str(product.get("name") or "").strip():
        raise ConfigError("Поле product.name (имя продукта) обязательно в config.yaml.")
    # cta_phrase опционален: CTA в пути генерации пишется под каждый ролик,
    # в пути «дословно» не добавляется вовсе (см. spec 2026-07-21).

    lang = str(cfg.get("language") or "ru").strip().lower()
    if not (len(lang) == 2 and lang.isalpha()):
        raise ConfigError(
            f"Поле language должно быть двухбуквенным кодом языка ('ru', 'kk'), сейчас: {cfg.get('language')!r}."
        )
    cfg["language"] = lang
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_config.py -v` → PASS.
Run: `python -m pytest` → все существующие тесты тоже PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/reels-factory/engine/src/reels_factory/config.py plugins/reels-factory/engine/tests/test_config.py
git commit -m "feat(config): cta_phrase опционален, поле language (ru/kk)"
```

---

### Task 2: scenario.py — дословная разбивка и валидатор целостности

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/scenario.py` (добавить функции в конец файла; существующие не трогать)
- Test: `plugins/reels-factory/engine/tests/test_scenario.py` (создать)

**Interfaces:**
- Produces:
  - `split_verbatim(text: str) -> list[dict]` — блоки `{"role","start","end","speech"}`, роли из `ROLES_4` по порядку (меньше 4 предложений → меньше блоков, роли с начала списка); конкатенация `speech` == исходный текст с точностью до схлопывания пробелов.
  - `scenario_from_text(workdir: Path, text: str) -> dict` — пишет `<workdir>/scenario.json` вида `{"mode": "verbatim", "blocks": [...]}` и возвращает его.
  - `validate_integrity(sc: dict) -> list[str]` — только механика: blocks — непустой список, у каждого блока непустой `speech`, числовые `start`/`end`, `start` каждого == `end` предыдущего.
  - `WORDS_PER_SEC = 2.5` — константа оценки таймингов.

- [ ] **Step 1: Write the failing tests**

`plugins/reels-factory/engine/tests/test_scenario.py`:

```python
import json
import re
from reels_factory.scenario import (
    split_verbatim, scenario_from_text, validate_integrity, ROLES_4,
)


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


TEXT = ("Мы запустили продукт в марте. Первый месяц не было ни одной продажи. "
        "Потом мы поменяли оффер. Продажи пошли на третий день. "
        "Сейчас у нас двадцать клиентов.")


def test_split_preserves_text_verbatim():
    blocks = split_verbatim(TEXT)
    joined = " ".join(b["speech"] for b in blocks)
    assert _norm(joined) == _norm(TEXT)


def test_split_roles_and_order():
    blocks = split_verbatim(TEXT)
    assert 1 <= len(blocks) <= 4
    assert [b["role"] for b in blocks] == ROLES_4[:len(blocks)]


def test_split_timings_monotonic():
    blocks = split_verbatim(TEXT)
    assert blocks[0]["start"] == 0.0
    for prev, cur in zip(blocks, blocks[1:]):
        assert cur["start"] == prev["end"]
        assert cur["end"] > cur["start"]


def test_split_short_text_single_block():
    blocks = split_verbatim("Одна фраза.")
    assert len(blocks) == 1
    assert blocks[0]["speech"] == "Одна фраза."


def test_scenario_from_text_writes_file(tmp_path):
    sc = scenario_from_text(tmp_path, TEXT)
    on_disk = json.loads((tmp_path / "scenario.json").read_text(encoding="utf-8"))
    assert on_disk == sc
    assert sc["mode"] == "verbatim"
    assert validate_integrity(sc) == []


def test_validate_integrity_catches_empty_speech():
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 2.0, "speech": ""}]}
    errs = validate_integrity(sc)
    assert any("speech" in e for e in errs)


def test_validate_integrity_catches_gap():
    sc = {"blocks": [
        {"role": "hook", "start": 0.0, "end": 2.0, "speech": "а"},
        {"role": "development", "start": 3.0, "end": 5.0, "speech": "б"},
    ]}
    assert validate_integrity(sc) != []


def test_validate_integrity_no_quality_rules():
    # 200 слов, нет CTA, латиница — целостность ДОЛЖНА пройти (качество не её дело)
    long_speech = "слово " * 200 + "Microsoft"
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 80.0, "speech": long_speech}]}
    assert validate_integrity(sc) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scenario.py -v`
Expected: FAIL с `ImportError: cannot import name 'split_verbatim'`.

- [ ] **Step 3: Implement**

Добавить в конец `scenario.py`:

```python
# ---------------------------------------------------------------------------
# Путь «дословно»: текст пользователя без правок (spec 2026-07-21).
# Блоки — только формат передачи сборке/Юле: границы по предложениям,
# роли позиционные, тайминги — черновая оценка по счёту слов.

WORDS_PER_SEC = 2.5

_SENT_RE = re.compile(r"(?<=[.!?…])\s+")


def split_verbatim(text: str) -> list[dict]:
    text = str(text or "").strip()
    if not text:
        raise ScenarioError("пустой текст")
    sents = [s for s in _SENT_RE.split(text) if s.strip()]
    n_blocks = min(4, len(sents))
    total_words = sum(len(s.split()) for s in sents)
    target = total_words / n_blocks

    groups, cur, cur_words = [], [], 0
    for s in sents:
        cur.append(s)
        cur_words += len(s.split())
        if cur_words >= target and len(groups) < n_blocks - 1:
            groups.append(" ".join(cur))
            cur, cur_words = [], 0
    if cur:
        groups.append(" ".join(cur))

    blocks, t = [], 0.0
    for role, chunk in zip(ROLES_4, groups):
        dur = round(len(chunk.split()) / WORDS_PER_SEC, 1)
        blocks.append({"role": role, "start": round(t, 1),
                       "end": round(t + dur, 1), "speech": chunk})
        t += dur
    return blocks


def scenario_from_text(workdir: Path, text: str) -> dict:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    sc = {"mode": "verbatim", "blocks": split_verbatim(text)}
    (workdir / "scenario.json").write_text(
        json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
    return sc


def validate_integrity(sc: dict) -> list[str]:
    """Только механика (файл годен для сборки). Качество — судья, не код."""
    errs = []
    blocks = sc.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return ["blocks: отсутствует или пуст"]
    prev_end = None
    for i, b in enumerate(blocks):
        if not isinstance(b, dict):
            errs.append(f"блок {i}: не объект")
            continue
        if not str(b.get("speech") or "").strip():
            errs.append(f"блок {i} ({b.get('role')}): пустой speech")
        start, end = b.get("start"), b.get("end")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in (start, end)):
            errs.append(f"блок {i}: start/end не числа")
            continue
        if prev_end is not None and start != prev_end:
            errs.append(f"блок {i}: start ({start}) != end предыдущего ({prev_end})")
        prev_end = end
    return errs
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_scenario.py -v` → PASS. `python -m pytest` → PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/reels-factory/engine/src/reels_factory/scenario.py plugins/reels-factory/engine/tests/test_scenario.py
git commit -m "feat(scenario): дословная разбивка split_verbatim + validate_integrity"
```

---

### Task 3: Баг `_mentions_theme` — латинская тема валит сценарий

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/scenario.py:53-72` (`_mentions_theme`)
- Test: `plugins/reels-factory/engine/tests/test_scenario.py` (дополнить)
- Delete: `C:/Users/123/.claude/projects/reels-factory/memory/bug-theme-spoken-validation.md` + строка в `MEMORY.md` (после зелёных тестов)

**Interfaces:**
- Consumes: `_mentions_theme(text, *candidates)` — приватная, используется в `validate_scenario` (старый путь, продолжает работать).
- Produces: то же имя/сигнатура; новое поведение: кандидат в другом алфавите, чем текст, не может провалить проверку в одиночку.

- [ ] **Step 1: Write the failing test**

Дописать в `tests/test_scenario.py`:

```python
from reels_factory.scenario import _mentions_theme


def test_mentions_theme_latin_theme_cyrillic_text():
    # Баг: тема "Vael" при русском тексте валила сценарий,
    # хотя theme_spoken («ваэль») в тексте есть.
    assert _mentions_theme("расскажу про ваэль и её фишки", "Vael", "ваэль") is True


def test_mentions_theme_skips_incomparable_alphabet():
    # Латинский кандидат без кириллического дубля не должен давать False,
    # если в тексте вообще нет латиницы — алфавиты несопоставимы.
    assert _mentions_theme("текст только кириллицей", "Vael") is True


def test_mentions_theme_still_fails_when_absent():
    assert _mentions_theme("текст про другое", "маркетинг", "маркетинга") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scenario.py -k mentions_theme -v`
Expected: `test_mentions_theme_skips_incomparable_alphabet` FAIL (сейчас вернёт False).
(`..._latin_theme_cyrillic_text` может проходить за счёт «ваэль» — это нормально.)

- [ ] **Step 3: Implement**

Заменить тело цикла в `_mentions_theme`:

```python
def _mentions_theme(text: str, *candidates) -> bool:
    low = (text or "").lower()
    text_has_cyr = bool(re.search(r"[а-яё]", low))
    comparable = 0
    for g in candidates:
        g = str(g or "").strip()
        if not g:
            continue
        words = _WORD_RE.findall(g)
        if not words:
            continue
        longest = max(words, key=len).lower()
        # кандидат в алфавите, которого нет в тексте, — несопоставим:
        # не считаем его провалом (баг: латинская тема при русском тексте)
        cand_is_cyr = bool(re.search(r"[а-яё]", longest))
        if cand_is_cyr != text_has_cyr and not re.search(
                r"[a-z]" if not cand_is_cyr else r"[а-яё]", low):
            continue
        comparable += 1
        root = _theme_root(longest)
        if len(root) >= 2 and root in low:
            return True
    return comparable == 0  # нечего было проверять — не валим
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_scenario.py -v` → PASS. `python -m pytest` → PASS.

- [ ] **Step 5: Удалить заметку из памяти**

Удалить файл `C:/Users/123/.claude/projects/reels-factory/memory/bug-theme-spoken-validation.md` и его строку из `C:/Users/123/.claude/projects/reels-factory/memory/MEMORY.md` (заметка сама требует удаления после фикса).

- [ ] **Step 6: Commit**

```bash
git add plugins/reels-factory/engine/src/reels_factory/scenario.py plugins/reels-factory/engine/tests/test_scenario.py
git commit -m "fix(scenario): _mentions_theme не валит сценарий при теме в другом алфавите"
```

---

### Task 4: llm.py — SkillRunner (вызов скиллов плагина через claude -p)

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/llm.py` (добавить в конец)
- Modify: `plugins/reels-factory/engine/src/reels_factory/config.py` (константа PLUGIN_DIR)
- Test: `plugins/reels-factory/engine/tests/test_llm.py` (дополнить)

**Interfaces:**
- Produces:
  - `config.PLUGIN_DIR: Path` — корень плагина (`.../plugins/reels-factory`), вычислен от `__file__` движка.
  - `SkillRunner` (Protocol): `run_skill(self, skill: str, payload_path: Path) -> str`.
  - `ClaudeSkillRunner(plugin_dir: Path | None = None, timeout_s: int = 600)` — строит промпт `/reels-factory:<skill> <payload_path>` и зовёт `claude -p ... --plugin-dir <dir>`.
  - `FakeSkillRunner(replies: list[str])` — как `FakeRunner`, пишет `(skill, payload_path)` в `self.calls`.

- [ ] **Step 1: Write the failing tests**

Дописать в `tests/test_llm.py`:

```python
import json
from pathlib import Path
from reels_factory.llm import ClaudeSkillRunner, FakeSkillRunner


def test_claude_skill_runner_builds_command(monkeypatch, tmp_path):
    captured = {}

    class P:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["input"] = kw.get("input")
        return P()

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)
    payload = tmp_path / "task.json"
    payload.write_text("{}", encoding="utf-8")

    r = ClaudeSkillRunner(plugin_dir=Path("C:/plug/reels-factory"))
    out = r.run_skill("humanizing-speech", payload)

    assert out == '{"ok": true}'
    assert "--plugin-dir" in captured["cmd"]
    i = captured["cmd"].index("--plugin-dir")
    assert captured["cmd"][i + 1] == "C:/plug/reels-factory"
    assert captured["input"].startswith("/reels-factory:humanizing-speech ")
    assert str(payload).replace("\\", "/") in captured["input"].replace("\\", "/")


def test_fake_skill_runner_records_calls(tmp_path):
    f = FakeSkillRunner(['{"a": 1}'])
    out = f.run_skill("judging-script", tmp_path / "x.json")
    assert json.loads(out) == {"a": 1}
    assert f.calls == [("judging-script", tmp_path / "x.json")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_llm.py -v`
Expected: FAIL — ImportError `ClaudeSkillRunner`.

- [ ] **Step 3: Implement**

В `config.py` после `CONFIG_PATH` добавить:

```python
# Корень плагина (skills/, .claude-plugin/) — для вызова скиллов движком
# через `claude -p --plugin-dir`. engine/src/reels_factory/ -> вверх 3 уровня.
PLUGIN_DIR = Path(__file__).resolve().parents[3]
```

В `llm.py` добавить:

```python
class SkillRunner(Protocol):
    def run_skill(self, skill: str, payload_path) -> str: ...


class ClaudeSkillRunner:
    """Вызов скилла плагина: claude -p "/reels-factory:<skill> <payload>".

    Скилл разворачивается в промпт детерминированно (headless-механизм
    Claude Code); --plugin-dir гарантирует загрузку локального плагина.
    """

    def __init__(self, plugin_dir=None, timeout_s: int = 600):
        from reels_factory.config import PLUGIN_DIR
        self.plugin_dir = str(plugin_dir or PLUGIN_DIR)
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
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_llm.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/reels-factory/engine/src/reels_factory/llm.py plugins/reels-factory/engine/src/reels_factory/config.py plugins/reels-factory/engine/tests/test_llm.py
git commit -m "feat(llm): SkillRunner — вызов скиллов плагина через claude -p"
```

---

### Task 5: Скилл humanizing-speech + модуль humanize.py (режимы polish/phonetics)

**Files:**
- Create: `plugins/reels-factory/skills/humanizing-speech/SKILL.md`
- Create: `plugins/reels-factory/skills/humanizing-speech/references/speech-bans-ru.md`
- Create: `plugins/reels-factory/skills/humanizing-speech/evals/evals.json`
- Create: `plugins/reels-factory/engine/src/reels_factory/humanize.py`
- Test: `plugins/reels-factory/engine/tests/test_humanize.py` (создать)

**Interfaces:**
- Consumes: `SkillRunner.run_skill` (Task 4), `_extract_json` из `scenario.py`.
- Produces:
  - `humanize.humanize_scenario(runner, workdir: Path, sc: dict, mode: str, language: str) -> dict` — `mode` in `("polish", "phonetics")`; пишет `<workdir>/humanize_task.json`, зовёт скилл `humanizing-speech`, возвращает сценарий с обновлёнными `speech` (роли/количество блоков обязаны совпасть, иначе `HumanizeError`).
  - `humanize.HumanizeError(Exception)`.
- Контракт скилла: вход — путь к JSON `{"mode","language","blocks":[{"role","speech"}]}`; выход — ТОЛЬКО JSON `{"blocks":[{"role","speech"}]}`.

- [ ] **Step 1: Write the failing tests**

`plugins/reels-factory/engine/tests/test_humanize.py`:

```python
import json
import pytest
from reels_factory.llm import FakeSkillRunner
from reels_factory.humanize import humanize_scenario, HumanizeError

SC = {"mode": "verbatim", "blocks": [
    {"role": "hook", "start": 0.0, "end": 2.0, "speech": "Мы внедрили Microsoft CRM."},
    {"role": "development", "start": 2.0, "end": 5.0, "speech": "Продажи выросли."},
]}


def test_humanize_writes_task_and_applies_reply(tmp_path):
    reply = json.dumps({"blocks": [
        {"role": "hook", "speech": "Мы внедрили Майкрософт Си-Ар-Эм."},
        {"role": "development", "speech": "Продажи выросли."},
    ]}, ensure_ascii=False)
    runner = FakeSkillRunner([reply])

    out = humanize_scenario(runner, tmp_path, SC, mode="phonetics", language="ru")

    assert out["blocks"][0]["speech"] == "Мы внедрили Майкрософт Си-Ар-Эм."
    assert out["blocks"][0]["start"] == 0.0  # тайминги сохранены
    skill, payload_path = runner.calls[0]
    assert skill == "humanizing-speech"
    task = json.loads(payload_path.read_text(encoding="utf-8"))
    assert task["mode"] == "phonetics"
    assert task["language"] == "ru"
    assert [b["role"] for b in task["blocks"]] == ["hook", "development"]


def test_humanize_rejects_block_mismatch(tmp_path):
    reply = json.dumps({"blocks": [{"role": "hook", "speech": "х"}]})
    runner = FakeSkillRunner([reply])
    with pytest.raises(HumanizeError):
        humanize_scenario(runner, tmp_path, SC, mode="polish", language="ru")


def test_humanize_rejects_bad_mode(tmp_path):
    with pytest.raises(HumanizeError):
        humanize_scenario(FakeSkillRunner([]), tmp_path, SC, mode="x", language="ru")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_humanize.py -v` → FAIL (нет модуля humanize).

- [ ] **Step 3: Implement humanize.py**

`plugins/reels-factory/engine/src/reels_factory/humanize.py`:

```python
"""Хуманизация сценария: вызов скилла humanizing-speech через SkillRunner.

Режимы (выбираются путём, не пользователем): polish — переписать под живую
устную речь (факты неприкосновенны); phonetics — только фонетическая запись
терминов/брендов и числа прописью, больше ничего (путь «дословно»).
"""
import json
from pathlib import Path

from reels_factory.scenario import _extract_json, ScenarioError

MODES = ("polish", "phonetics")


class HumanizeError(Exception):
    pass


def humanize_scenario(runner, workdir, sc: dict, mode: str, language: str) -> dict:
    if mode not in MODES:
        raise HumanizeError(f"неизвестный режим {mode!r}, ожидается {MODES}")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    task = {
        "mode": mode,
        "language": language,
        "blocks": [{"role": b["role"], "speech": b["speech"]} for b in sc["blocks"]],
    }
    payload = workdir / "humanize_task.json"
    payload.write_text(json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8")

    reply = runner.run_skill("humanizing-speech", payload)
    try:
        data = _extract_json(reply)
    except ScenarioError as e:
        raise HumanizeError(str(e)) from e

    new_blocks = data.get("blocks")
    if (not isinstance(new_blocks, list)
            or [b.get("role") for b in new_blocks] != [b["role"] for b in sc["blocks"]]):
        raise HumanizeError(
            f"скилл вернул блоки с другими ролями/количеством: {new_blocks!r}")

    out = {**sc, "blocks": [dict(orig, speech=str(nb.get("speech") or orig["speech"]))
                            for orig, nb in zip(sc["blocks"], new_blocks)]}
    return out
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_humanize.py -v` → PASS.

- [ ] **Step 5: Create the skill**

`plugins/reels-factory/skills/humanizing-speech/SKILL.md`:

````markdown
---
name: humanizing-speech
description: Rewrites reel scenario speech into natural spoken Russian/Kazakh for TTS voiceover, or (phonetics mode) only transliterates brands/terms and spells out numbers. Engine-invoked with a path to a JSON task file. Not for chat use.
disable-model-invocation: true
---

# Humanizing Speech

Ты — редактор устной речи. Аргумент вызова — путь к JSON-файлу задания.

## Шаги

1. Прочитай файл задания (путь в аргументе):
   `{"mode": "polish"|"phonetics", "language": "ru"|"kk", "blocks": [{"role", "speech"}]}`.
2. Прочитай справочник `references/speech-bans-ru.md` (для kk применяй те же
   принципы: канцелярит, кальки, артефакты чатбота).
3. Обработай каждый блок по режиму (ниже).
4. Самоаудит: пройди свой результат по справочнику пункт за пунктом, найди
   нарушения, исправь.
5. Ответь ТОЛЬКО JSON без пояснений и без markdown-ограждений:
   `{"blocks": [{"role": "...", "speech": "..."}]}` — роли и количество блоков
   ровно как во входе.

## Режим polish

Перепиши speech под живую устную речь на языке задания:
- короткие фразы (до ~12 слов), одна мысль на фразу;
- без сложносочинённых, причастных и деепричастных цепочек;
- ФАКТ-ЗАМОК: числа, имена, факты, порядок мыслей — неприкосновенны;
- сохраняй человеческое: конкретные детали, эмоцию, вариативность длины фраз;
- всё из блока «Обязательно для озвучки» ниже.

## Режим phonetics

ЕДИНСТВЕННЫЕ разрешённые операции:
- термины, бренды, фамилии, иностранные слова — фонетической записью
  («Microsoft» → «Майкрософт», «UGC» → «ю-джи-си», «CRM» → «Си-Ар-Эм»);
- числа, валюты, даты — прописью словами («45 000 ₸» → «сорок пять тысяч тенге»).
Больше НЕ меняй ничего: ни слова, ни порядок, ни знаки. Справочник в этом
режиме используй только как список правил фонетики.

## Обязательно для озвучки (оба режима)

- латиницы в speech быть не должно;
- аббревиатуры — как произносятся;
- в сложных словах ударение акутом (символ U+0301 после ударной гласной);
- эмоц-теги ElevenLabs в квадратных скобках ([смех], [вздыхает]) сохраняй.
````

`plugins/reels-factory/skills/humanizing-speech/references/speech-bans-ru.md`:

````markdown
# Запрещённые обороты и правила устной речи (ru)

Источники: humanizer-ru (MIT), Википедия «Признаки сгенерированности текста»,
правила фабрики. Пополняется авторами плагина.

## Жёсткие баны (заметил — переформулируй)

- «Не просто X, а Y», «Это не X — это Y»
- «в современном мире», «в современном динамично развивающемся мире»
- «данный», «является» (чаще 1 раза), «осуществлять», «представляет собой»
- «стоит отметить», «важно понимать», «важно отметить», «не секрет, что»
- «давайте разберёмся», «давайте рассмотрим», «итак,», «более того»
- «играет важную/ключевую роль», «ключевой момент», «неизгладимый след»
- «в данном видео», «как мы видим», «подводя итог», «в заключение»
- «может похвастаться», «раскрыть потенциал», «комплексный подход»
- артефакты чатбота: «Надеюсь, это помогло», «Конечно,», «Безусловно,»
- размытые атрибуции: «по словам экспертов», «некоторые считают»

## Правила устной речи

1. Фразы до ~12 слов. Одна фраза — одна мысль.
2. Никаких причастных/деепричастных цепочек и вложенных придаточных.
3. Избегай слов с кластерами губных согласных (п-б-м) подряд и
   труднопроизносимых стыков.
4. Числа/валюты/даты — прописью. Латиница — фонетически.
5. Разговорные конструкции допустимы, если так яснее.

## Примеры

Плохо: «Внедрение данной системы позволило осуществить рост конверсии.»
Хорошо: «Поставили систему — конверсия выросла.»
Плохо: «Важно понимать, что контент является ключевым инструментом.»
Хорошо: «Без контента сегодня никуда.»
Плохо: «Мы используем Microsoft Teams для коммуникации.»
Хорошо: «Созваниваемся в Майкрософт Тимс.»
````

`plugins/reels-factory/skills/humanizing-speech/evals/evals.json`:

```json
[
  {
    "name": "phonetics_only_transliterates",
    "prompt": "/reels-factory:humanizing-speech {\"mode\":\"phonetics\",\"language\":\"ru\",\"blocks\":[{\"role\":\"hook\",\"speech\":\"Мы внедрили Microsoft CRM за 2 недели.\"}]} (задание передано инлайн вместо файла для eval)",
    "assertions": [
      "output is JSON with key blocks",
      "no Latin characters remain in any speech",
      "the word order and all non-brand words are unchanged",
      "digits are spelled out in words"
    ]
  },
  {
    "name": "polish_removes_ai_cliches",
    "prompt": "/reels-factory:humanizing-speech {\"mode\":\"polish\",\"language\":\"ru\",\"blocks\":[{\"role\":\"hook\",\"speech\":\"Важно понимать, что в современном мире внедрение данной системы является ключевым фактором роста, позволившим осуществить увеличение конверсии на 40 процентов.\"}]} (задание инлайн для eval)",
    "assertions": [
      "output is JSON with key blocks and same single role hook",
      "no banned phrases from speech-bans-ru.md remain",
      "the number 40 (сорок процентов) is preserved",
      "sentences are at most ~12 words each"
    ]
  }
]
```

- [ ] **Step 6: Validate plugin structure**

Run (из корня репо): `claude plugin validate ./plugins/reels-factory --strict`
Expected: OK, скилл виден без ошибок манифеста.

- [ ] **Step 7: Commit**

```bash
git add plugins/reels-factory/skills/humanizing-speech plugins/reels-factory/engine/src/reels_factory/humanize.py plugins/reels-factory/engine/tests/test_humanize.py
git commit -m "feat(humanize): скилл humanizing-speech (polish/phonetics) + модуль движка"
```

---

### Task 6: CLI `script-text` — путь 1 целиком

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/__main__.py`
- Test: `plugins/reels-factory/engine/tests/test_scenario.py` (дополнить) — тестируем новую функцию `run_script_text` из scenario-модуля… нет: логику кладём в `humanize.py`? Нет — новый модуль не нужен, функция в `__main__.py` нетестируема удобно. Решение: логика — в `scenario.py::run_verbatim_path`, CLI — тонкая обёртка.
- Modify: `plugins/reels-factory/engine/src/reels_factory/scenario.py` (добавить `run_verbatim_path`)

**Interfaces:**
- Consumes: `scenario_from_text`, `validate_integrity` (Task 2), `humanize_scenario` (Task 5), `transcribe_file` (существующий, Task 8 добавит язык).
- Produces:
  - `scenario.run_verbatim_path(workdir: Path, text: str, skill_runner, language: str) -> dict` — phonetics-хуманизация → verbatim-сценарий (разбивка ПОСЛЕ фонетики, чтобы блоки несли финальный текст) → integrity; возвращает `{"ok", "scenario", "info": {"words", "est_seconds"}}`.
  - CLI: `python -m reels_factory script-text --workdir W (--text-file F | --audio F)` — JSON в stdout: `{"ok", "scenario", "info"}`; exit 1 при ошибке.
- Примечание: строка стоимости считается в чат-скилле (Task 10) из `info.est_seconds` — прайс HeyGen движок не знает (Юля подтвердит модель; поле в конфиг не добавляем, пока прайс не подтверждён).

- [ ] **Step 1: Write the failing tests**

Дописать в `tests/test_scenario.py`:

```python
from reels_factory.llm import FakeSkillRunner
from reels_factory.scenario import run_verbatim_path


def test_run_verbatim_path_full_flow(tmp_path):
    text = "Мы внедрили Microsoft. Продажи выросли в два раза. Клиенты довольны."
    phonetics_reply = json.dumps({"blocks": [
        {"role": "hook", "speech": "Мы внедрили Майкрософт."},
        {"role": "development", "speech": "Продажи выросли в два раза."},
        {"role": "payoff", "speech": "Клиенты довольны."},
    ]}, ensure_ascii=False)
    runner = FakeSkillRunner([phonetics_reply])

    res = run_verbatim_path(tmp_path, text, runner, language="ru")

    assert res["ok"] is True
    sc = res["scenario"]
    assert sc["mode"] == "verbatim"
    assert "Майкрософт" in sc["blocks"][0]["speech"]
    assert (tmp_path / "scenario.json").exists()
    assert res["info"]["words"] > 0
    assert res["info"]["est_seconds"] > 0
    # задание фонетики получило текст одним блоком (разбивка — после)
    task = json.loads(runner.calls[0][1].read_text(encoding="utf-8"))
    assert task["mode"] == "phonetics"
```

Замечание для исполнителя: фонетика получает текст, уже разбитый
`split_verbatim` (структура блоков нужна контракту скилла), затем блоки
пересобираются из ответа — это и есть «разбивка несёт финальный текст».
Тест выше проверяет именно контракт: mode=phonetics, финальный scenario.json
содержит фонетический текст.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scenario.py::test_run_verbatim_path_full_flow -v`
Expected: FAIL — ImportError `run_verbatim_path`.

- [ ] **Step 3: Implement**

В `scenario.py` (после `validate_integrity`):

```python
def run_verbatim_path(workdir, text: str, skill_runner, language: str) -> dict:
    """Путь «дословно»: фонетика (единственная правка) -> scenario.json."""
    from reels_factory.humanize import humanize_scenario

    workdir = Path(workdir)
    draft = {"mode": "verbatim", "blocks": split_verbatim(text)}
    final = humanize_scenario(skill_runner, workdir, draft,
                              mode="phonetics", language=language)
    errs = validate_integrity(final)
    if errs:
        raise ScenarioError(f"целостность: {errs}")
    (workdir / "scenario.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
    n_words = sum(_wordcount(b["speech"]) for b in final["blocks"])
    return {"ok": True, "scenario": final,
            "info": {"words": n_words,
                     "est_seconds": round(n_words / WORDS_PER_SEC)}}
```

В `__main__.py` добавить команду (по образцу `_cmd_script`):

```python
def _cmd_script_text(args, cfg):
    from reels_factory.scenario import run_verbatim_path, ScenarioError
    from reels_factory.llm import ClaudeSkillRunner

    wd = _resolve_workdir(args.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    else:
        from reels_factory.transcribe import transcribe_file
        meta = transcribe_file(args.audio, wd, language=cfg.get("language", "ru"))
        words = json.loads(Path(meta["out"]).read_text(encoding="utf-8"))["words"]
        text = " ".join(w["text"] for w in words)
    try:
        res = run_verbatim_path(wd, text, ClaudeSkillRunner(),
                                language=cfg.get("language", "ru"))
    except (ScenarioError, Exception) as e:
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(res, ensure_ascii=False))
```

И в `main()` парсер:

```python
    p_st = sub.add_parser("script-text",
                          help="путь «дословно»: текст/аудио пользователя -> scenario.json без правок")
    p_st.add_argument("--workdir", required=True)
    g = p_st.add_mutually_exclusive_group(required=True)
    g.add_argument("--text-file", dest="text_file", help="файл с готовым текстом")
    g.add_argument("--audio", help="аудио/видео с речью (локальная расшифровка)")
```

и ветку диспетчера: `elif args.cmd == "script-text": _cmd_script_text(args, cfg)`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest` → все PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/reels-factory/engine/src/reels_factory/scenario.py plugins/reels-factory/engine/src/reels_factory/__main__.py plugins/reels-factory/engine/tests/test_scenario.py
git commit -m "feat(cli): script-text — путь «дословно» целиком"
```

---

### Task 7: Скилл judging-script + цикл редактор→судья (refine_loop)

**Files:**
- Create: `plugins/reels-factory/skills/judging-script/SKILL.md`
- Create: `plugins/reels-factory/skills/judging-script/evals/evals.json`
- Modify: `plugins/reels-factory/engine/src/reels_factory/humanize.py`
- Test: `plugins/reels-factory/engine/tests/test_humanize.py` (дополнить)

**Interfaces:**
- Consumes: `humanize_scenario` (Task 5), `SkillRunner`.
- Produces:
  - `humanize.judge_scenario(runner, workdir, sc, task: dict, language: str) -> dict` — пишет `<workdir>/judge_task.json` `{"language","task","blocks"}`; возвращает вердикт `{"pass": bool, "scores": {...}, "issues": [{"criterion","where","what","fix"}]}`; невалидный JSON → `HumanizeError`.
  - `humanize.refine_loop(runner, workdir, sc, task, language, max_rounds=2) -> tuple[dict, dict]` — polish → judge; not pass → повторный polish с претензиями (`task["issues"]` в задании) → judge (претензии прошлого круга в `task["prior_issues"]`); возвращает `(лучший сценарий, последний вердикт)`.

- [ ] **Step 1: Write the failing tests**

Дописать в `tests/test_humanize.py`:

```python
from reels_factory.humanize import judge_scenario, refine_loop

TASK = {"idea": "как мы подняли продажи", "length_s": 30}


def _blocks_reply(suffix=""):
    return json.dumps({"blocks": [
        {"role": "hook", "speech": "Хук" + suffix},
        {"role": "development", "speech": "Развитие" + suffix},
    ]}, ensure_ascii=False)


VERDICT_FAIL = json.dumps({"pass": False,
                           "scores": {"hook": False},
                           "issues": [{"criterion": "hook", "where": "Хук",
                                       "what": "не цепляет", "fix": "начни с цифры"}]},
                          ensure_ascii=False)
VERDICT_PASS = json.dumps({"pass": True, "scores": {"hook": True}, "issues": []},
                          ensure_ascii=False)


def test_judge_scenario_parses_verdict(tmp_path):
    runner = FakeSkillRunner([VERDICT_PASS])
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 2.0, "speech": "х"}]}
    v = judge_scenario(runner, tmp_path, sc, TASK, "ru")
    assert v["pass"] is True
    assert runner.calls[0][0] == "judging-script"


def test_refine_loop_retries_until_pass(tmp_path):
    sc = {"blocks": [
        {"role": "hook", "start": 0.0, "end": 2.0, "speech": "а"},
        {"role": "development", "start": 2.0, "end": 4.0, "speech": "б"},
    ]}
    runner = FakeSkillRunner([
        _blocks_reply(" v1"), VERDICT_FAIL,   # круг 1: polish + брак
        _blocks_reply(" v2"), VERDICT_PASS,   # круг 2: polish с претензиями + pass
    ])
    final, verdict = refine_loop(runner, tmp_path, sc, TASK, "ru", max_rounds=2)
    assert verdict["pass"] is True
    assert final["blocks"][0]["speech"] == "Хук v2"
    # претензии судьи дошли до редактора на 2-м круге
    second_polish_task = json.loads(runner.calls[2][1].read_text(encoding="utf-8"))
    assert second_polish_task.get("issues")


def test_refine_loop_returns_last_on_exhaust(tmp_path):
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 2.0, "speech": "а"}]}
    runner = FakeSkillRunner([
        json.dumps({"blocks": [{"role": "hook", "speech": "v1"}]}), VERDICT_FAIL,
        json.dumps({"blocks": [{"role": "hook", "speech": "v2"}]}), VERDICT_FAIL,
    ])
    final, verdict = refine_loop(runner, tmp_path, sc, TASK, "ru", max_rounds=2)
    assert verdict["pass"] is False
    assert final["blocks"][0]["speech"] == "v2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_humanize.py -v` → FAIL (ImportError judge_scenario).

- [ ] **Step 3: Implement in humanize.py**

```python
def judge_scenario(runner, workdir, sc: dict, task: dict, language: str) -> dict:
    workdir = Path(workdir)
    payload = workdir / "judge_task.json"
    payload.write_text(json.dumps(
        {"language": language, "task": task,
         "blocks": [{"role": b["role"], "speech": b["speech"]} for b in sc["blocks"]]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    reply = runner.run_skill("judging-script", payload)
    try:
        v = _extract_json(reply)
    except ScenarioError as e:
        raise HumanizeError(f"судья вернул не-JSON: {e}") from e
    if not isinstance(v.get("pass"), bool):
        raise HumanizeError(f"вердикт без поля pass: {v!r}")
    return v


def refine_loop(runner, workdir, sc: dict, task: dict, language: str,
                max_rounds: int = 2):
    """polish -> judge; брак -> polish с претензиями -> judge. Возвращает
    (лучший из имеющихся сценарий, последний вердикт)."""
    current, verdict = sc, None
    issues = []
    for _ in range(max_rounds):
        round_task = dict(task)
        if issues:
            round_task["issues"] = issues
        # humanize_scenario читает только mode/language/blocks; претензии и
        # задание кладём в тот же файл — скилл увидит их в JSON задания
        current = _polish_with_task(runner, workdir, current, language, round_task)
        judge_task = dict(task)
        if issues:
            judge_task["prior_issues"] = issues
        verdict = judge_scenario(runner, workdir, current, judge_task, language)
        if verdict["pass"]:
            return current, verdict
        issues = verdict.get("issues") or []
    return current, verdict


def _polish_with_task(runner, workdir, sc: dict, language: str, task: dict) -> dict:
    """Как humanize_scenario(mode=polish), но с полем task в задании."""
    workdir = Path(workdir)
    payload = workdir / "humanize_task.json"
    payload.write_text(json.dumps(
        {"mode": "polish", "language": language, "task": task,
         "blocks": [{"role": b["role"], "speech": b["speech"]} for b in sc["blocks"]],
         **({"issues": task["issues"]} if task.get("issues") else {})},
        ensure_ascii=False, indent=1), encoding="utf-8")
    reply = runner.run_skill("humanizing-speech", payload)
    try:
        data = _extract_json(reply)
    except ScenarioError as e:
        raise HumanizeError(str(e)) from e
    new_blocks = data.get("blocks")
    if (not isinstance(new_blocks, list)
            or [b.get("role") for b in new_blocks] != [b["role"] for b in sc["blocks"]]):
        raise HumanizeError(f"скилл вернул блоки с другими ролями: {new_blocks!r}")
    return {**sc, "blocks": [dict(o, speech=str(nb.get("speech") or o["speech"]))
                             for o, nb in zip(sc["blocks"], new_blocks)]}
```

(Рефакторинг: `humanize_scenario` переписать как обёртку над `_polish_with_task`-подобным ядром, чтобы не дублировать разбор ответа — общее ядро `_call_humanizer(runner, workdir, sc, payload_dict)`.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_humanize.py -v` → PASS. `python -m pytest` → PASS.

- [ ] **Step 5: Create the judging-script skill**

`plugins/reels-factory/skills/judging-script/SKILL.md`:

````markdown
---
name: judging-script
description: Adversarial judge for short vertical reel scripts. Reads a JSON task file (language, task, blocks), evaluates against binary rubric, returns strict JSON verdict with actionable issues. Engine-invoked. Not for chat use.
disable-model-invocation: true
---

# Judging Script

Ты — придирчивый редактор коротких вертикальных роликов, нанятый заказчиком
проверять чужую работу. Тебе неизвестно, кто написал текст. Твоя репутация
страдает, если брак пройдёт. При сомнении по критерию — fail.

Аргумент вызова — путь к JSON: `{"language", "task": {"idea"?, "length_s"?,
"quotes"?, "prior_issues"?}, "blocks": [{"role", "speech"}]}`.

## Порядок

1. Прочитай файл задания.
2. Если есть `task.prior_issues` — сначала проверь, устранена ли каждая из
   этих претензий; неустранённые включи в issues снова.
3. По КАЖДОМУ критерию ниже: сначала краткое рассуждение, потом bool.
4. Ответь ТОЛЬКО JSON (без пояснений, без ограждений) — схема в конце.

## Критерии (все бинарные; pass = все true)

1. **hook** — первые ~12 произносимых слов содержат разрыв шаблона, петлю
   любопытства или конкретную цифру/факт. Нет приветствий, само-представлений,
   «в этом видео». Пример pass: «Минус триста тысяч за месяц. Вот что нас
   спасло.» Пример fail: «Привет, сегодня я расскажу про наш продукт.»
2. **one_idea** — весь текст пересказывается одним предложением; нет второй
   темы, которую можно вырезать без потери.
3. **speakable** — читается вслух не запнувшись: нет фраз длиннее ~15 слов без
   паузы, латиницы, аббревиатур без расшифровки, цифр с неясным произношением,
   канцелярита. Для kk — естественный порядок слов, не калька с русского.
   Пример fail: «Осуществив внедрение CRM, мы констатировали рост.»
4. **facts** — числа, имена и утверждения совпадают с `task.quotes`/`task.idea`
   (если заданы); ничего не додумано. Нет quotes — проверяй внутреннюю
   непротиворечивость.
5. **cta** — призыв есть, один, в конце, тип соответствует смыслу ролика
   (заявки не навязаны там, где смысл с ними несовместим; допустимы «поделись»,
   «сохрани», «напиши в комментариях», «подпишись»). Критерий применяется,
   только если в task есть `idea` (путь генерации).
6. **fit_length** — суммарная речь соответствует `task.length_s` из расчёта
   ~2.5 слова/сек (допуск ±25%). Применяется, только если `length_s` задан.

## Схема ответа

```json
{"pass": false,
 "scores": {"hook": true, "one_idea": true, "speakable": false,
            "facts": true, "cta": true, "fit_length": true},
 "issues": [{"criterion": "speakable",
             "where": "точная цитата проблемного места (до 15 слов)",
             "what": "в чём брак, одним предложением",
             "fix": "исполняемая инструкция редактору, лучше готовый вариант"}]}
```

Каждый критерий со значением false — минимум одна претензия в issues.
````

`plugins/reels-factory/skills/judging-script/evals/evals.json`:

```json
[
  {
    "name": "fails_greeting_hook",
    "prompt": "/reels-factory:judging-script {\"language\":\"ru\",\"task\":{\"idea\":\"рост продаж\",\"length_s\":30},\"blocks\":[{\"role\":\"hook\",\"speech\":\"Привет, друзья, сегодня я расскажу вам про наш продукт и его историю.\"},{\"role\":\"cta\",\"speech\":\"Подпишись.\"}]} (задание инлайн для eval)",
    "assertions": [
      "output is strict JSON matching the verdict schema",
      "pass is false",
      "scores.hook is false",
      "issues contains an entry with criterion hook and a concrete fix"
    ]
  },
  {
    "name": "passes_good_script",
    "prompt": "/reels-factory:judging-script {\"language\":\"ru\",\"task\":{\"idea\":\"ошибка в оффере съедала продажи\",\"length_s\":20},\"blocks\":[{\"role\":\"hook\",\"speech\":\"Минус триста тысяч за месяц. Одна строка в оффере.\"},{\"role\":\"development\",\"speech\":\"Мы обещали скидку всем. Покупали только халявщики.\"},{\"role\":\"payoff\",\"speech\":\"Убрали скидку — средний чек вырос вдвое.\"},{\"role\":\"cta\",\"speech\":\"Сохрани, чтобы не повторить.\"}]} (задание инлайн для eval)",
    "assertions": [
      "output is strict JSON matching the verdict schema",
      "pass is true",
      "issues is an empty array"
    ]
  }
]
```

- [ ] **Step 6: Validate and commit**

Run: `claude plugin validate ./plugins/reels-factory --strict` → OK.

```bash
git add plugins/reels-factory/skills/judging-script plugins/reels-factory/engine/src/reels_factory/humanize.py plugins/reels-factory/engine/tests/test_humanize.py
git commit -m "feat(judge): скилл judging-script + refine_loop редактор->судья"
```

---

### Task 8: transcribe.py — язык из конфига (kk насквозь, часть 1)

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/transcribe.py:93` (только сигнатурный дефолт — язык уже параметр)
- Test: `plugins/reels-factory/engine/tests/test_ingest.py` — НЕ трогать; новый тест в `tests/test_scenario.py`

**Interfaces:**
- Consumes: `transcribe_file(src, workdir, model_size, language, device)` — язык УЖЕ параметр (см. `transcribe.py:93`); `_cmd_script_text` уже передаёт `cfg["language"]` (Task 6).
- Produces: подтверждённый тестом контракт «язык из конфига доходит до расшифровки».

- [ ] **Step 1: Write the failing test**

Дописать в `tests/test_scenario.py` тест на прокидку языка через CLI-обвязку
(функцию `_cmd_script_text` дёргаем напрямую с фейками):

```python
def test_script_text_passes_language_to_transcribe(monkeypatch, tmp_path):
    import reels_factory.__main__ as cli

    seen = {}

    def fake_transcribe_file(src, workdir, model_size="large-v3",
                             language="ru", device="auto"):
        seen["language"] = language
        out = Path(workdir) / "words.json"
        out.write_text(json.dumps({"words": [
            {"id": 0, "start": 0.0, "end": 1.0, "text": "сәлем", "prob": 1.0}]},
            ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "out": str(out)}

    import reels_factory.transcribe as tr
    monkeypatch.setattr(tr, "transcribe_file", fake_transcribe_file)

    class Args:
        workdir = str(tmp_path)
        text_file = None
        audio = "fake.wav"

    import reels_factory.llm as llm
    monkeypatch.setattr(llm, "ClaudeSkillRunner",
                        lambda: FakeSkillRunner([json.dumps(
                            {"blocks": [{"role": "hook", "speech": "сәлем"}]},
                            ensure_ascii=False)]))

    cli._cmd_script_text(Args, {"language": "kk"})
    assert seen["language"] == "kk"
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `python -m pytest tests/test_scenario.py::test_script_text_passes_language_to_transcribe -v`
Если PASS сразу (Task 6 уже прокидывает язык) — это подтверждающий тест,
оставить; если FAIL — поправить `_cmd_script_text` до передачи
`language=cfg.get("language", "ru")`.

- [ ] **Step 3: Run all tests and commit**

Run: `python -m pytest` → PASS.

```bash
git add plugins/reels-factory/engine/tests/test_scenario.py
git commit -m "test: язык из конфига доходит до расшифровки (kk насквозь)"
```

---

### Task 9: Скилл writing-scenario + путь 2 в движке (script-idea)

**Files:**
- Create: `plugins/reels-factory/skills/writing-scenario/SKILL.md`
- Create: `plugins/reels-factory/skills/writing-scenario/references/hooks.md`
- Create: `plugins/reels-factory/skills/writing-scenario/evals/evals.json`
- Modify: `plugins/reels-factory/engine/src/reels_factory/scenario.py` (добавить `run_generated_path`)
- Modify: `plugins/reels-factory/engine/src/reels_factory/__main__.py` (команда `script-idea`)
- Test: `plugins/reels-factory/engine/tests/test_scenario.py` (дополнить)

**Interfaces:**
- Consumes: `SkillRunner` (Task 4), `refine_loop` (Task 7), `validate_integrity` (Task 2).
- Produces:
  - `scenario.run_generated_path(workdir, idea: dict, skill_runner, language: str) -> dict` — `idea` = `{"idea": str, "length_s": int, "quotes": list[str], "persona": str|None}`; пишет `<workdir>/idea.json`, зовёт скилл `writing-scenario` (черновик) → `refine_loop` (полировка+судья) → integrity → `scenario.json`; возвращает `{"ok", "scenario", "verdict"}`.
  - CLI: `python -m reels_factory script-idea --workdir W --idea-file F` — JSON в stdout; exit 1 при ошибке целостности/JSON, exit 2 если вердикт судьи `pass: false` после ретраев (сценарий всё равно сохранён — чат-скилл покажет претензии пользователю).
- Контракт скилла writing-scenario: вход — путь к JSON `{"language","idea","length_s","quotes","persona"}`; выход — ТОЛЬКО JSON `{"title","blocks":[{"role","start","end","speech"}]}` с ролями из hook/context/development/payoff/cta по порядку.

- [ ] **Step 1: Write the failing tests**

Дописать в `tests/test_scenario.py`:

```python
from reels_factory.scenario import run_generated_path

IDEA = {"idea": "скидка всем убивала средний чек", "length_s": 20,
        "quotes": ["средний чек вырос вдвое"], "persona": "владелец бизнеса"}


def _gen_reply():
    return json.dumps({"title": "Скидка-убийца", "blocks": [
        {"role": "hook", "start": 0.0, "end": 3.0, "speech": "Минус триста тысяч."},
        {"role": "development", "start": 3.0, "end": 12.0, "speech": "Скидка была всем."},
        {"role": "payoff", "start": 12.0, "end": 17.0, "speech": "Чек вырос вдвое."},
        {"role": "cta", "start": 17.0, "end": 20.0, "speech": "Сохрани."},
    ]}, ensure_ascii=False)


def _polish_pass_replies():
    blocks = json.loads(_gen_reply())["blocks"]
    polish = json.dumps({"blocks": [{"role": b["role"], "speech": b["speech"]}
                                    for b in blocks]}, ensure_ascii=False)
    verdict = json.dumps({"pass": True, "scores": {}, "issues": []})
    return [polish, verdict]


def test_run_generated_path_full_flow(tmp_path):
    runner = FakeSkillRunner([_gen_reply(), *_polish_pass_replies()])
    res = run_generated_path(tmp_path, IDEA, runner, language="ru")
    assert res["ok"] is True
    assert res["verdict"]["pass"] is True
    assert (tmp_path / "scenario.json").exists()
    # порядок вызовов: генерация -> полировка -> судья
    assert [c[0] for c in runner.calls] == [
        "writing-scenario", "humanizing-speech", "judging-script"]
    gen_task = json.loads(runner.calls[0][1].read_text(encoding="utf-8"))
    assert gen_task["length_s"] == 20
    assert gen_task["language"] == "ru"


def test_run_generated_path_bad_blocks_raises(tmp_path):
    runner = FakeSkillRunner([json.dumps({"title": "x", "blocks": []})])
    import pytest as _pytest
    with _pytest.raises(Exception):
        run_generated_path(tmp_path, IDEA, runner, language="ru")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scenario.py -k generated -v` → FAIL (ImportError).

- [ ] **Step 3: Implement run_generated_path**

В `scenario.py`:

```python
def run_generated_path(workdir, idea: dict, skill_runner, language: str) -> dict:
    """Путь «из сырья»: скилл-генерация -> полировка+судья -> scenario.json."""
    from reels_factory.humanize import refine_loop

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    task = {"language": language,
            "idea": idea.get("idea"),
            "length_s": idea.get("length_s"),
            "quotes": idea.get("quotes") or [],
            "persona": idea.get("persona")}
    payload = workdir / "idea.json"
    payload.write_text(json.dumps(task, ensure_ascii=False, indent=1),
                       encoding="utf-8")

    reply = skill_runner.run_skill("writing-scenario", payload)
    draft = _extract_json(reply)
    errs = validate_integrity(draft)
    if errs:
        raise ScenarioError(f"черновик генерации: {errs}")

    final, verdict = refine_loop(skill_runner, workdir, draft,
                                 {k: task[k] for k in ("idea", "length_s", "quotes")},
                                 language)
    errs = validate_integrity(final)
    if errs:
        raise ScenarioError(f"целостность после полировки: {errs}")
    (workdir / "scenario.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "scenario": final, "verdict": verdict}
```

В `__main__.py` — команда:

```python
def _cmd_script_idea(args, cfg):
    from reels_factory.scenario import run_generated_path, ScenarioError
    from reels_factory.llm import ClaudeSkillRunner

    wd = _resolve_workdir(args.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    idea = json.loads(Path(args.idea_file).read_text(encoding="utf-8"))
    try:
        res = run_generated_path(wd, idea, ClaudeSkillRunner(),
                                 language=cfg.get("language", "ru"))
    except ScenarioError as e:
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res["verdict"]["pass"] else 2)
```

Парсер:

```python
    p_si = sub.add_parser("script-idea",
                          help="путь «из сырья»: задание-идея -> генерация+хуманизация+судья")
    p_si.add_argument("--workdir", required=True)
    p_si.add_argument("--idea-file", required=True, dest="idea_file",
                      help="JSON: {idea, length_s, quotes[], persona?}")
```

и ветка `elif args.cmd == "script-idea": _cmd_script_idea(args, cfg)`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest` → PASS.

- [ ] **Step 5: Create the writing-scenario skill**

`plugins/reels-factory/skills/writing-scenario/SKILL.md`:

````markdown
---
name: writing-scenario
description: Writes a short vertical reel script (ru/kk) from an idea task file - hook, one idea, user facts only, spoken style, CTA matched to meaning. Engine-invoked with a path to a JSON task file. Not for chat use.
disable-model-invocation: true
---

# Writing Scenario

Ты пишешь текст короткого вертикального ролика, который человек произнесёт
вслух на камеру. Аргумент вызова — путь к JSON-заданию:
`{"language", "idea", "length_s", "quotes": [...], "persona"}`.

## Порядок

1. Прочитай задание. Язык текста — `language`. Целевая длина — `length_s`
   секунд, это ~`length_s * 2.5` слов суммарно.
2. Прочитай `references/hooks.md`, напиши 2–3 варианта хука по разным
   формулам, выбери лучший по трём проверкам: тема мгновенно ясна; есть
   контрастное слово/поворот; есть неожиданный сдвиг. Первые ~12 произносимых
   слов обязаны содержать крючок. Запрещены приветствия, само-представления,
   «в этом видео».
3. Напиши сценарий по таймингу в процентах от `length_s`:
   хук 10% → проблема/история 25% → суть 30% → доказательство 25% → CTA 10%.
4. Самопроверка перед выдачей: пройди чек-лист, перепиши что не прошло.
5. Ответь ТОЛЬКО JSON (схема в конце).

## Правила

- ОДНА идея на ролик, максимум 2 ключевых пункта.
- Факты — только из `quotes` (и самой `idea`). Ничего не выдумывай: ни цифр,
  ни кейсов, ни результатов. Нет факта — не утверждай.
- Предложения ≤15 слов, писать как говорят, от лица `persona` (если задана).
- Под озвучку: числа/валюты/даты прописью, аббревиатуры как произносятся,
  термины и бренды фонетической записью, без латиницы.
- CTA: один, в конце, тип по СМЫСЛУ ролика — заявки только если смысл ролика
  совместим с ними; иначе «поделись с тем, кому нужно» / «сохрани» /
  «напиши мнение в комментариях» / «подпишись».

## Чек-лист самопроверки

- Скроллер: остановит ли первая фраза человека, листающего ленту?
- Скептик: не звучит ли текст как реклама или ИИ-текст?
- Хук в первых 3 секундах? Одна идея? Все факты из quotes? CTA по смыслу?

## Схема ответа

```json
{"title": "...", "blocks": [
  {"role": "hook", "start": 0.0, "end": 3.0, "speech": "..."},
  {"role": "development", "start": 3.0, "end": 12.0, "speech": "..."},
  {"role": "payoff", "start": 12.0, "end": 17.0, "speech": "..."},
  {"role": "cta", "start": 17.0, "end": 20.0, "speech": "..."}]}
```

Роли ровно hook, development, payoff, cta по порядку (context после hook —
только если правда нужна короткая завязка). start/end — доли от `length_s`
по таймингу из шага 3; start каждого блока равен end предыдущего.
````

`plugins/reels-factory/skills/writing-scenario/references/hooks.md`:

````markdown
# Формулы хуков (выбирай 2–3, пиши варианты, бери лучший)

1. Конкретное число: «Минус триста тысяч за один месяц.»
2. Контрарное утверждение: «Скидки убивают продажи.»
3. Личная трансформация: «Год назад я боялся камеры. Вчера — миллион просмотров.»
4. Исповедь/провал: «Я потерял первого клиента из-за одной фразы.»
5. Вопрос-вакуум (без очевидного ответа): «Почему худший продавец делает лучшие чеки?»
6. Результат-вперёд: «Двадцать заявок за ночь. Показываю как.»
7. Прогноз: «Через год без этого не выживет ни один эксперт.»

Тест лучшего хука (Kallaway): тема мгновенно ясна + контрастное слово/поворот
+ неожиданный сдвиг нарратива. Анти-паттерны: приветствие, само-представление,
абстрактная тема без обещания, вопрос с очевидным ответом.
````

`plugins/reels-factory/skills/writing-scenario/evals/evals.json`:

```json
[
  {
    "name": "grounded_no_invented_facts",
    "prompt": "/reels-factory:writing-scenario {\"language\":\"ru\",\"idea\":\"убрали скидку и средний чек вырос\",\"length_s\":20,\"quotes\":[\"убрали скидку\",\"средний чек вырос вдвое\"],\"persona\":\"владелец кофейни\"} (задание инлайн для eval)",
    "assertions": [
      "output is strict JSON with title and blocks per schema",
      "roles are hook development payoff cta in order",
      "no numeric claims beyond those derivable from quotes",
      "hook has no greeting and hooks within first 12 words",
      "no Latin characters in any speech"
    ]
  },
  {
    "name": "cta_matches_meaning",
    "prompt": "/reels-factory:writing-scenario {\"language\":\"ru\",\"idea\":\"личная история выгорания и восстановления\",\"length_s\":30,\"quotes\":[\"полгода не мог работать\",\"помог жёсткий режим сна\"],\"persona\":null} (задание инлайн для eval)",
    "assertions": [
      "cta block is not a sales/lead-gen call",
      "cta is share/save/comment/subscribe style matching the story"
    ]
  }
]
```

- [ ] **Step 6: Validate and commit**

Run: `claude plugin validate ./plugins/reels-factory --strict` → OK.

```bash
git add plugins/reels-factory/skills/writing-scenario plugins/reels-factory/engine/src/reels_factory/scenario.py plugins/reels-factory/engine/src/reels_factory/__main__.py plugins/reels-factory/engine/tests/test_scenario.py
git commit -m "feat(scenario): путь «из сырья» — скилл writing-scenario + script-idea CLI"
```

---

### Task 10: Скилл extracting-ideas + CLI ideas

**Files:**
- Create: `plugins/reels-factory/skills/extracting-ideas/SKILL.md`
- Create: `plugins/reels-factory/skills/extracting-ideas/evals/evals.json`
- Modify: `plugins/reels-factory/engine/src/reels_factory/__main__.py` (команда `ideas`)
- Modify: `plugins/reels-factory/engine/src/reels_factory/scenario.py` (функция `run_ideas`)
- Test: `plugins/reels-factory/engine/tests/test_scenario.py` (дополнить)

**Interfaces:**
- Consumes: `SkillRunner` (Task 4).
- Produces:
  - `scenario.run_ideas(workdir, source_text: str, skill_runner, language: str) -> dict` — пишет `<workdir>/ideas_task.json` `{"language","transcript"}`, зовёт скилл `extracting-ideas`, валидирует форму ответа, пишет `<workdir>/ideas.json`, возвращает `{"ok", "ideas": [...]}`. Каждая идея: `{"idea","emotion","draft_hook","quotes":[...],"length_s","why"}`; 2–3 штук, иначе `ScenarioError`.
  - CLI: `python -m reels_factory ideas --workdir W --source-file F` (текст; аудио пользователь прогоняет через `script-text --audio`-механику? нет — для сырья-аудио: `--audio F`, расшифровка как в Task 6).

- [ ] **Step 1: Write the failing tests**

```python
from reels_factory.scenario import run_ideas

IDEAS_REPLY = json.dumps({"ideas": [
    {"idea": "и1", "emotion": "удивление", "draft_hook": "х1",
     "quotes": ["ц1"], "length_s": 30, "why": "спорное мнение"},
    {"idea": "и2", "emotion": "злость", "draft_hook": "х2",
     "quotes": ["ц2"], "length_s": 60, "why": "история"},
]}, ensure_ascii=False)


def test_run_ideas_flow(tmp_path):
    runner = FakeSkillRunner([IDEAS_REPLY])
    res = run_ideas(tmp_path, "длинный транскрипт встречи", runner, "ru")
    assert res["ok"] is True
    assert len(res["ideas"]) == 2
    assert (tmp_path / "ideas.json").exists()
    task = json.loads(runner.calls[0][1].read_text(encoding="utf-8"))
    assert task["transcript"] == "длинный транскрипт встречи"


def test_run_ideas_rejects_wrong_shape(tmp_path):
    runner = FakeSkillRunner([json.dumps({"ideas": []})])
    import pytest as _pytest
    with _pytest.raises(Exception):
        run_ideas(tmp_path, "т", runner, "ru")
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_scenario.py -k ideas -v` → FAIL.

- [ ] **Step 3: Implement**

`scenario.py`:

```python
def run_ideas(workdir, source_text: str, skill_runner, language: str) -> dict:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    payload = workdir / "ideas_task.json"
    payload.write_text(json.dumps({"language": language, "transcript": source_text},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    reply = skill_runner.run_skill("extracting-ideas", payload)
    data = _extract_json(reply)
    ideas = data.get("ideas")
    if not isinstance(ideas, list) or not (2 <= len(ideas) <= 3):
        raise ScenarioError(f"ожидалось 2–3 идеи, получено: {ideas!r}")
    for i, idea in enumerate(ideas):
        for key in ("idea", "draft_hook", "quotes", "length_s"):
            if not idea.get(key):
                raise ScenarioError(f"идея {i}: нет поля {key}")
    (workdir / "ideas.json").write_text(
        json.dumps({"ideas": ideas}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "ideas": ideas}
```

`__main__.py` — команда `ideas` (по образцу script-text: `--source-file` или `--audio`):

```python
def _cmd_ideas(args, cfg):
    from reels_factory.scenario import run_ideas, ScenarioError
    from reels_factory.llm import ClaudeSkillRunner

    wd = _resolve_workdir(args.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    if args.source_file:
        text = Path(args.source_file).read_text(encoding="utf-8")
    else:
        from reels_factory.transcribe import transcribe_file
        meta = transcribe_file(args.audio, wd, language=cfg.get("language", "ru"))
        words = json.loads(Path(meta["out"]).read_text(encoding="utf-8"))["words"]
        text = " ".join(w["text"] for w in words)
    try:
        res = run_ideas(wd, text, ClaudeSkillRunner(), cfg.get("language", "ru"))
    except ScenarioError as e:
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(res, ensure_ascii=False))
```

Парсер:

```python
    p_i = sub.add_parser("ideas", help="извлечь 2-3 идеи рилсов из сырья (текст/аудио)")
    p_i.add_argument("--workdir", required=True)
    gi = p_i.add_mutually_exclusive_group(required=True)
    gi.add_argument("--source-file", dest="source_file", help="файл с текстом-сырьём")
    gi.add_argument("--audio", help="аудио/видео сырьё (локальная расшифровка)")
```

и ветка `elif args.cmd == "ideas": _cmd_ideas(args, cfg)`.

- [ ] **Step 4: Create the skill**

`plugins/reels-factory/skills/extracting-ideas/SKILL.md`:

````markdown
---
name: extracting-ideas
description: Extracts 2-3 viral reel ideas from raw meeting transcript or notes (ru/kk) with scoring rubric, draft hooks and supporting quotes. Engine-invoked with a path to a JSON task file. Not for chat use.
disable-model-invocation: true
---

# Extracting Ideas

Ты — виральный продюсер коротких видео. Аргумент вызова — путь к JSON:
`{"language", "transcript"}`.

## Порядок

1. Просканируй транскрипт по таксономии виральных моментов: спорное/смелое
   мнение; удивительный факт; эмоция (смех, признание, уязвимость); конкретный
   совет «вот как»; яркая цитата; начало истории с интригой. Набери 5–8
   кандидатов.
2. Оцени каждого кандидата 0–100 по рубрике: Хук 30% / Понятность без
   контекста 25% / Эмоция 20% / Плотность пользы 15% / Развязка 10%.
   Кандидаты <60 — отбрасывай. Балл — приоритизация, не гарантия.
3. Жёсткий фильтр: идея обязана быть понятной человеку, который НЕ был на
   встрече. Требует контекста — отклони или переформулируй.
4. Выбери 2–3 лучших. Для каждой определи длину ролика по материалу:
   короткий панч ~20–40с; история/разбор ~60–90с.
5. Ответь ТОЛЬКО JSON:

```json
{"ideas": [
  {"idea": "формулировка одной фразой",
   "emotion": "целевая эмоция зрителя",
   "draft_hook": "черновой хук",
   "quotes": ["точные цитаты-опоры из транскрипта"],
   "length_s": 30,
   "why": "почему зайдёт: момент таксономии + счёт по рубрике"}]}
```

Все тексты — на языке `language`. Цитаты — дословно из транскрипта (защита
от выдумывания фактов на следующих шагах).
````

`plugins/reels-factory/skills/extracting-ideas/evals/evals.json`:

```json
[
  {
    "name": "extracts_self_contained_ideas",
    "prompt": "/reels-factory:extracting-ideas {\"language\":\"ru\",\"transcript\":\"...мы потеряли триста тысяч на скидках, я вообще считаю что скидки это зло для малого бизнеса... потом обсуждали отчёт за март... кстати смешная история: клиент вернулся через год и извинился...\"} (задание инлайн для eval)",
    "assertions": [
      "output is strict JSON with 2-3 ideas",
      "each idea has idea, emotion, draft_hook, quotes, length_s, why",
      "quotes are verbatim substrings of the transcript",
      "no idea requires knowing meeting context to understand"
    ]
  }
]
```

- [ ] **Step 5: Run tests, validate, commit**

Run: `python -m pytest` → PASS. `claude plugin validate ./plugins/reels-factory --strict` → OK.

```bash
git add plugins/reels-factory/skills/extracting-ideas plugins/reels-factory/engine/src/reels_factory/scenario.py plugins/reels-factory/engine/src/reels_factory/__main__.py plugins/reels-factory/engine/tests/test_scenario.py
git commit -m "feat(ideas): скилл extracting-ideas + CLI ideas"
```

---

### Task 11: Чат-скилл — выбор пути и оба сценария для пользователя

**Files:**
- Modify: `plugins/reels-factory/skills/script/SKILL.md` (ПЕРЕПИСАТЬ ЦЕЛИКОМ: только два пути; research-цикл из пользовательского сценария удаляется)

**Interfaces:**
- Consumes: CLI-команды `script-text`, `script-idea`, `ideas` (Tasks 6, 9, 10).
- Produces: обновлённый пользовательский сценарий этапа script.

- [ ] **Step 1: Rewrite the chat skill**

Заменить содержимое `plugins/reels-factory/skills/script/SKILL.md` после
frontmatter (frontmatter обновить: description — «этап script: два пути
создания сценария»; упоминание research из description убрать). Все команды
ниже выполняет Клод сам — пользователь команд не видит и не вводит. Новое тело:

````markdown
## Шаг 0. Выбор пути (ОБЯЗАТЕЛЬНО, не угадывать)

Явно предложи пользователю выбор (в будущем боте это кнопки):
1. **Свой сценарий** — у тебя готовый текст (или голосовое), мы его НЕ меняем;
2. **Сгенерировать из сырья** — дай текст/аудио (транскрибацию, заметки,
   дневник), мы достанем идеи и напишем сценарий.

НЕ выбирай путь за пользователя по формулировке запроса. Спроси.
Все команды движка ниже запускаешь ТЫ сам, автоматически, в указанном
порядке — пользователь команд не вводит никогда.

## Путь 1: свой сценарий (дословно)

1. Получи от пользователя текст (сохрани в `work/<имя>/user_text.txt`) или
   аудиофайл.
2. Запусти из корня рабочей папки проекта:
   `$env:PYTHONUTF8="1"; .venv\Scripts\python.exe -m reels_factory script-text --workdir <имя> --text-file work/<имя>/user_text.txt`
   (для аудио: `--audio <путь>` вместо `--text-file`).
3. Движок НЕ меняет текст — только фонетическая запись брендов/чисел для
   озвучки. Замены пользователю не показывай (смысл не меняется).
4. Покажи пользователю текст по блокам и информ-строку из `info`:
   «~N слов ≈ M секунд» (стоимость аватара добавь, когда Юля подтвердит
   актуальный прайс модели HeyGen — до этого стоимость не называй).
5. Жди явного «ок». Для казахского (language: kk) — «ок» должен дать носитель
   (клиент), текст отправляет ему пользователь. БЕЗ «ок» не запускай ничего
   платного.
6. После «ок» — обычный `/reels-factory:make`.

## Путь 2: сгенерировать из сырья

1. Получи сырьё: текст (сохрани в `work/<имя>/source.txt`) или аудио.
2. `... -m reels_factory ideas --workdir <имя> --source-file work/<имя>/source.txt`
   (или `--audio <путь>`).
3. Покажи пользователю 2–3 идеи из ответа: формулировка, почему зайдёт,
   черновой хук, предлагаемая длина. Пользователь выбирает; любое его слово
   про длину («короче», «на минуту») переопределяет `length_s`.
4. Собери файл задания `work/<имя>/idea.json`:
   `{"idea": ..., "length_s": ..., "quotes": [...], "persona": <из config.yaml
   persona.description>}` — из выбранной идеи.
5. `... -m reels_factory script-idea --workdir <имя> --idea-file work/<имя>/idea.json`
   Exit-код 2 = судья не принял после ретраев: покажи пользователю сценарий И
   претензии судьи из `verdict.issues`, пусть решит — принять или перегенерить.
6. Покажи реплики по блокам полностью. Пользователь может править любой блок,
   включая CTA (CTA сгенерирован под смысл ролика). Правки вноси в
   `work/<имя>/scenario.json` руками.
7. Жди явного «ок» (kk — «ок» носителя). Дальше `/reels-factory:make`.

## Общие правила

- Ничего платного (make: ElevenLabs + HeyGen) без явного «ок» пользователя.
- Правки пользователя вноси в `work/<имя>/scenario.json` и показывай заново.
- Сабы — только речь ведущего. Свои надписи на видеоряд — никогда.
- `factory/hypotheses.md` НЕ требуется ни одному из путей.
````

(старые шаги 1–6 research-цикла и предусловие про hypotheses.md из скилла
удалить полностью — пользовательских путей ровно два.)

- [ ] **Step 2: Validate**

Run: `claude plugin validate ./plugins/reels-factory --strict` → OK.
Прочитать итоговый SKILL.md целиком: упоминаний research-цикла и
hypotheses.md как предусловия не осталось.

- [ ] **Step 3: Commit**

```bash
git add plugins/reels-factory/skills/script/SKILL.md
git commit -m "feat(skill): script — два пути (свой текст / из сырья), research-цикл убран"
```

---

### Task 12: Сквозная проверка и финал

**Files:**
- Test: полный прогон `python -m pytest` из `plugins/reels-factory/engine`
- Modify: `plugins/reels-factory/engine/README.md` (краткая секция про новые команды CLI)

- [ ] **Step 1: Full test suite**

Run: `python -m pytest -q` из `plugins/reels-factory/engine`
Expected: все тесты PASS, включая старые (test_ingest, test_render, test_captions, test_tts, test_glossary, test_llm).

- [ ] **Step 2: Plugin validation**

Run: `claude plugin validate ./plugins/reels-factory --strict` → OK (4 новых скилла видны).

- [ ] **Step 3: Смоук на реальном сырье (бесплатно, без TTS/HeyGen)**

Из `C:\Users\123\projects\reels MVP test` (venv связан editable):

```powershell
$env:PYTHONUTF8="1"; .venv\Scripts\python.exe -m reels_factory ideas --workdir smoke-ideas --source-file "C:\Users\123\Downloads\Жанна.md"
```

Expected: JSON с 2–3 идеями, понятными без контекста встречи. Это живой
вызов `claude -p` (бесплатный, локальный) — проверяет и SkillRunner, и скилл.

Затем путь 1 на коротком тексте:

```powershell
"Мы внедрили CRM. Продажи выросли вдвое. Пиши плюс в комментарии." | Out-File -Encoding utf8 work\smoke-text\user_text.txt
$env:PYTHONUTF8="1"; .venv\Scripts\python.exe -m reels_factory script-text --workdir smoke-text --text-file work\smoke-text\user_text.txt
```

Expected: `ok: true`, «CRM» стал «Си-Ар-Эм» (или аналог), остальной текст
дословно, `info.words`/`info.est_seconds` заполнены.

- [ ] **Step 4: README**

В `plugins/reels-factory/engine/README.md` добавить секцию:

```markdown
## CLI: пути сценария

- `script-text --workdir W (--text-file F | --audio F)` — путь «дословно»:
  текст пользователя без правок (только фонетика для озвучки) -> scenario.json.
- `ideas --workdir W (--source-file F | --audio F)` — 2-3 виральные идеи из
  сырья -> ideas.json.
- `script-idea --workdir W --idea-file F` — генерация по выбранной идее +
  хуманизация + LLM-судья (exit 2 = судья не принял, см. verdict.issues).
- `script ...` — классический research-цикл (без изменений).

Язык всех шагов — `language` из factory/config.yaml (ru по умолчанию, kk
поддержан насквозь: идеи, генерация, хуманизация, судья, расшифровка).
```

- [ ] **Step 5: Commit, показать дифф пользователю, ждать «ок» для PR**

```bash
git add plugins/reels-factory/engine/README.md
git commit -m "docs(engine): CLI-команды двух путей сценария"
```

Показать пользователю сводку изменений простыми словами (по правилам проекта).
Push и PR — только после явного «ок».

---

## Self-Review (выполнено при написании плана)

1. **Покрытие спеки:** путь 1 (Tasks 2, 5, 6), путь 2 (Tasks 7, 9, 10),
   4 скилла (Tasks 5, 7, 9, 10), выбор пути явно (Task 11), CTA генеративный
   по смыслу (скиллы writing-scenario/judging-script), целостность вместо
   старого валидатора (Task 2), баг латинской темы (Task 3), язык насквозь
   (Tasks 1, 6, 8 + language в каждом задании скиллов), цитаты-опоры/факт-замок
   (Tasks 5, 9, 10), стоимость: строка в чат-скилле отложена до подтверждения
   прайса Юлей (зафиксировано в Task 11 шаг 4 — стоимость не называть).
2. **Плейсхолдеров нет:** каждый шаг содержит код/контент целиком.
3. **Согласованность типов:** `run_skill(skill, payload_path)` единый (Tasks
   4, 5, 7, 9, 10); формат блоков `{"role","start","end","speech"}` единый;
   вердикт `{"pass","scores","issues"}` единый (Tasks 7, 9).
4. **Отложено сознательно (YAGNI):** `--json-schema` в claude -p (зависит от
   версии CLI — начинаем с `_extract_json`, он уже есть и протестирован);
   строка стоимости HeyGen (ждёт подтверждения модели/прайса Юлей); казахские
   списки банов (метод описан в скилле, наполнение — по обратной связи
   Серика); прогон evals через skill-creator (файлы evals.json заложены,
   запуск — отдельной сессией после реализации).
