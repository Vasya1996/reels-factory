# Монтажная насыщенность и честный учёт — план доработок №1 после переезда на HyperFrames

> **Для агента-исполнителя:** ОБЯЗАТЕЛЬНЫЙ СУБ-СКИЛ: `superpowers:subagent-driven-development` (рекомендуется) или `superpowers:executing-plans`. Задачи выполняются строго по порядку. Шаги — чекбоксы (`- [ ]`).

**Цель:** ролик перестаёт провисать — паузы речи вырезаются, каждые 3 секунды в кадре что-то происходит, материал вставок приходит из маршрутов/снимков/media-use по приоритету, а агентская сессия сборки попадает в биллинг.

**Архитектура:** та же, что в переезде (план `2026-07-28-hyperframes-migration.md`): монтажные решения — скилы HeyGen, наш код — обвязка. Этот план только расширяет обвязку: планировщик назначает больше материала, гейты требуют ритм, мастер-звук режет паузы до заказа аватара, стоимость compose-сессии пишется в журнал.

**Технологии:** Python 3.11, pytest, ffmpeg, headless Claude (скилы HeyGen), движок `hyperframes@0.7.70` (жёстко).

## Решения заказчика, которые план фиксирует (Вася, 2026-07-29)

1. **Хук — это первые 3–4 секунды ролика, а не весь сценарный блок `role="hook"`.** Запрет прятать ведущую сужается до этого окна времени.
2. **Приоритет материала окна** (арбитр — планировщик, один материал на окно): экранный маршрут → снимок сайта → media-use (сток/генерация). Библиотека клиента из приоритетов исключена — бот материалы не собирает. **Каждый источник показывается в ролике один раз, без повторов.**
3. **Правило «каждые 3 секунды»** возвращается гейтом: дыра без событий длиннее 3 с — брак раскадровки.
4. **Паузорезка возвращается в мастер-звук** (взамен мёртвых jump_cuts — их флаг остаётся мёртвым до уборки).
5. **D6_broll_bed переводится в SKIP** — фоновой дорожки в новом пути нет.
6. **Граундинг НЕ ужесточаем** — только считаем статистику на живых прогонах.
7. Уборка (старый рендер, жёлтый, флаги-пустышки) — отдельным планом №2, самой последней.

## Глобальные ограничения

- Кадр **1080×1920, 30 кадров/с**; все тайминги кратны 1/30 с; громкость −14 LUFS / −1.5 TP.
- Версия движка **жёстко 0.7.70**; облачный рендер не используем; внутри карточек только локальные файлы; шрифты Montserrat/Inter.
- Стиль `minimal`, заморожен. Единственное правило поверх скила — не перекрывать лицо ведущей.
- Ветка: **`feat/vasya-hyperframes`** (продолжаем ту же). Коммит после каждой задачи.
- Тесты: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest -q -m "not slow"` — системный python пакет не видит. База на старте плана: **684 passed**.
- Числа «N passed» в шагах посчитаны рассуждением. Если тест ведёт себя иначе — сверься с кодом репозитория и правь план, а не подгоняй код.

## Установленные факты (проверены разведкой 2026-07-29, перепроверять не нужно)

- `MasterAudioArtifacts` (frozen): `wav, mp3, block_wavs, words, timed_scenario, canonical, manifest` (`master_audio.py:37-45`). `build_master_audio(scenario, config, workdir, *, voice_id=None, provider=None, run_cmd=None, duration_fn=None, meter=None)` (`:289-427`): один запрос ElevenLabs → mp3→wav (ffmpeg через `run_cmd`) → `alignment_to_words` (`:344-346`) → `_block_audio_ranges` (`:347`, граница блоков = середина зазора речи) → `timed_scenario` (`:348-356`) → нарезка `block_wavs` (`:358-368`) → манифесты (`:370-417`).
- Ключи слова: `id, block_id, block_index, role, character_start, character_end, start, end, text` (`master_audio.py:211-221`).
- `pipeline.py` потребляет: `master.block_wavs` (`:246`), `finalize_edit_plan(edit_plan, master.timed_scenario, list(master.words))` (`:270-274`), sha256 мастер-wav в план рендера аватара (`:283`), `avatar_render_fn(master.wav, ...)` (`:291`), сборка (`:359-367`). Паузорезка обязана случиться **внутри** `build_master_audio` — до sha и до заказа аватара, чтобы губы совпали с уже порезанным звуком.
- Старые резалки пауз (`edit.py:52,80,134`, auto-editor/silencedetect) режут готовые фрагменты и не двигают words/timed_scenario — не переиспользуются; примитивы `editplan.detect_silences` (`editplan.py:60`) не нужны: у нас есть точные пословные тайминги.
- Запрет прятать ведущую сейчас **по роли блока**: `editplan.py:2558-2562` (hook/cta), `:2575-2579` (visual director в hook/cta), `:2596-2599` (bubble), `:2850-2851` (apply-рекомендации), `:2756` (кандидаты в prompt LLM). Комментарий в `_assign_window` (`:1390`) ссылается на устаревшие номера.
- `enrich_visuals_with_llm(plan, runner)` (`editplan.py:3311-3336`), prompt строит `visual_analysis_prompt`, применение — `apply_visual_recommendations(plan, parsed, source="llm", strict=False)`; вызывается из `pipeline.py:181-189` при `config.edit_plan.visual_director.llm.enabled`.
- `material_for_phrase` (`editplan.py:1320-1347`), `_prepare_material` (`hf_render.py:167-202`). Ключи окна после `_assign_window`: `id, phrase_ids, block_id, block_index, role, visual_intent, coverage, asset, fallback, decision_reason, estimated_timing, final_timing, camera, zone, material, transition_in, caption, effect, safe_to_skip_avatar` (`editplan.py:1370-1398`).
- `check_storyboard(storyboard, face, faceless_windows=None) -> dict` возвращает `D8_face..D12_faceless_cover` (`hf_gates.py:14-15, 76-78`), значения `"PASS"` / `"FAIL: ..."`.
- D6: avatar-ветка `verify.py:148-159`, split-ветка `:160-176`; `qa = {"all_pass", "gates"}` (`:184-185`); SKIP не проваливает all_pass.
- Биллинг: `LedgerStore.charge(chat_id, *, entry_id, job_id, provider, unit, quantity, unit_price_micro, cost_micro, charged_micro, meta=None)` идемпотентен по entry_id (`billing.py:118-146`); `JobMeter` (`billing.py:323-394`), `entry_id = f"{job_id}:{run_id}:{provider}:{step}"` (`:357`); **`JobMeter.claude(usd)` существует (`:388-391`), но не вызывается никем**; `claude_cost_micro(usd)=to_micro(usd)` (`:292-294`). Чек бота — `job_breakdown(job_id)` (`billing.py:242-253`, `bot.py:1484-1502`): трата с job_id попадёт в чек автоматически.
- `run_make(..., meter=None)` (`pipeline.py:81-88`); метер создаётся в `__main__.py:91-95,111`. Вызов сборки: `assemble_fn(wd, master.timed_scenario, edit_plan=..., avatar_mp4s=..., master_audio=master.wav, alignment_words=..., avatar_render_plan=..., out_mp4=...)` (`pipeline.py:359-367`) — `agent_runner` и `meter` туда не передаются, `res["agent_cost_usd"]` выбрасывается.
- `HeyGenAgentRunner` (`hf_agent.py`): `-p --output-format json --permission-mode acceptEdits`, таймаут 1800 с, подхват `CLAUDE_CODE_OAUTH_TOKEN` из `~/.reels-factory/oauth-token`. Демо-сессия на 14 окон не уложилась в 30 минут и стоила $9.79 — наблюдаемость и учёт обязательны.
- `write_brief(rdir, plan, *, face, duration, clips=None, media=None, retry_reason=None)` (`hf_brief.py`); free_bands(None) сейчас отдаёт полосу на весь кадр (противоречие с face_line — чинится задачей 8).

## Структура файлов

| Файл | Ответственность |
|---|---|
| `src/reels_factory/master_audio.py` | + `trim_master_pauses` — паузорезка с пересдвигом words |
| `src/reels_factory/editplan.py` | Хук по времени; `fill_material_by_rhythm` — материал в дыры по приоритету |
| `src/reels_factory/hf_media.py` (новый) | Сток/генерация через media-use-сессию, кэш |
| `src/reels_factory/hf_gates.py` | + гейт `D13_rhythm` |
| `src/reels_factory/hf_brief.py` | Правило ритма в BRIEF |
| `src/reels_factory/hf_agent.py` | Лог сессии `agent.log`, конфигурируемый таймаут |
| `src/reels_factory/hf_render.py` | kind="stock" в `_prepare_material` |
| `src/reels_factory/verify.py` | D6 → SKIP |
| `src/reels_factory/face_detect.py` | free_bands(None) без противоречия |
| `src/reels_factory/visual_grounding.py` | Строка статистики в log |
| `src/reels_factory/pipeline.py` | agent_runner + meter.claude в сборке |
| `src/reels_factory/billing.py` | `JobMeter.claude(usd, step=...)` |

---

## Фаза А — где ведущая обязана быть в кадре

### Задача 1: Хук — первые 4 секунды, а не весь блок

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/editplan.py` (`:2558-2562`, `:2575-2579`, `:2596-2599`, `:2850-2851`, prompt-кандидаты `:2756`)
- Изменить: `plugins/reels-factory/engine/tests/test_editplan.py`

**Интерфейсы:**
- Производит: `HOOK_GUARD_S = 4.0`, `_in_hook_guard(window) -> bool` (по `final_timing`, при его отсутствии `estimated_timing`).
- CTA-запрет остаётся **по роли** — призыв в конце, его время плавает.

- [ ] **Шаг 1: Написать падающий тест**

Дописать в `tests/test_editplan.py`:

```python
def test_хвост_длинного_хука_разрешает_показ():
    """Хук — первые 4 секунды. Дальше кадр можно отдавать показу."""
    from reels_factory.editplan import validate_edit_plan

    plan = {
        "format_version": 1, "status": "draft",
        "script": {"language": "ru"},
        "timeline": {"final_duration_seconds": 12.0},
        "blocks": [], "log": [],
        "phrases": [{"id": "p1", "text": "показываем", "block_index": 0,
                     "role": "hook", "coverage": "hyperframes",
                     "window_id": "w1"}],
        "windows": [{"id": "w1", "phrase_ids": ["p1"], "block_index": 0,
                     "role": "hook", "coverage": "hyperframes",
                     "zone": "fullscreen",
                     "final_timing": {"start": 6.0, "end": 9.0},
                     "effect": {"type": "chart_bars",
                                "hyperframes": {"block": "task_list"}}}],
    }
    report = validate_edit_plan(plan, require_final=False,
                                require_asset_files=False)
    assert not any("hook" in e for e in report["errors"])


def test_первые_секунды_прятать_ведущую_нельзя():
    from reels_factory.editplan import validate_edit_plan

    plan = {
        "format_version": 1, "status": "draft",
        "script": {"language": "ru"},
        "timeline": {"final_duration_seconds": 12.0},
        "blocks": [], "log": [],
        "phrases": [{"id": "p1", "text": "старт", "block_index": 0,
                     "role": "hook", "coverage": "hyperframes",
                     "window_id": "w1"}],
        "windows": [{"id": "w1", "phrase_ids": ["p1"], "block_index": 0,
                     "role": "hook", "coverage": "hyperframes",
                     "zone": "fullscreen",
                     "final_timing": {"start": 0.0, "end": 3.0},
                     "effect": {"type": "chart_bars",
                                "hyperframes": {"block": "task_list"}}}],
    }
    report = validate_edit_plan(plan, require_final=False,
                                require_asset_files=False)
    assert any("хук" in e or "hook" in e for e in report["errors"])
```

- [ ] **Шаг 2: Запустить, убедиться что первый падает**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_editplan.py -k "хвост or прятать" -v`
Ожидание: `test_хвост_длинного_хука_разрешает_показ` FAIL (сейчас запрет по роли), второй PASS.

- [ ] **Шаг 3: Реализация**

В `editplan.py` рядом с `_zone_for` добавить:

```python
# Хук как продуктовое окно — первые секунды ролика, а не сценарный блок:
# блок role="hook" бывает длиной 12 секунд, и его хвост — обычная речь,
# где кадр можно отдать показу. Решение Васи 2026-07-29.
HOOK_GUARD_S = 4.0


def _in_hook_guard(window: dict) -> bool:
    timing = window.get("final_timing") or window.get("estimated_timing") or {}
    return float(timing.get("start", 0.0) or 0.0) < HOOK_GUARD_S
```

Правки четырёх мест (роль → время; CTA не трогать):
- `:2558-2560`: условие `role == "hook" and coverage not in {"avatar", "mixed"}` заменить на `_in_hook_guard(window) and coverage not in {"avatar", "mixed"}`; текст ошибки: `f'{window["id"]}: первые {HOOK_GUARD_S:g} секунды — хук, ведущую прятать нельзя'`.
- `:2575-2579` (visual director) и `:2596-2599` (bubble): ту же половину условия про hook заменить на `_in_hook_guard(window)`; половину про cta оставить.
- `:2850-2851` (apply-рекомендации): `any(phrase.get("role") == "cta" ...)` оставить, проверку hook заменить проверкой времени окна кандидата: `_in_hook_guard(window)` — словарь окна там уже есть.
- `:2756` (кандидаты в LLM-prompt): исключение hook-кандидатов заменить исключением окон с `_in_hook_guard(window)`; cta-исключение оставить.

- [ ] **Шаг 4: Прогнать набор**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_editplan.py -q`
Ожидание: зелено. Существующие тесты «hook нельзя скрывать» используют окна с ранним стартом — если какой-то падает из-за окна, стартующего позже 4 с, это находка: перечитай тест и поправь его фикстуру осмысленно (окно в первых секундах), а не правило.

- [ ] **Шаг 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/editplan.py plugins/reels-factory/engine/tests/test_editplan.py
git commit -m "feat(editplan): hook guard is the first four seconds, not the block"
```

---

### Задача 2: Сток и генерация через media-use (`hf_media.py`)

**Файлы:**
- Создать: `plugins/reels-factory/engine/src/reels_factory/hf_media.py`
- Создать: `plugins/reels-factory/engine/tests/test_hf_media.py`
- Изменить: `plugins/reels-factory/engine/src/reels_factory/hf_render.py` (`_prepare_material`, `:167-202`)

**Интерфейсы:**
- Производит: `resolve_stock(query: str, out_dir, *, runner=None) -> Path` — вертикальный медиафайл по запросу; `stock_cache_dir() -> Path` (`~/.reels-factory/stock-cache`); кэш по sha1 запроса.
- Потребляет: `hf_agent.HeyGenAgentRunner` (обычный профиль — скил media-use виден).
- `_prepare_material` получает ветку `kind == "stock"`: файл кладётся в `public/media/{window_id}-stock{suffix}`.

**Почему сессия, а не библиотека:** media-use — скил (инструкция агенту), как и hyperframes. Заходим отдельной короткой сессией с узким заданием: найти или сгенерировать один файл. Решение «что искать» уже принято планировщиком — агент только исполняет.

- [ ] **Шаг 1: Написать падающий тест**

Создать `tests/test_hf_media.py`:

```python
"""Сток/генерация через media-use: узкая сессия, кэш по запросу."""
from pathlib import Path

import pytest

from reels_factory.hf_media import resolve_stock


class _Runner:
    def __init__(self, target_dir, make_file=True):
        self.target_dir, self.make_file, self.prompts = target_dir, make_file, []
        self.total_cost_usd = 0.0

    def run(self, prompt, cwd=None):
        self.prompts.append(prompt)
        if self.make_file:
            out = Path(cwd) / "stock.png"
            out.write_bytes(b"png")
        return "готово"


def test_вход_через_media_use(tmp_path):
    runner = _Runner(tmp_path)
    resolve_stock("нейросеть озвучка", tmp_path, runner=runner)
    assert runner.prompts and "/media-use" in runner.prompts[0]
    assert "нейросеть озвучка" in runner.prompts[0]
    assert "1080" in runner.prompts[0] and "1920" in runner.prompts[0]


def test_файл_возвращается_и_кэшируется(tmp_path):
    runner = _Runner(tmp_path)
    first = resolve_stock("нейросеть озвучка", tmp_path, runner=runner)
    assert first.exists()
    second = resolve_stock("нейросеть озвучка", tmp_path, runner=runner)
    assert second == first
    assert len(runner.prompts) == 1, "кэш-хит не должен звать агента"


def test_разные_запросы_не_путаются(tmp_path):
    runner = _Runner(tmp_path)
    a = resolve_stock("город ночью", tmp_path, runner=runner)
    b = resolve_stock("график роста", tmp_path, runner=runner)
    assert a != b


def test_сессия_без_файла_это_ошибка(tmp_path):
    with pytest.raises(RuntimeError, match="media-use"):
        resolve_stock("пустота", tmp_path, runner=_Runner(tmp_path, make_file=False))
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_hf_media.py -v`
Ожидание: FAIL — модуля нет.

- [ ] **Шаг 3: Реализация**

Создать `src/reels_factory/hf_media.py`:

```python
"""Сток и генерация медиа через скил media-use.

Планировщик уже решил, ЧТО показать (запрос). Здесь узкая агентская сессия
находит или генерирует один вертикальный файл. Кэш — по запросу: одна тема
не должна оплачиваться и искаться дважды.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

_MEDIA_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm")

PROMPT = """/media-use

Найди или сгенерируй ОДИН вертикальный медиафайл (изображение или короткое
видео) под кадр 1080×1920 по запросу: «{query}».

Требования:
- файл сохрани в текущую папку; ровно один файл, никаких превью и вариантов;
- без текста и водяных знаков в кадре;
- ничего не спрашивай, реши сам и закончи.
"""


def stock_cache_dir() -> Path:
    return Path.home() / ".reels-factory" / "stock-cache"


def _cache_key(query: str) -> str:
    return hashlib.sha1(" ".join(query.lower().split()).encode("utf-8")).hexdigest()[:16]


def _find_media(directory: Path) -> Path | None:
    files = [p for p in sorted(directory.iterdir())
             if p.suffix.lower() in _MEDIA_SUFFIXES]
    return files[0] if files else None


def resolve_stock(query: str, work_dir, *, runner=None) -> Path:
    """Файл по запросу: из кэша либо новой media-use-сессией."""
    from reels_factory.hf_agent import HeyGenAgentRunner

    cache = stock_cache_dir() / _cache_key(query)
    cached = _find_media(cache) if cache.exists() else None
    if cached is not None:
        return cached

    session_dir = Path(work_dir) / f"stock-{_cache_key(query)}"
    session_dir.mkdir(parents=True, exist_ok=True)
    runner = runner or HeyGenAgentRunner()
    runner.run(PROMPT.format(query=query), cwd=session_dir)

    found = _find_media(session_dir)
    if found is None:
        raise RuntimeError(
            f"media-use не вернул файла по запросу «{query}» в {session_dir}")
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / found.name
    shutil.copyfile(found, target)
    return target
```

- [ ] **Шаг 4: Запустить тесты модуля**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_hf_media.py -v`
Ожидание: 4 passed.

- [ ] **Шаг 5: Ветка stock в `_prepare_material`**

В `hf_render.py`, в `_prepare_material` (`:167-202`), рядом с ветками `site`/`route` добавить (импорт `hf_media` — внутри функции, по образцу соседних):

```python
            elif kind == "stock":
                from reels_factory import hf_media

                source = hf_media.resolve_stock(
                    str(material.get("query") or ""), rdir)
                target = public / "media" / f"{window_id}-stock{Path(source).suffix}"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                media.append({"file": f"media/{target.name}",
                              "window_id": window_id,
                              "what": window.get("visual_intent")
                              or f"сток: {material.get('query')}"})
```

Дописать в `tests/test_hf_render.py` тест по образцу соседних тестов подготовки материала (мок `hf_media.resolve_stock` через `monkeypatch.setattr`, окно с `material={"kind": "stock", "query": "город ночью"}`, ассерт: файл в `public/media/`, запись в `media.json` содержит `stock`).

- [ ] **Шаг 6: Прогнать весь набор**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest -q -m "not slow"`
Ожидание: зелено (684 + 5 новых).

- [ ] **Шаг 7: Живая проверка (один запрос, дёшево)**

```bash
cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -c "from reels_factory.hf_media import resolve_stock; print(resolve_stock('вертикальный кадр город ночью', 'C:/tmp/stock-probe'))"
```
Ожидание: путь к файлу. Повторный запуск — тот же путь без новой сессии.

- [ ] **Шаг 8: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/hf_media.py plugins/reels-factory/engine/tests/test_hf_media.py plugins/reels-factory/engine/src/reels_factory/hf_render.py plugins/reels-factory/engine/tests/test_hf_render.py
git commit -m "feat(media): stock material through a narrow media-use session"
```

---

### Задача 3: Материал в дыры по приоритету (планировщик)

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/editplan.py`
- Изменить: `plugins/reels-factory/engine/tests/test_editplan.py`

**Интерфейсы:**
- Производит: `fill_material_by_rhythm(plan: dict, *, max_gap_s: float = 3.0) -> dict` — чистая функция, зовётся в `finalize_edit_plan` **после** ретайминга окон и **до** `enforce_visual_grounding`.
- Правило: окно длиннее `max_gap_s` без события (эффект `none`/нет, материала нет, покрытие avatar) и вне хук-гарда/CTA получает `material` по приоритету: **маршрут → сайт → сток**; сток-запрос — три самых длинных слова речи окна.
- **Дедуп:** один и тот же источник (url сайта / шаги маршрута / сток-запрос) не назначается дважды за ролик; окна, где источник уже занят, переходят к следующему приоритету.

- [ ] **Шаг 1: Написать падающий тест**

Дописать в `tests/test_editplan.py`:

```python
def _rhythm_plan(windows):
    return {"phrases": [{"id": f"p{i}", "text": w.pop("_speech"),
                         "window_id": w["id"]} for i, w in enumerate(windows)],
            "windows": windows, "blocks": [], "log": []}


def test_дыра_получает_материал_по_приоритету():
    from reels_factory.editplan import fill_material_by_rhythm

    plan = _rhythm_plan([
        {"id": "w1", "phrase_ids": ["p0"], "role": "development",
         "coverage": "avatar", "effect": {"type": "none"}, "material": None,
         "final_timing": {"start": 6.0, "end": 11.0},
         "_speech": "зайди на elevenlabs точка ай о и посмотри сам"},
    ])
    out = fill_material_by_rhythm(plan)
    assert out["windows"][0]["material"]["kind"] == "site"


def test_дыра_без_предмета_получает_сток():
    from reels_factory.editplan import fill_material_by_rhythm

    plan = _rhythm_plan([
        {"id": "w1", "phrase_ids": ["p0"], "role": "development",
         "coverage": "avatar", "effect": {"type": "none"}, "material": None,
         "final_timing": {"start": 6.0, "end": 11.0},
         "_speech": "усложняем продажи изучаем хитрые приёмы"},
    ])
    material = fill_material_by_rhythm(plan)["windows"][0]["material"]
    assert material["kind"] == "stock"
    assert "усложняем" in material["query"]


def test_источник_не_повторяется():
    from reels_factory.editplan import fill_material_by_rhythm

    speech = "зайди на elevenlabs точка ай о и попробуй"
    plan = _rhythm_plan([
        {"id": "w1", "phrase_ids": ["p0"], "role": "development",
         "coverage": "avatar", "effect": {"type": "none"}, "material": None,
         "final_timing": {"start": 6.0, "end": 11.0}, "_speech": speech},
        {"id": "w2", "phrase_ids": ["p1"], "role": "development",
         "coverage": "avatar", "effect": {"type": "none"}, "material": None,
         "final_timing": {"start": 20.0, "end": 25.0}, "_speech": speech},
    ])
    out = fill_material_by_rhythm(plan)
    kinds = [w["material"]["kind"] for w in out["windows"]]
    assert kinds[0] == "site"
    assert kinds[1] == "stock", "сайт уже показан — второй раз нельзя"


def test_хук_и_короткие_окна_не_трогаются():
    from reels_factory.editplan import fill_material_by_rhythm

    plan = _rhythm_plan([
        {"id": "w1", "phrase_ids": ["p0"], "role": "hook",
         "coverage": "avatar", "effect": {"type": "none"}, "material": None,
         "final_timing": {"start": 0.0, "end": 3.5},
         "_speech": "зайди на elevenlabs точка ай о"},
        {"id": "w2", "phrase_ids": ["p1"], "role": "development",
         "coverage": "avatar", "effect": {"type": "none"}, "material": None,
         "final_timing": {"start": 6.0, "end": 8.0},
         "_speech": "короткое окно"},
    ])
    out = fill_material_by_rhythm(plan)
    assert out["windows"][0]["material"] is None
    assert out["windows"][1]["material"] is None


def test_окно_с_событием_не_трогается():
    from reels_factory.editplan import fill_material_by_rhythm

    plan = _rhythm_plan([
        {"id": "w1", "phrase_ids": ["p0"], "role": "development",
         "coverage": "hyperframes", "material": None,
         "effect": {"type": "chart_bars"},
         "final_timing": {"start": 6.0, "end": 11.0},
         "_speech": "зайди на elevenlabs точка ай о"},
    ])
    assert fill_material_by_rhythm(plan)["windows"][0]["material"] is None
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_editplan.py -k "дыра or источник_не_повтор or хук_и_короткие or окно_с_событием" -v`
Ожидание: FAIL — функции нет.

- [ ] **Шаг 3: Реализация**

В `editplan.py`, рядом с `material_for_phrase`:

```python
_STOCK_WORD_RE = re.compile(r"[А-Яа-яЁёA-Za-z]{5,}")


def _stock_query(text: str) -> str | None:
    """Три самых длинных слова речи — тема для стока.

    Сортировка вторично по алфавиту: set не гарантирует порядок между
    запусками, а недетерминированный запрос ломал бы кэш стока.
    """
    words = sorted({w.lower() for w in _STOCK_WORD_RE.findall(str(text or ""))},
                   key=lambda w: (-len(w), w))[:3]
    return " ".join(words) or None


def _material_key(material: dict) -> str:
    if material.get("kind") == "site":
        return f'site:{material.get("url")}'
    if material.get("kind") == "route":
        return "route:" + "|".join(
            str(s.get("url") or s.get("selector") or s.get("type"))
            for s in material.get("steps") or [])
    return f'stock:{material.get("query")}'


def fill_material_by_rhythm(plan: dict, *, max_gap_s: float = 3.0) -> dict:
    """Назначить материал окнам-дырам: ролик не молчит картинкой дольше 3 с.

    Приоритет источника (решение Васи 2026-07-29): маршрут → сайт → сток.
    Один источник — один раз за ролик; занятый источник уступает следующему.
    Хук-гард и CTA не трогаем: там ведущая работает лицом.
    """
    result = copy.deepcopy(plan)
    text_by_id = {p["id"]: p.get("text", "") for p in result.get("phrases") or []}
    used: set[str] = set()
    for window in result.get("windows") or []:
        if window.get("material"):
            used.add(_material_key(window["material"]))

    for window in result.get("windows") or []:
        timing = window.get("final_timing") or {}
        length = float(timing.get("end", 0.0)) - float(timing.get("start", 0.0))
        effect = (window.get("effect") or {}).get("type")
        busy = (effect and effect != "none") or window.get("material")
        if (busy or length <= max_gap_s or window.get("role") == "cta"
                or _in_hook_guard(window)):
            continue
        speech = " ".join(text_by_id.get(pid, "")
                          for pid in window.get("phrase_ids") or [])
        candidates = []
        primary = material_for_phrase(speech)
        if primary and primary.get("kind") == "route":
            candidates.append(primary)
        if primary and primary.get("kind") == "site":
            candidates.append(primary)
        query = _stock_query(speech)
        if query:
            candidates.append({"kind": "stock", "query": query})
        for material in candidates:
            key = _material_key(material)
            if key in used:
                continue
            window["material"] = material
            window["decision_reason"] = (
                f"Ритм: окно {length:.1f} с без событий, источник {material['kind']}")
            used.add(key)
            result.setdefault("log", []).append(
                f'{window["id"]}: ритм-материал {material["kind"]}')
            break
    return result
```

Подключение в `finalize_edit_plan`: сразу **перед** вызовом `enforce_visual_grounding(result)` (поставлен задачей 4 переезда):

```python
    result = fill_material_by_rhythm(result)
```

- [ ] **Шаг 4: Прогнать весь набор**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest -q -m "not slow"`
Ожидание: зелено. Если существующая фикстура получила неожиданный материал — проверь, что окно реально длиннее 3 с и пустое: это правило работает, поправь ожидание теста осмысленно.

- [ ] **Шаг 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/editplan.py plugins/reels-factory/engine/tests/test_editplan.py
git commit -m "feat(editplan): fill silent gaps with material by priority"
```

---

### Задача 4: Гейт ритма D13 и правило в BRIEF

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/hf_gates.py`
- Изменить: `plugins/reels-factory/engine/src/reels_factory/hf_brief.py`
- Изменить: `plugins/reels-factory/engine/tests/test_hf_gates.py`, `tests/test_hf_brief.py`

**Интерфейсы:**
- `check_storyboard(storyboard, face, faceless_windows=None, *, duration=None, hook_guard_s=4.0, max_gap_s=3.0)` — новый гейт `D13_rhythm`: на отрезке `[hook_guard_s, duration]` зазор между соседними карточками (по `startSec`/`endSec`, любые зоны) не больше `max_gap_s`. Без `duration` гейт возвращает `"SKIP(нет длительности)"`.
- `hf_render.assemble_hyperframes` передаёт `duration=quantize(total)` в оба вызова `check_storyboard`.
- BRIEF получает раздел «Ритм».

- [ ] **Шаг 1: Написать падающий тест**

Дописать в `tests/test_hf_gates.py`:

```python
def test_ритм_ловит_дыру_длиннее_трёх_секунд():
    cards = [_card(id="c1", startSec=4.0, endSec=7.0)]
    gates = check_storyboard({"cards": cards}, FACE, duration=41.5)
    assert gates["D13_rhythm"].startswith("FAIL")
    assert "7" in gates["D13_rhythm"]


def test_ритм_проходит_при_плотной_раскадровке():
    cards = [
        _card(id="c1", startSec=4.0, endSec=9.0),
        _card(id="c2", startSec=11.0, endSec=16.0),
        _card(id="c3", startSec=18.0, endSec=24.0),
        _card(id="c4", startSec=26.0, endSec=32.0),
        _card(id="c5", startSec=34.0, endSec=41.5),
    ]
    gates = check_storyboard({"cards": cards}, FACE, duration=41.5)
    assert gates["D13_rhythm"] == "PASS"


def test_хук_гард_ритмом_не_проверяется():
    """Первые 4 секунды — ведущая без карточек, это не дыра."""
    cards = [
        _card(id="c1", startSec=4.0, endSec=9.0),
        _card(id="c2", startSec=11.0, endSec=16.0),
        _card(id="c3", startSec=18.0, endSec=24.0),
        _card(id="c4", startSec=26.0, endSec=32.0),
        _card(id="c5", startSec=34.0, endSec=41.5),
    ]
    gates = check_storyboard({"cards": cards}, FACE, duration=41.5)
    assert gates["D13_rhythm"] == "PASS"


def test_без_длительности_ритм_пропускается():
    gates = check_storyboard({"cards": [_card()]}, FACE)
    assert gates["D13_rhythm"].startswith("SKIP")
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_hf_gates.py -k ритм -v`
Ожидание: FAIL — гейта нет (TypeError по duration).

- [ ] **Шаг 3: Реализация гейта**

В `hf_gates.py` сигнатуру расширить и перед `def gate(...)` добавить:

```python
def check_storyboard(storyboard: dict, face: dict | None,
                     faceless_windows: list[dict] | None = None, *,
                     duration: float | None = None,
                     hook_guard_s: float = 4.0,
                     max_gap_s: float = 3.0) -> dict:
```

```python
    rhythm_bad: list[str] = []
    rhythm_skip = duration is None
    if not rhythm_skip:
        spans = sorted(
            (float(c.get("startSec", 0)), float(c.get("endSec", 0)))
            for c in storyboard.get("cards") or [])
        cursor = hook_guard_s
        for span_start, span_end in spans:
            if span_start - cursor > max_gap_s + 0.001:
                rhythm_bad.append(
                    f"дыра {cursor:g}–{span_start:g} с без событий")
            cursor = max(cursor, span_end)
        if float(duration) - cursor > max_gap_s + 0.001:
            rhythm_bad.append(f"дыра {cursor:g}–{float(duration):g} с в хвосте")
```

И в возвращаемый словарь добавить ключ:

```python
            "D13_rhythm": ("SKIP(нет длительности)" if rhythm_skip
                           else gate(rhythm_bad)),
```

В `hf_render.assemble_hyperframes` оба вызова `check_storyboard(...)` дополнить `duration=duration` (переменная уже посчитана как `quantize(total)`).

**Важно про существующие тесты:** старые тесты `test_hf_gates.py` зовут гейты без `duration` — им достанется `SKIP`, ничего не сломается. Тесты `test_hf_render.py` с фейковыми раскадровками получат `duration=6.0` при пустых `cards` — дыра 4.0–6.0 короче 3 с не будет… 6.0−4.0=2.0 ≤ 3 — PASS; проверь фактические длительности фейков, при провале поправь фикстуру осмысленно (карточка или короче ролик), а не гейт.

- [ ] **Шаг 4: Правило ритма в BRIEF**

В `hf_brief.py`, в раздел «Жёсткие границы» шаблона, после пункта про окна без ведущей добавить строку:

```python
- **Ритм: не оставляй экран без событий дольше 3 секунд** (кроме первых
  4 секунд — там хук, ведущая работает лицом, и карточки не нужны).
  Событие — карточка в любой зоне. Материал для окон-дыр уже приготовлен
  и перечислен в разделе «Материал для вставок» — используй его.
```

Дописать в `tests/test_hf_brief.py`:

```python
def test_правило_ритма_в_задании(tmp_path):
    text = _text(tmp_path)
    assert "3 секунд" in text
    assert "ритм" in text.lower()
```

- [ ] **Шаг 5: Прогнать весь набор**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest -q -m "not slow"`
Ожидание: зелено.

- [ ] **Шаг 6: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/hf_gates.py plugins/reels-factory/engine/src/reels_factory/hf_brief.py plugins/reels-factory/engine/src/reels_factory/hf_render.py plugins/reels-factory/engine/tests/test_hf_gates.py plugins/reels-factory/engine/tests/test_hf_brief.py
git commit -m "feat(hf): rhythm gate — no dead screen longer than three seconds"
```

---

### Задача 5: LLM-директор предлагает оверлеи для оставшихся дыр

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/editplan.py` (`visual_analysis_prompt`)
- Изменить: `plugins/reels-factory/engine/tests/test_editplan.py`

**Зачем:** материал (задача 3) закрывает дыры, где есть предмет показа. Где предмета нет (чистая риторика), единственное разрешённое событие — оверлей-карточка поверх ведущей. Их придумывает LLM-директор; правило — подсказать ему это в промпте. Существующий механизм применения (`apply_visual_recommendations`, `source="llm"`, граундинг) не меняется.

- [ ] **Шаг 1: Написать падающий тест**

Дописать в `tests/test_editplan.py`:

```python
def test_промпт_директора_просит_закрывать_дыры_оверлеями():
    from reels_factory.editplan import visual_analysis_prompt

    plan = {"phrases": [], "windows": [], "blocks": [], "log": []}
    prompt = visual_analysis_prompt(plan)
    assert "3 секунд" in prompt
    assert "оверле" in prompt.lower() or "video-overlay" in prompt
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_editplan.py -k промпт_директора -v`
Ожидание: FAIL.

- [ ] **Шаг 3: Реализация**

В `visual_analysis_prompt` (рядом с существующими правилами отбора кандидатов) добавить абзац-инструкцию:

```python
    "Ролик не должен молчать картинкой дольше 3 секунд. Если между "
    "вставками остаётся окно длиннее 3 секунд без события и без материала — "
    "предложи для него оверлей-карточку (зона video-overlay, ведущая остаётся "
    "в кадре): ключевая фраза, число или короткий список ИЗ ПРОЗВУЧАВШИХ "
    "слов этого окна. Первые 4 секунды ролика и призыв не трогай."
```

Точное место — тем же стилем, что соседние строки промпта (посмотри, как собирается текст: конкатенация строк или f-string, и повтори его).

- [ ] **Шаг 4: Прогнать набор и коммит**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_editplan.py -q`
Ожидание: зелено.

```bash
git add plugins/reels-factory/engine/src/reels_factory/editplan.py plugins/reels-factory/engine/tests/test_editplan.py
git commit -m "feat(editplan): llm director fills remaining gaps with overlays"
```

---

## Фаза Б — паузорезка

### Задача 6: Мастер-звук режет паузы до заказа аватара

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/master_audio.py`
- Изменить: `plugins/reels-factory/engine/tests/test_master_audio.py`
- Изменить: `plugins/reels-factory/templates/config.example.yaml` (секция `master_audio`)

**Интерфейсы:**
- Производит: `trim_master_pauses(words: list[dict], duration: float, *, min_silence_s: float = 0.45, keep_s: float = 0.18) -> tuple[list[dict], float, list[tuple[float, float]]]` — чистая функция: новые слова (пересдвинутые), новая длительность, список вырезанных интервалов `(start, end)` в координатах ИСХОДНОГО звука.
- Врезка в `build_master_audio`: после `alignment_to_words` (`:344-346`) и **до** `_block_audio_ranges` (`:347`); wav перерезается ffmpeg-ом через существующий `run_cmd`; дальше все шаги (`timed_scenario`, `block_wavs`, манифест) идут по новым словам и новому wav — то есть аватар HeyGen заказывается уже под порезанный звук, губы совпадают.
- Конфиг: `master_audio.trim_pauses: {enabled: true, min_silence_s: 0.45}`; перекрытие окружением `RF_TRIM_PAUSES=0/1`.
- Паузы ищутся **по пословным таймингам** (зазор `next.start - prev.end > min_silence_s`), не по silencedetect: тайминги точнее и уже есть. С каждой стороны выреза остаётся хвост `keep_s` — речь не обрубается впритык.

- [ ] **Шаг 1: Написать падающий тест**

Дописать в `tests/test_master_audio.py`:

```python
def _w(start, end, text):
    return {"id": f"w{start}", "block_id": "b0", "block_index": 0,
            "role": "hook", "character_start": 0, "character_end": 1,
            "start": start, "end": end, "text": text}


def test_паузы_вырезаются_с_пересдвигом_слов():
    from reels_factory.master_audio import trim_master_pauses

    words = [_w(0.0, 1.0, "раз"), _w(2.0, 3.0, "два"), _w(3.1, 4.0, "три")]
    new_words, new_total, cuts = trim_master_pauses(words, 4.5,
                                                    min_silence_s=0.45,
                                                    keep_s=0.18)
    # пауза 1.0–2.0 длиной 1.0 с: остаются хвосты по 0.18 с, вырез 0.64 с
    assert cuts == [(1.18, 1.82)]
    assert new_words[0]["start"] == pytest.approx(0.0)
    assert new_words[1]["start"] == pytest.approx(2.0 - 0.64)
    assert new_words[2]["end"] == pytest.approx(4.0 - 0.64)
    assert new_total == pytest.approx(4.5 - 0.64)


def test_короткие_паузы_не_трогаются():
    from reels_factory.master_audio import trim_master_pauses

    words = [_w(0.0, 1.0, "раз"), _w(1.3, 2.0, "два")]
    new_words, new_total, cuts = trim_master_pauses(words, 2.5)
    assert cuts == []
    assert new_total == 2.5
    assert new_words[1]["start"] == 1.3


def test_несколько_пауз_режутся_накопительно():
    from reels_factory.master_audio import trim_master_pauses

    words = [_w(0.0, 1.0, "а"), _w(2.0, 3.0, "б"), _w(4.0, 5.0, "в")]
    new_words, new_total, cuts = trim_master_pauses(words, 5.0,
                                                    min_silence_s=0.45,
                                                    keep_s=0.18)
    assert len(cuts) == 2
    assert new_words[2]["start"] == pytest.approx(4.0 - 2 * 0.64)
    assert new_total == pytest.approx(5.0 - 2 * 0.64)


def test_хвост_после_последнего_слова_не_режется():
    """Дыхание в конце — забота ретайминга CTA, не паузорезки."""
    from reels_factory.master_audio import trim_master_pauses

    words = [_w(0.0, 1.0, "раз")]
    _, new_total, cuts = trim_master_pauses(words, 3.0)
    assert cuts == [] and new_total == 3.0
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_master_audio.py -k пауз -v`
Ожидание: FAIL — функции нет.

- [ ] **Шаг 3: Реализация чистой функции**

В `master_audio.py`:

```python
def trim_master_pauses(words, duration, *, min_silence_s: float = 0.45,
                       keep_s: float = 0.18):
    """Вырезы длинных пауз по пословным таймингам.

    Возвращает (новые слова, новая длительность, вырезы в исходных
    координатах). Вырез начинается через keep_s после конца слова и
    кончается за keep_s до начала следующего — речь не обрубается.
    """
    cuts: list[tuple[float, float]] = []
    ordered = sorted(words, key=lambda w: float(w["start"]))
    for prev, nxt in zip(ordered, ordered[1:]):
        gap = float(nxt["start"]) - float(prev["end"])
        if gap > min_silence_s:
            cuts.append((float(prev["end"]) + keep_s,
                         float(nxt["start"]) - keep_s))
    if not cuts:
        return [dict(w) for w in words], float(duration), []

    def shifted(t: float) -> float:
        removed = sum(min(t, c1) - c0 for c0, c1 in cuts if t > c0)
        return round(t - removed, 3)

    new_words = [{**w, "start": shifted(float(w["start"])),
                  "end": shifted(float(w["end"]))} for w in words]
    total_removed = sum(c1 - c0 for c0, c1 in cuts)
    return new_words, round(float(duration) - total_removed, 3), cuts
```

- [ ] **Шаг 4: Запустить чистые тесты**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_master_audio.py -k пауз -v`
Ожидание: 4 passed.

- [ ] **Шаг 5: Врезка в build_master_audio**

После `alignment_to_words` (`:344-346`), до `_block_audio_ranges`:

```python
    trim_cfg = (config.get("master_audio") or {}).get("trim_pauses") or {}
    trim_enabled = os.environ.get("RF_TRIM_PAUSES", "").strip() or (
        "1" if trim_cfg.get("enabled", True) else "0")
    if trim_enabled not in ("0", "false", "False"):
        words, duration, cuts = trim_master_pauses(
            words, duration,
            min_silence_s=float(trim_cfg.get("min_silence_s", 0.45)))
        if cuts:
            keep = _keep_intervals(cuts, original_duration)
            filter_parts = ";".join(
                f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[s{i}]"
                for i, (a, b) in enumerate(keep))
            concat_inputs = "".join(f"[s{i}]" for i in range(len(keep)))
            run_cmd([FFMPEG, "-y", "-i", str(wav),
                     "-filter_complex",
                     f"{filter_parts};{concat_inputs}concat=n={len(keep)}:v=0:a=1[out]",
                     "-map", "[out]", str(trimmed)])
            wav = trimmed  # дальше все шаги идут по порезанному файлу
```

Точная форма врезки — по фактическому коду функции: переменные `wav`, `duration`, `run_cmd` там уже есть; `original_duration` сохрани до вызова; `trimmed = workdir / "voice_master.trimmed.wav"`, после успешной резки замени исходный `voice_master.wav` порезанным (`shutil.move`), чтобы имя файла для pipeline/sha не менялось. Манифест (`audio_manifest.json`) дополни полем `"pause_cuts": cuts`. Вспомогательная функция:

```python
def _keep_intervals(cuts: list[tuple[float, float]],
                    total: float) -> list[tuple[float, float]]:
    """Дополнение вырезов: какие куски исходного звука сохраняются."""
    keep, cursor = [], 0.0
    for c0, c1 in cuts:
        if c0 - cursor > 0.01:
            keep.append((cursor, c0))
        cursor = c1
    if total - cursor > 0.01:
        keep.append((cursor, total))
    return keep
```

- [ ] **Шаг 6: Интеграционный тест врезки**

Дописать в `tests/test_master_audio.py` тест по образцу `test_build_master_audio_один_provider_request_и_полный_contract` (`:96`): фикстура выравнивания с паузой > 0.45 с между блоками, `run_cmd=fake_run` со счётчиком, `duration_fn` возвращает исходную длительность; ассерты: среди вызовов fake_run есть команда с `atrim`; `artifacts.timed_scenario["total"]` меньше исходного; `artifacts.words` пересдвинуты; `RF_TRIM_PAUSES=0` (monkeypatch.setenv) отключает резку — команд с `atrim` нет. Числа посчитай из своей фикстуры и проверь руками.

- [ ] **Шаг 7: Конфиг и полный прогон**

В `templates/config.example.yaml`, в секцию `master_audio`, добавить:

```yaml
  trim_pauses:
    enabled: true        # вырезать паузы речи длиннее min_silence_s
    min_silence_s: 0.45  # порог паузы; хвосты по 0.18 с остаются
```

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest -q -m "not slow"`
Ожидание: зелено. Тесты, считавшие 3 вызова ffmpeg в build_master_audio, при включённой резке получат больше — сверь и поправь ожидания осмысленно.

- [ ] **Шаг 8: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/master_audio.py plugins/reels-factory/engine/tests/test_master_audio.py plugins/reels-factory/templates/config.example.yaml
git commit -m "feat(audio): cut long speech pauses before avatar order"
```

---

## Фаза В — гейты и мелочи

### Задача 7: D6_broll_bed → SKIP

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/verify.py` (`:148-176`)
- Изменить: `plugins/reels-factory/engine/tests/test_verify.py`

- [ ] **Шаг 1: Написать падающий тест**

Дописать в `tests/test_verify.py`:

```python
def test_d6_всегда_skip_в_новом_пути():
    """Фоновой дорожки в HyperFrames-пути нет — мерить нечего."""
    qa = verify_reel(Path("нет.mp4"), _scenario(10.0),
                     dur_fn=lambda p: 10.0, wh_fn=lambda p: (1080, 1920, 30.0),
                     lufs_fn=lambda p: -14.0, volume_fn=lambda p, a, b: -20.0,
                     format="avatar")
    assert qa["gates"]["D6_broll_bed"].startswith("SKIP")
    assert qa["all_pass"] is True
```

(сигнатуры моков возьми из соседних тестов файла — они уже есть.)

- [ ] **Шаг 2: Реализация**

Обе ветки D6 (`verify.py:148-176`) заменить одной строкой:

```python
    gates["D6_broll_bed"] = "SKIP(фоновой дорожки в HyperFrames-пути нет)"
```

Старый код не удалять в архив — просто удалить: история в git.

- [ ] **Шаг 3: Починить старые тесты D6**

По списку из разведки: `test_d6_avatar_skip_без_вставок` (уже SKIP — оставить), `test_d6_avatar_замер_в_окне_первой_вставки`, `test_d6_avatar_тихая_вставка_фейлит`, `test_провал_по_тишине_слоя_видеоряда`, `test_тихая_сцена_не_фейлит_d6`, `test_все_гейты_проходят` (`test_verify.py:34,103-179`) — тесты замера удалить (поведение исчезло), в `test_все_гейты_проходят` ожидание `PASS` для D6 заменить на `startswith("SKIP")`.

- [ ] **Шаг 4: Прогон и коммит**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_verify.py -q && ./.venv/Scripts/python.exe -m pytest -q -m "not slow"`
Ожидание: зелено.

```bash
git add plugins/reels-factory/engine/src/reels_factory/verify.py plugins/reels-factory/engine/tests/test_verify.py
git commit -m "fix(verify): D6 broll bed is a skip — no bed track anymore"
```

---

### Задача 8: Мелочи — free_bands(None), статистика граундинга, смоук pip

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/face_detect.py` (`free_bands`)
- Изменить: `plugins/reels-factory/engine/src/reels_factory/visual_grounding.py` (строка статистики)
- Изменить: `tests/test_face_detect.py`, `tests/test_visual_grounding.py`, `tests/test_hf_gates.py`

- [ ] **Шаг 1: Написать падающие тесты**

В `tests/test_face_detect.py`:

```python
def test_без_лица_средняя_треть_запретна():
    """Раньше free_bands(None) отдавал полосу на весь кадр и противоречил
    face_line в BRIEF («считай запретной среднюю треть»)."""
    from reels_factory.face_detect import free_bands

    bands = free_bands(None)
    assert len(bands) == 2
    assert bands[0] == {"left": 0, "top": 0, "width": 1080, "height": 640}
    assert bands[1] == {"left": 0, "top": 1280, "width": 1080, "height": 640}
```

В `tests/test_visual_grounding.py`:

```python
def test_статистика_граундинга_в_логе():
    plan = enforce_visual_grounding(_plan(["Кому продаём", "Открыть сайт elevenlabs"]))
    assert any(line.startswith("граундинг:") for line in plan["log"])
```

В `tests/test_hf_gates.py` (смоук пузыря — pip-раскладка):

```python
def test_пузырь_pip_проходит_гейты():
    """Аватар малым окном в углу (аналог пузыря) — законная раскладка."""
    card = _card(zone="video-overlay",
                 contentRect={"left": 60, "top": 400, "width": 960, "height": 900},
                 videoRect={"left": 690, "top": 28, "width": 360, "height": 203})
    gates = check_storyboard({"cards": [card]}, FACE, duration=3.0)
    assert gates["D8_face"] == "PASS"
```

- [ ] **Шаг 2: Реализация**

`free_bands` (`face_detect.py`): ветку `box is None` заменить:

```python
    if box is None:
        # лица нет — договорная запретная зона: средняя треть кадра
        third = height // 3
        return [{"left": 0, "top": 0, "width": width, "height": third},
                {"left": 0, "top": 2 * third, "width": width, "height": third}]
```

(при 1920 треть = 640 — числа теста сходятся).

`visual_grounding.enforce_visual_grounding`: перед `return result` добавить:

```python
    checked = sum(1 for w in result.get("windows") or []
                  if ((w.get("effect") or {}).get("visual_director") or {})
                  .get("source") == "llm" or "Снято граундингом"
                  in str(w.get("decision_reason") or ""))
    stripped = sum(1 for line in result.get("log") or []
                   if "вставка снята" in line)
    result.setdefault("log", []).append(
        f"граундинг: снято {stripped}, проверено {checked}")
```

Смоук pip нового кода не требует — `moved_face` уже умеет; тест закрепляет.

- [ ] **Шаг 3: Прогон и коммит**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_face_detect.py tests/test_visual_grounding.py tests/test_hf_gates.py -q && ./.venv/Scripts/python.exe -m pytest -q -m "not slow"`
Ожидание: зелено. `test_hf_brief.py::test_скрытые_субтитры_отмечены` строит BRIEF с face=None — если он ассертил полосу на весь кадр, поправь ожидание под две полосы.

```bash
git add plugins/reels-factory/engine/src/reels_factory/face_detect.py plugins/reels-factory/engine/src/reels_factory/visual_grounding.py plugins/reels-factory/engine/tests
git commit -m "fix(hf): faceless bands, grounding stats, pip smoke"
```

---

## Фаза Г — наблюдаемость и деньги

### Задача 9: Лог агентской сессии и конфигурируемый таймаут

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/hf_agent.py`
- Изменить: `plugins/reels-factory/engine/tests/test_hf_agent.py`

**Зачем:** демо-сессия молчала 30 минут до таймаута — недопустимый режим отказа. Пишем весь вывод сессии в `agent.log` рядом с BRIEF, таймаут поднимаем и делаем настраиваемым.

**Интерфейсы:**
- `HeyGenAgentRunner.run(prompt, cwd)`: stdout+stderr сессии полностью пишутся в `<cwd>/agent.log` (перезапись на каждый запуск); при таймауте — `RuntimeError` с путём к логу; таймаут: аргумент конструктора > env `RF_HF_AGENT_TIMEOUT_S` > дефолт **3600**.

- [ ] **Шаг 1: Написать падающие тесты**

Дописать в `tests/test_hf_agent.py` (стиль соседних, с фейковым subprocess.run):

```python
def test_вывод_сессии_пишется_в_лог(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    def fake_run(cmd, **kw):
        class P:
            returncode = 0
            stdout = 'шум\n{"result": "ок", "total_cost_usd": 0.1}'
            stderr = "warn"
        return P()

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_run)
    hf_agent.HeyGenAgentRunner().run("/hyperframes х", cwd=tmp_path)
    log = (tmp_path / "agent.log").read_text(encoding="utf-8")
    assert "шум" in log and "warn" in log


def test_таймаут_из_окружения(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    monkeypatch.setenv("RF_HF_AGENT_TIMEOUT_S", "120")
    seen = {}

    def fake_run(cmd, **kw):
        seen["timeout"] = kw.get("timeout")
        class P:
            returncode = 0
            stdout = '{"result": "ок"}'
            stderr = ""
        return P()

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_run)
    hf_agent.HeyGenAgentRunner().run("х", cwd=tmp_path)
    assert seen["timeout"] == 120


def test_таймаут_даёт_понятную_ошибку_с_логом(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    def fake_run(cmd, **kw):
        raise hf_agent.subprocess.TimeoutExpired(cmd="claude", timeout=1,
                                                 output="частичный вывод")

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="agent.log"):
        hf_agent.HeyGenAgentRunner(timeout_s=1).run("х", cwd=tmp_path)
    assert "частичный вывод" in (tmp_path / "agent.log").read_text(encoding="utf-8")
```

- [ ] **Шаг 2: Запустить, убедиться что падают**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_hf_agent.py -k "лог or таймаут" -v`
Ожидание: FAIL.

- [ ] **Шаг 3: Реализация**

В `hf_agent.py`: `TIMEOUT_S = 3600`; в конструкторе:

```python
    def __init__(self, timeout_s: int | None = None):
        env_timeout = os.environ.get("RF_HF_AGENT_TIMEOUT_S", "").strip()
        self.timeout_s = int(timeout_s if timeout_s is not None
                             else env_timeout or TIMEOUT_S)
```

В `run()` вокруг subprocess:

```python
        log_path = (Path(cwd) if cwd else Path.cwd()) / "agent.log"
        try:
            result = subprocess.run(...)  # как сейчас
        except subprocess.TimeoutExpired as exc:
            log_path.write_text(str(exc.output or ""), encoding="utf-8")
            raise RuntimeError(
                f"агент-сборщик не уложился в {self.timeout_s} с; "
                f"частичный вывод в {log_path}") from exc
        log_path.write_text(
            (result.stdout or "") + "\n--- stderr ---\n" + (result.stderr or ""),
            encoding="utf-8")
```

- [ ] **Шаг 4: Прогон и коммит**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_hf_agent.py -q && ./.venv/Scripts/python.exe -m pytest -q -m "not slow"`
Ожидание: зелено.

```bash
git add plugins/reels-factory/engine/src/reels_factory/hf_agent.py plugins/reels-factory/engine/tests/test_hf_agent.py
git commit -m "feat(hf): agent session log and configurable timeout"
```

---

### Задача 10: Стоимость compose-сессии в биллинг

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/billing.py` (`JobMeter.claude`, `:388-391`)
- Изменить: `plugins/reels-factory/engine/src/reels_factory/pipeline.py` (вызов сборки `:359-367`)
- Изменить: `plugins/reels-factory/engine/tests/test_billing.py`, `tests/test_pipeline.py`

**Зачем:** демо-сессия стоила $9.79 и не попала бы ни в чек, ни в баланс. `JobMeter.claude()` существует, но не вызывается никем.

**Интерфейсы:**
- `JobMeter.claude(usd, step: str = "scenario")` — step уходит в entry_id (`{job_id}:{run_id}:claude:{step}`), повторный учёт того же шага идемпотентен.
- `pipeline.run_make`: создаёт `HeyGenAgentRunner()` (импорт из `hf_agent`), передаёт `agent_runner=` в вызов сборки; после сборки: `if meter and res.get("agent_cost_usd"): meter.claude(res["agent_cost_usd"], step="compose")`.
- Чек бота дорабатывать не надо: трата пишется с `job_id`, `job_breakdown` подхватит её автоматически (`billing.py:242-253`).

- [ ] **Шаг 1: Написать падающие тесты**

В `tests/test_billing.py` (стиль соседних тестов JobMeter):

```python
def test_claude_шаг_в_entry_id(tmp_path):
    store = LedgerStore(tmp_path / "b.sqlite3")
    store.topup(1, amount_micro=10_000_000, currency="USD", topup_id="t1")
    meter = JobMeter(store, chat_id=1, job_id="j1", rates=_rates(),
                     markup=1.0, run_id="r1")
    meter.claude(9.78, step="compose")
    meter.claude(9.78, step="compose")  # идемпотентно
    rows = store.job_breakdown("j1")
    assert rows.get("claude") == to_micro(9.78)
```

В `tests/test_pipeline.py`:

Тест пишется по шаблону любого соседнего теста, идущего через помощник `_fakes` (`tests/test_pipeline.py:57`) — скопируй его подготовку (`_fakes(...)` с `captured`), не выдумывая свою. Содержательная часть:

```python
    charged = []

    class _Meter:
        def elevenlabs(self, *a, **k): pass
        def heygen(self, *a, **k): pass
        def claude(self, usd, step="scenario"):
            charged.append((round(usd, 2), step))

    # ... подготовка через _fakes как в соседнем тесте, meter=_Meter() в run_make

    assert captured.get("agent_runner") is not None
    assert (0.05, "compose") in charged
```

В фейк сборщика (`fake_assemble` внутри `_fakes`) добавь в возвращаемый словарь `"agent_cost_usd": 0.05` — это и есть источник числа в ассерте.

- [ ] **Шаг 2: Запустить, убедиться что падают**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest tests/test_billing.py -k entry_id -v && ./.venv/Scripts/python.exe -m pytest tests/test_pipeline.py -k тарифицируется -v`
Ожидание: FAIL (нет step у claude; agent_runner не передаётся).

- [ ] **Шаг 3: Реализация**

`billing.py:388-391` — добавить параметр:

```python
    def claude(self, usd, step: str = "scenario") -> None:
        ...  # существующее тело; step пробрось в _record вместо
             # захардкоженного шага, чтобы entry_id получил ":claude:compose"
```

`pipeline.py`: импорт `from reels_factory.hf_agent import HeyGenAgentRunner` (модульный уровень, рядом с импортом сборщика `:43`); в вызове сборки (`:359-367`) добавить аргумент `agent_runner=HeyGenAgentRunner()`; после получения `res`:

```python
        agent_cost = float(res.get("agent_cost_usd") or 0.0)
        if meter is not None and agent_cost > 0:
            meter.claude(agent_cost, step="compose")
```

- [ ] **Шаг 4: Прогон и коммит**

Запуск: `cd plugins/reels-factory/engine && ./.venv/Scripts/python.exe -m pytest -q -m "not slow"`
Ожидание: зелено. Тесты pipeline, распаковывающие фейк сборки, получат лишний kwarg `agent_runner` — фейк принимает `**kw`, ассерты не трогать без причины.

```bash
git add plugins/reels-factory/engine/src/reels_factory/billing.py plugins/reels-factory/engine/src/reels_factory/pipeline.py plugins/reels-factory/engine/tests/test_billing.py plugins/reels-factory/engine/tests/test_pipeline.py
git commit -m "feat(billing): compose agent session is metered per job"
```

---

## Фаза Д — живая проверка

### Задача 11: Живая сборка демо-ролика по новым правилам

**Материал:** тот же, что в задаче 13 переезда: `C:\Users\123\Videos\Reels\work\bot-583558720-1784873847`. Скрипт демо-прогона из прошлой сессии: план строится `build_edit_plan` + `finalize_edit_plan` (теперь внутри — ритм-материал и хук по времени), сборка `assemble_hyperframes` с `avatar_render_plan` на один шот и `agent_runner` с логом.

- [ ] **Шаг 1: Пересобрать мастер-звук с паузорезкой**

Живого вызова ElevenLabs НЕ делать. Паузорезку проверить на готовом wav: прогнать `trim_master_pauses` по `words.fixed.json` + `reel-audio.wav` (41.5 с) отдельным скриптом с ffmpeg — получить порезанный wav и новые words; убедиться, что заминка на 11–12 с исчезла (пауза между блоками показывается в cuts).

- [ ] **Шаг 2: Собрать ролик**

Свежая папка, полный план из сценария, порезанные words/wav, `HeyGenAgentRunner()` (таймаут 3600, лог). Ожидания: гейты D8–D13 все PASS; `agent.log` существует; в BRIEF есть раздел ритма; в плане есть ритм-материал (лог `ритм-материал`).

- [ ] **Шаг 3: Посмотреть глазами и показать Васе**

Кадры каждые ~3 секунды: дыр длиннее 3 с нет, первые 4 с — чистая ведущая, лицо не перекрыто, кириллица целая, паузы речи не ощущаются. Ролик — Васе на приёмку.

- [ ] **Шаг 4: Коммит вспомогательного скрипта не нужен** — прогон разовый, скрипт остаётся в scratchpad.

---

## Открытые вопросы — решаются этим же живым прогоном

1. **Сколько реально стоит и длится сессия с ритмом:** BRIEF стал требовательнее (больше карточек). Если сессия снова у потолка часа — план №2 (мини-сессии на карточку) поднимается в приоритете.
2. **Качество стока media-use:** первый живой resolve покажет, что скил реально возвращает по русскоязычному запросу. Если мусор — сток выключается из приоритета одной строкой в `fill_material_by_rhythm`.
3. **Ритм 3 с на длинных payoff-окнах:** возможно, окна придётся дробить на уровне сценария — решать по живому ролику, не в этом плане.

## Отложено сознательно — план №2 (после приёмки этого)

1. **Каркас композиции кодом** (клипы+звук+субтитры без агента) — контракт разведан (data-start/data-duration/data-track-index, `window.__timelines`), но дизайн стоит делать на данных agent.log из задачи 9.
2. **Мини-сессии на карточку** через суб-композиции (`data-composition-src`), параллель, кэш детерминированных карточек, точечный ретрай.
3. **Черновой рендер** (флаг качества) — внутренний инструмент.
4. **Уборка:** старый Revideo-рендер, жёлтый `#FFE500`, флаги-пустышки `grade/grain/zoom/flash`, мёртвая ветка jump_cuts в pipeline, судьба `tz_validator.py` — самой последней задачей (решение Васи).

## Чего в плане намеренно нет

- Ужесточения граундинга — решение Васи: собрать статистику (задача 8 добавляет счётчик в log).
- Библиотеки б-роллов клиента — бот материалы не собирает, механизм в движке дремлет.
- Изменений в скилах HeyGen — они как есть; вся новизна — в обвязке.
