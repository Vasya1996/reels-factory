# Переезд фабрики рилсов на HyperFrames — план внедрения

> **Для агента-исполнителя:** ОБЯЗАТЕЛЬНЫЙ СУБ-СКИЛ: `superpowers:subagent-driven-development` (рекомендуется) или `superpowers:executing-plans`. Задачи выполняются строго по порядку. Шаги — чекбоксы (`- [ ]`).

**Цель:** заменить самописную сцену Revideo на движок HyperFrames и передать монтажные решения готовым скилам HeyGen, дописав поверх них ровно то, чего у них нет: безопасные зоны, знание про лицо, кириллицу, наши пословные тайминги, содержание вставок из нашего плана и связь «ведущий не нужен → аватар не заказываем».

**Архитектура — прочитай дважды.** Скил HeyGen — инструкция для агента, а не библиотека. Композицию собирает **агент в отдельной headless-сессии** под скилами HeyGen. Наш Python **не пишет вёрстку карточек и не сочиняет стиль**. Он делает пять вещей: готовит материал, пишет задание (`BRIEF.md`) **вместе с содержанием вставок из плана монтажа**, запускает агента, проверяет возвращённую раскадровку своими гейтами и рендерит.

**Технологии:** Python 3.11, Node ≥22 и `npx hyperframes@0.7.70`, headless Claude со скилами HeyGen, ffmpeg, pytest.

## Два решения, которые план принимает явно

1. **Мастер-звук становится обязательным.** Новый сборщик работает только с единой озвучкой и пословным выравниванием. Путь без мастер-звука (`voice_wavs`, ретайминг по фрагментам) не переносится. Флаг `master_audio.enabled` переводится в `true` по умолчанию, тесты старого пути переписываются на новый (задача 12).
2. **Формат `fullscreen` не переносится.** Конвейер падает понятной ошибкой. Поддержаны `split` и `avatar`.

## Глобальные ограничения

- Кадр **1080×1920, 30 кадров/с** (`config.py:48-49`), громкость **−14 LUFS / −1.5 TP** (`config.py:50-51`).
- Версия движка **жёстко 0.7.70** (`hyperframes_blocks.py:25`).
- **Все тайминги кратны 1/30 секунды.**
- **Громкость приводим сами** — в движке её нет.
- **Облачный рендер не используем** (`cloud`, `lambda`, `cloudrun`).
- **Внутри карточек только локальные файлы.** Шрифты — исключение: движок сам подтягивает семейство по имени на этапе компиляции и встраивает его с сохранением диапазонов символов, поэтому `font-family: "Montserrat"` без `<link>` — законно и обязательно.
- **Шрифты `Montserrat` и `Inter`** — только они закрывают кириллицу и казахские `ә ғ қ ң ө ұ ү һ і`.
- **Стиль фабрики — `minimal`** из десяти стилей скила, заморожен.
- **Разрешены две зоны карточки: `video-overlay` и `fullscreen`.** Остальные три (`lower-third`, `side-panel`, `whiteboard-area`) в вертикали целиком лежат в полосе интерфейса приложения и запрещены нами.
- **Каждый шаг сборки пишет файл-маркер и перезапускаем.**
- На Windows CLI движка вызывается **строкой с `shell=True`** — так это уже сделано в `hyperframes_blocks.py:586`. Список аргументов с `npx` не резолвится.
- Ветка `feat/vasya-hyperframes`. Коммит после каждой задачи.
- Тесты: `cd plugins/reels-factory/engine && python -m pytest -q -m "not slow"`.

## Установленные факты (перепроверять не нужно)

- Сборщик бота: `pipeline.py:39` → `revideo_render.assemble_revideo`; вызов `:346-357`; дефолт `:90`.
- `caption_fixes` уже посчитаны правильно на `pipeline.py:152`; `apply_caption_fixes` живёт в `compose.py` и **не импортирован** в `pipeline.py`.
- `verify_reel` (`verify.py:106-108`) **не принимает** `edit_plan` — его сигнатуру не трогаем, гейты вставок сливаем в результат после вызова.
- `VENC` определён в `render.py:13`, реэкспортируется через `compose.py:43`; в `config.py` его нет.
- `safe_to_skip_avatar` разрешён валидатором **только** при `coverage == "full_broll"` и `effect.type == "broll"` (`editplan.py:2456-2462`); `avatar_required` блока считается только по фразам `full_broll` (`:1908-1916`).
- `enforce_visual_grounding` обязана менять покрытие **и у окна, и у его фраз** — иначе `validate_edit_plan` упадёт на несовпадении (`editplan.py:2443-2444`), как это делает штатный `_downgrade_window` (`:2113-2118`).
- `effect["src"]` — **имя ассета библиотеки**, не путь. Путь считает `_asset_path` (`editplan.py:665`), исходные данные лежат в `window["asset"]`.
- Прямоугольники окна видео в вертикали: `overlay` `{0,0,1080,1920}`, `stack` `{0,0,1080,844}`, `split` `{0,960,1080,960}`, `pip` `{738,28,312,555}`.
- `ClaudeSkillRunner` (`llm.py:52`) работает в изолированном профиле `~/.reels-factory/claude` с `--setting-sources ""` — **скилы HeyGen из `~/.claude/skills` он не увидит**. Нужен отдельный запуск.
- GSAP лежит в `~/.claude/skills/talking-head-recut/assets/vendor/gsap.min.js`.
- Восемь наших блоков (`hyperframes_blocks.py:592-600`) вызываются только из `revideo_render.py:104`. После переезда их содержание передаётся агенту заданием, а сам `render_block` становится неиспользуемым — это осознанно, см. «Отложено».

## Геометрия кадра

- **Ядро вставки:** `x ∈ [130, 940]`, `y ∈ [280, 1250]`.
- **Полоса интерфейса:** `y ≥ 1300`.
- **Лицо:** прямоугольник вокруг центра лица. Ведущая стоит по центру кадра, поэтому свободных полос ровно две: над головой и под ней. Карточка ставится в одну из них, а не «где-нибудь в ядре».
- Проверяется **прямоугольник видимого содержимого** карточки (`contentRect`), а не габариты зоны.

## Структура файлов

| Файл | Ответственность |
|---|---|
| `src/reels_factory/hf_assets.py` | Локальный GSAP |
| `src/reels_factory/face_detect.py` | `face.json` — где лицо |
| `src/reels_factory/hf_layout.py` | Геометрия вертикали, зоны, безопасные полосы, сетка кадров |
| `src/reels_factory/visual_grounding.py` | Снимает вставки, чей текст не звучит |
| `src/reels_factory/hf_gates.py` | Гейты раскадровки |
| `src/reels_factory/hf_brief.py` | Задание агенту: правила **и содержание вставок** |
| `src/reels_factory/hf_agent.py` | Запуск агента под скилами HeyGen (свой профиль, свои права) |
| `src/reels_factory/hf_render.py` | Возобновляемые шаги сборки |
| `src/reels_factory/capture_site.py` | Снимок сайта с кэшем |
| `src/reels_factory/screen_route.py` | Запись экранного маршрута |

Изменяются: `editplan.py`, `pipeline.py`, `tests/test_pipeline.py`, `tests/test_editplan.py`, `tests/test_hyperframes_blocks.py`.

---

## Фаза 0 — подготовка

### Задача 1: Ветка, окружение, GSAP

**Файлы:**
- Создать: `plugins/reels-factory/engine/tests/test_hf_env.py`
- Создать: `plugins/reels-factory/engine/src/reels_factory/hf_assets.py`

**Интерфейсы:**
- Производит: `hf_assets.vendor_gsap(public_dir) -> Path`, `hf_assets.SKILLS_DIR`.

- [ ] **Шаг 1: Ветка**

```bash
git switch -c feat/vasya-hyperframes
```

- [ ] **Шаг 2: Установить скилы и проверить окружение**

```bash
npx --yes hyperframes@0.7.70 skills update talking-head-recut
```
Ожидание: ставятся девять скилов в `~/.claude/skills` (`hyperframes`, `talking-head-recut`, `hyperframes-core`, `-animation`, `-keyframes`, `-creative`, `-registry`, `-cli`, `media-use`).

```bash
node --version
```
Ожидание: `v22`+.

```bash
npx --yes hyperframes@0.7.70 telemetry disable
```

- [ ] **Шаг 3: Написать падающий тест**

Создать `plugins/reels-factory/engine/tests/test_hf_env.py`:

```python
"""Окружение: версия закреплена, облачные подкоманды не зовутся, GSAP локальный."""
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "reels_factory"


def test_версия_движка_закреплена():
    text = (SRC / "hyperframes_blocks.py").read_text(encoding="utf-8")
    version = re.search(r'_HF_VERSION\s*=\s*"([\d.]+)"', text)
    assert version and version.group(1) == "0.7.70"
    assert "hyperframes@latest" not in text


def test_облачные_подкоманды_не_зовутся():
    """Подкоманда ищется как отдельный аргумент вызова, а не подстрока."""
    forbidden = {"cloud", "lambda", "cloudrun"}
    for path in list(SRC.glob("hf_*.py")) + [SRC / "capture_site.py"]:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for call in re.findall(r"_cli\(([^)]*)\)", text):
            args = re.findall(r'"([a-z-]+)"', call)
            assert not (forbidden & set(args)), f"{path.name}: облачный режим запрещён"


def test_gsap_кладётся_локально(tmp_path):
    from reels_factory.hf_assets import vendor_gsap

    if not (Path.home() / ".claude" / "skills" / "talking-head-recut").exists():
        pytest.skip("скилы HeyGen не установлены")
    target = vendor_gsap(tmp_path)
    assert target.exists() and target.stat().st_size > 10_000
```

- [ ] **Шаг 4: Запустить, убедиться что третий падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_env.py -v`
Ожидание: 2 passed, 1 failed (`ModuleNotFoundError: reels_factory.hf_assets`).

- [ ] **Шаг 5: Реализация**

Создать `plugins/reels-factory/engine/src/reels_factory/hf_assets.py`:

```python
"""Локальные ассеты композиции: внешние URL внутри карточек запрещены."""
from __future__ import annotations

import shutil
from pathlib import Path

SKILLS_DIR = Path.home() / ".claude" / "skills"
GSAP_SOURCE = SKILLS_DIR / "talking-head-recut" / "assets" / "vendor" / "gsap.min.js"


def vendor_gsap(public_dir) -> Path:
    """Положить gsap.min.js в public/vendor. Возвращает путь к копии."""
    target = Path(public_dir) / "vendor" / "gsap.min.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not GSAP_SOURCE.exists():
        raise RuntimeError(
            "не найден gsap.min.js; выполни "
            "npx hyperframes@0.7.70 skills update talking-head-recut")
    shutil.copyfile(GSAP_SOURCE, target)
    return target
```

- [ ] **Шаг 6: Запустить тест**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_env.py -v`
Ожидание: 3 passed.

- [ ] **Шаг 7: Коммит**

```bash
git add plugins/reels-factory/engine/tests/test_hf_env.py plugins/reels-factory/engine/src/reels_factory/hf_assets.py
git commit -m "chore(hf): install skills, pin engine, vendor gsap"
```

---

### Задача 2: Где лицо

> **Порядок:** эта задача выполняется **после задачи 3** — `face_detect` импортирует `hf_layout`. Нумерация оставлена ради ссылок; исполняй 1 → 3 → 2 → 4 → …

**Файлы:**
- Создать: `plugins/reels-factory/engine/src/reels_factory/face_detect.py`
- Создать: `plugins/reels-factory/engine/tests/test_face_detect.py`

**Интерфейсы:**
- Потребляет: `zoom.detect_face_anchor(src, *, sample_fps=2.0, run_probe=None, detect=None) -> tuple[float, float]` (`zoom.py:55`, доли кадра; без детекта возвращает `(0.5, 0.42)`).
- Производит: `face_box_for(video, out_json, *, width=OUT_W, height=OUT_H, detect=None) -> dict` → `{"cx", "cy", "h"}` в пикселях; `load_face(rdir) -> dict | None`; `free_bands(face) -> list[dict]` — свободные полосы над и под лицом внутри ядра.

**Зачем `free_bands`:** ведущая стоит по центру, поэтому «поставь карточку внутрь ядра» — недостаточная инструкция. Агенту нужно отдать конкретные прямоугольники, куда можно.

- [ ] **Шаг 1: Написать падающий тест**

Создать `plugins/reels-factory/engine/tests/test_face_detect.py`:

```python
"""Лицо ведущей: доли кадра из детектора -> пиксели -> свободные полосы."""
import json

from reels_factory.face_detect import face_box_for, free_bands, load_face


def test_доли_превращаются_в_пиксели(tmp_path):
    out = tmp_path / "face.json"
    face = face_box_for("нет.mp4", out, detect=lambda src, fps: [(0.5, 0.3)])
    assert face["cx"] == 540
    assert face["cy"] == 576
    assert face["h"] > 0
    assert json.loads(out.read_text(encoding="utf-8")) == face


def test_без_детекта_якорь_по_умолчанию(tmp_path):
    face = face_box_for("нет.mp4", tmp_path / "face.json", detect=lambda src, fps: [])
    assert face["cx"] == 540
    assert face["cy"] == round(1920 * 0.42)


def test_свободные_полосы_не_пересекают_лицо(tmp_path):
    from reels_factory.hf_layout import face_box, violations

    face = face_box_for("нет.mp4", tmp_path / "face.json", detect=lambda src, fps: [])
    bands = free_bands(face)
    assert bands, "должна остаться хотя бы одна свободная полоса"
    for band in bands:
        assert violations(band, face) == []


def test_чтение_отсутствующего_файла(tmp_path):
    assert load_face(tmp_path) is None
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_face_detect.py -v`
Ожидание: FAIL — модуля нет.

- [ ] **Шаг 3: Реализация**

Создать `plugins/reels-factory/engine/src/reels_factory/face_detect.py`:

```python
"""Координаты лица ведущей и свободные полосы кадра.

Детектор уже есть в движке (zoom.detect_face_anchor) и возвращает доли кадра.
Здесь они переводятся в пиксели и кладутся в face.json, чтобы задание агенту
и гейты читали одно и то же число.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from reels_factory.config import OUT_H, OUT_W

# высота головы как доля высоты кадра для говорящей головы в вертикали
FACE_HEIGHT_RATIO = 0.14
# минимальная полезная высота свободной полосы
MIN_BAND_H = 180


def face_box_for(video, out_json, *, width: int = OUT_W, height: int = OUT_H,
                 detect=None) -> dict:
    """Найти лицо и записать face.json в пикселях."""
    from reels_factory.zoom import detect_face_anchor

    fx, fy = detect_face_anchor(video, detect=detect)
    face = {"cx": round(float(fx) * width),
            "cy": round(float(fy) * height),
            "h": round(height * FACE_HEIGHT_RATIO)}
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(face, ensure_ascii=False), encoding="utf-8")
    return face


def load_face(rdir) -> dict | None:
    path = Path(rdir) / "face.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def free_bands(face: dict | None) -> list[dict]:
    """Полосы внутри ядра, куда карточку ставить можно: над лицом и под ним."""
    from reels_factory.hf_layout import CORE_BOX, face_box

    core_top = CORE_BOX["top"]
    core_bottom = CORE_BOX["top"] + CORE_BOX["height"]
    box = face_box(face)
    if box is None:
        return [{"left": CORE_BOX["left"], "top": core_top,
                 "width": CORE_BOX["width"], "height": CORE_BOX["height"]}]

    bands = []
    above = box["top"] - core_top
    if above >= MIN_BAND_H:
        bands.append({"left": CORE_BOX["left"], "top": core_top,
                      "width": CORE_BOX["width"], "height": int(above)})
    # округляем ВВЕРХ: int() отрезал бы дробную часть и полоса залезла бы
    # на лицо на доли пикселя — гейт это поймает, а причина будет неочевидна
    below_top = math.ceil(box["top"] + box["height"])
    below = core_bottom - below_top
    if below >= MIN_BAND_H:
        bands.append({"left": CORE_BOX["left"], "top": below_top,
                      "width": CORE_BOX["width"], "height": int(below)})
    return bands
```

- [ ] **Шаг 4: Запустить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_face_detect.py -v`
Ожидание: 4 passed. Если `test_свободные_полосы_не_пересекают_лицо` падает — значит `FACE_MARGIN` в задаче 3 подобран так, что свободных полос не остаётся; это сигнал уменьшить запас, а не удалять тест.

- [ ] **Шаг 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/face_detect.py plugins/reels-factory/engine/tests/test_face_detect.py
git commit -m "feat(face): face box and free bands of the frame"
```

---

## Фаза A — правила, которых нет у скила

### Задача 3: Геометрия вертикали

**Файлы:**
- Создать: `plugins/reels-factory/engine/src/reels_factory/hf_layout.py`
- Создать: `plugins/reels-factory/engine/tests/test_hf_layout.py`

**Интерфейсы:**
- Производит: `VIDEO_RECTS`, `ALLOWED_ZONES`, `CORE_BOX`, `UI_BAND_TOP`, `FACE_MARGIN`, `quantize(seconds) -> float`, `face_box(face) -> dict | None`, `violations(content_rect, face) -> list[str]`.
- `violations` возвращает строки с маркерами: `"ядро"`, `"интерфейс"`, `"лицо"` — по ним гейты раскладывают нарушения по разным ключам.

- [ ] **Шаг 1: Написать падающий тест**

Создать `plugins/reels-factory/engine/tests/test_hf_layout.py`:

```python
"""Геометрия вертикального кадра: сетка кадров, безопасные полосы, лицо."""
import pytest

from reels_factory.hf_layout import (
    ALLOWED_ZONES, CORE_BOX, UI_BAND_TOP, VIDEO_RECTS, face_box, quantize, violations,
)


def test_раскладки_и_разрешённые_зоны():
    assert VIDEO_RECTS["overlay"] == {"left": 0, "top": 0, "width": 1080, "height": 1920}
    assert VIDEO_RECTS["stack"]["height"] == 844
    assert VIDEO_RECTS["pip"] == {"left": 738, "top": 28, "width": 312, "height": 555}
    # три остальные зоны скила в вертикали лежат в полосе интерфейса — запрещены
    assert ALLOWED_ZONES == {"video-overlay", "fullscreen"}


@pytest.mark.parametrize("value,expected", [
    (0.0, 0.0), (1.0, 1.0), (13.02, 13.033), (13.017, 13.033),
    (41.508, 41.5), (6.017, 6.033),
])
def test_округление_к_сетке_кадров(value, expected):
    assert quantize(value) == pytest.approx(expected, abs=0.001)


def test_ядро_не_заходит_в_полосу_интерфейса():
    assert CORE_BOX["top"] + CORE_BOX["height"] <= UI_BAND_TOP


def test_содержимое_под_лицом_чисто():
    face = {"cx": 540, "cy": 520, "h": 260}
    assert violations({"left": 130, "top": 980, "width": 810, "height": 260}, face) == []


def test_карточка_на_лице_ловится():
    face = {"cx": 540, "cy": 520, "h": 260}
    problems = violations({"left": 200, "top": 400, "width": 700, "height": 300}, face)
    assert any("лицо" in p for p in problems)


def test_заход_в_полосу_интерфейса_ловится():
    problems = violations({"left": 130, "top": 1000, "width": 810, "height": 400}, None)
    assert any("интерфейс" in p for p in problems)


def test_выход_за_ядро_ловится():
    problems = violations({"left": 20, "top": 300, "width": 400, "height": 200}, None)
    assert any("ядро" in p for p in problems)


def test_без_лица_проверка_лица_пропускается():
    assert face_box(None) is None
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_layout.py -v`
Ожидание: FAIL — модуля нет. Всего тестов будет 13 (семь функций плюс шесть параметров).

- [ ] **Шаг 3: Реализация**

Создать `plugins/reels-factory/engine/src/reels_factory/hf_layout.py`:

```python
"""Геометрия вертикального кадра 1080x1920.

Прямоугольники раскладок продублированы из справочных файлов скила
talking-head-recut (таблица composition layouts, колонка portrait). Скил
обновляется отдельно от нас, поэтому значения зафиксированы здесь.

Безопасных зон движок не знает вовсе — это наше знание.
"""
from __future__ import annotations

from reels_factory.config import FPS

VIDEO_RECTS = {
    "overlay": {"left": 0, "top": 0, "width": 1080, "height": 1920},
    "stack": {"left": 0, "top": 0, "width": 1080, "height": 844},
    "split": {"left": 0, "top": 960, "width": 1080, "height": 960},
    "pip": {"left": 738, "top": 28, "width": 312, "height": 555},
}

# Скил знает пять зон, но lower-third (y>=1344), side-panel (y>=1152) и
# whiteboard-area (y>=1056) в вертикали лежат в полосе интерфейса приложения.
# Разрешаем только те две, где содержимое можно поставить куда нужно.
ALLOWED_ZONES = {"video-overlay", "fullscreen"}

CORE_BOX = {"left": 130, "top": 280, "width": 810, "height": 970}
UI_BAND_TOP = 1300

# запас вокруг центра лица: 0.6 высоты головы в каждую сторону
FACE_MARGIN = 0.6


def quantize(seconds: float) -> float:
    """Округлить время к сетке кадров: движок иначе добавляет до 1/30 секунды."""
    return round(round(float(seconds) * FPS) / FPS, 3)


def face_box(face: dict | None) -> dict | None:
    if not face:
        return None
    cx, cy, h = float(face["cx"]), float(face["cy"]), float(face["h"])
    margin = h * FACE_MARGIN
    return {"left": cx - margin, "top": cy - margin,
            "width": 2 * margin, "height": 2 * margin}


def _intersects(a: dict, b: dict) -> bool:
    return not (
        a["left"] + a["width"] <= b["left"]
        or b["left"] + b["width"] <= a["left"]
        or a["top"] + a["height"] <= b["top"]
        or b["top"] + b["height"] <= a["top"]
    )


def violations(content_rect: dict, face: dict | None) -> list[str]:
    """Нарушения прямоугольника ВИДИМОГО СОДЕРЖИМОГО. Пусто — всё чисто."""
    problems: list[str] = []
    right = content_rect["left"] + content_rect["width"]
    bottom = content_rect["top"] + content_rect["height"]

    if (content_rect["left"] < CORE_BOX["left"]
            or content_rect["top"] < CORE_BOX["top"]
            or right > CORE_BOX["left"] + CORE_BOX["width"]
            or bottom > CORE_BOX["top"] + CORE_BOX["height"]):
        problems.append("вышел за ядро вставки")

    if bottom > UI_BAND_TOP:
        problems.append("заходит в полосу интерфейса приложения")

    box = face_box(face)
    if box is not None and _intersects(content_rect, box):
        problems.append("перекрывает лицо ведущей")

    return problems
```

- [ ] **Шаг 4: Запустить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_layout.py tests/test_face_detect.py -v`
Ожидание: 13 + 4 passed.

- [ ] **Шаг 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/hf_layout.py plugins/reels-factory/engine/tests/test_hf_layout.py
git commit -m "feat(hf): portrait geometry, allowed zones, frame grid"
```

---

### Задача 4: Граундинг вставок

**Файлы:**
- Создать: `plugins/reels-factory/engine/src/reels_factory/visual_grounding.py`
- Создать: `plugins/reels-factory/engine/tests/test_visual_grounding.py`
- Изменить: `plugins/reels-factory/engine/src/reels_factory/editplan.py` (вызов перед `_refresh_blocks_and_summary`, `:2280`)

**Интерфейсы:**
- Производит: `enforce_visual_grounding(plan: dict) -> dict`.
- Текст берётся из обоих мест: `effect["hyperframes"]["variables"]["items"]` (строки) и `effect["items"]` (список словарей — ключ `label`).
- При снятии вставки окно **и его фразы** возвращаются в аватарное покрытие: иначе `validate_edit_plan` упадёт на несовпадении (`editplan.py:2443-2444`).

- [ ] **Шаг 1: Написать падающий тест**

Создать `plugins/reels-factory/engine/tests/test_visual_grounding.py`:

```python
"""Вставка обязана быть выведена из слов, которые в этот момент звучат."""
from reels_factory.visual_grounding import enforce_visual_grounding


def _plan(items):
    return {
        "phrases": [{"id": "p1", "text": "Первый вопрос: кому продаём и кто наш клиент",
                     "coverage": "hyperframes", "window_id": "window-000"}],
        "windows": [{
            "id": "window-000",
            "phrase_ids": ["p1"],
            "coverage": "hyperframes",
            "safe_to_skip_avatar": False,
            "effect": {
                "type": "chart_bars",
                "title": "Три вопроса",
                "items": [{"label": t, "v": 1} for t in items],
                "hyperframes": {"block": "task_list",
                                "variables": {"title": "Три вопроса", "items": items}},
            },
        }],
        "log": [],
    }


def test_заземлённая_вставка_остаётся():
    plan = enforce_visual_grounding(_plan(["Кому продаём", "Кто клиент"]))
    assert plan["windows"][0]["effect"]["type"] == "chart_bars"
    assert plan["log"] == []


def test_выдуманная_вставка_снимается():
    plan = enforce_visual_grounding(_plan(["Кому продаём", "Открыть сайт elevenlabs"]))
    assert plan["windows"][0]["effect"] == {"type": "none"}
    assert any("elevenlabs" in line for line in plan["log"])


def test_снятая_вставка_возвращает_окно_и_фразы_ведущему():
    plan = enforce_visual_grounding(_plan(["Открыть сайт elevenlabs"]))
    assert plan["windows"][0]["coverage"] == "avatar"
    assert plan["windows"][0]["safe_to_skip_avatar"] is False
    assert plan["phrases"][0]["coverage"] == "avatar"


def test_вставка_без_текста_не_трогается():
    plan = {
        "phrases": [{"id": "p1", "text": "любые слова", "coverage": "full_broll"}],
        "windows": [{"id": "w", "phrase_ids": ["p1"], "coverage": "full_broll",
                     "effect": {"type": "broll", "style": "fullscreen", "src": "a.mp4"}}],
        "log": [],
    }
    assert enforce_visual_grounding(plan)["windows"][0]["effect"]["type"] == "broll"


def test_исходный_план_не_меняется():
    original = _plan(["Открыть сайт elevenlabs"])
    enforce_visual_grounding(original)
    assert original["windows"][0]["effect"]["type"] == "chart_bars"
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_visual_grounding.py -v`
Ожидание: FAIL — модуля нет.

- [ ] **Шаг 3: Реализация**

Создать `plugins/reels-factory/engine/src/reels_factory/visual_grounding.py`:

```python
"""Граундинг вставок: на экране только то, что звучит.

Для речи правило есть с самого начала (скил сценария, scenario.py:213).
Для картинки его не было — через эту дыру в ролик попадает предмет, которого
в сценарии нет. Проверяем пункты списка: заголовок может быть обобщением,
а пункты обязаны опираться на сказанное.
"""
from __future__ import annotations

import copy
import re

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]{4,}")
_MIN_ROOT = 4


def _root(word: str) -> str:
    word = word.lower()
    return word[: max(_MIN_ROOT, len(word) - 2)]


def _speech_roots(text: str) -> set[str]:
    return {_root(w) for w in _WORD_RE.findall(str(text or ""))}


def _item_texts(effect: dict) -> list[str]:
    """Строки вставки из обоих мест, где движок их держит."""
    variables = (effect.get("hyperframes") or {}).get("variables") or {}
    texts = [str(x) for x in (variables.get("items") or []) if isinstance(x, str)]
    if texts:
        return texts
    out = []
    for item in effect.get("items") or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            out.append(str(item.get("label") or ""))
    return [t for t in out if t]


def _is_grounded(item: str, roots: set[str]) -> bool:
    words = _WORD_RE.findall(str(item or ""))
    if not words:
        return True
    return any(
        any(root.startswith(_root(w)) or _root(w).startswith(root) for root in roots)
        for w in words
    )


def enforce_visual_grounding(plan: dict) -> dict:
    """Снять вставки, чьи пункты не опираются на речь накрытых фраз."""
    result = copy.deepcopy(plan)
    phrases = result.get("phrases") or []
    text_by_id = {p["id"]: p.get("text", "") for p in phrases}

    for window in result.get("windows") or []:
        items = _item_texts(window.get("effect") or {})
        if not items:
            continue
        roots: set[str] = set()
        for phrase_id in window.get("phrase_ids") or []:
            roots |= _speech_roots(text_by_id.get(phrase_id, ""))
        stray = [item for item in items if not _is_grounded(item, roots)]
        if not stray:
            continue

        # Покрытие меняем и у окна, и у его фраз — иначе валидатор плана
        # поймает несовпадение и уронит finalize_edit_plan.
        window["effect"] = {"type": "none"}
        window["coverage"] = "avatar"
        window["zone"] = "video-overlay"   # инвариант: аватарное окно — поверх видео
        window["asset"] = None
        window["safe_to_skip_avatar"] = False
        window["decision_reason"] = (
            "Снято граундингом: в речи нет опоры для " + "; ".join(stray))
        own = set(window.get("phrase_ids") or [])
        for phrase in phrases:
            if phrase["id"] in own:
                phrase["coverage"] = "avatar"
                phrase["asset"] = None
                phrase["decision_reason"] = window["decision_reason"]
        result.setdefault("log", []).append(
            f"{window.get('id')}: вставка снята, нет опоры в речи — " + "; ".join(stray))
    return result
```

- [ ] **Шаг 4: Запустить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_visual_grounding.py -v`
Ожидание: 5 passed.

- [ ] **Шаг 5: Подключить в план**

В `editplan.py`, в `finalize_edit_plan`, непосредственно перед `_refresh_blocks_and_summary(result)` (`:2280`):

```python
    from reels_factory.visual_grounding import enforce_visual_grounding

    result = enforce_visual_grounding(result)
```

- [ ] **Шаг 6: Прогнать весь набор**

Запуск: `cd plugins/reels-factory/engine && python -m pytest -q -m "not slow"`
Ожидание: зелено. Падение теста `test_editplan.py` с выдуманными пунктами — находка правила: поправить текст фикстуры, чтобы пункты звучали в речи блока.

- [ ] **Шаг 7: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/visual_grounding.py plugins/reels-factory/engine/tests/test_visual_grounding.py plugins/reels-factory/engine/src/reels_factory/editplan.py
git commit -m "feat(editplan): show only what is actually said"
```

---

### Задача 5: Зона окна в плане

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/editplan.py` (`_assign_window` `:1284`, `_downgrade_window` `:2102`, `_downgrade_draft_window` `:1353`)
- Изменить: `plugins/reels-factory/engine/tests/test_editplan.py`

**Интерфейсы:**
- У окна **добавляется** поле `zone` — `video-overlay` там, где ведущий несёт смысл, `fullscreen` там, где важнее показать. Поле `camera` **остаётся** (его читает `test_editplan.py:472`).
- Поля `layout` **не добавляем**: в вертикали работает единственная раскладка `overlay`, а различие выражается зоной. Раскладками управляет агент внутри разрешённого набора, наше дело — сказать зону.
- **Экономии на аватаре эта задача не даёт.** Валидатор разрешает `safe_to_skip_avatar` только для `coverage="full_broll"` с эффектом `broll` (`editplan.py:2456-2462`), а блок считается безопасным только по фразам `full_broll` (`:1908-1916`). Пропуск аватара под полноэкранной графикой — отдельная задача 6.

- [ ] **Шаг 1: Написать падающий тест**

Дописать в `plugins/reels-factory/engine/tests/test_editplan.py`:

```python
def _timed_two_blocks():
    return {"total": 20.0, "blocks": [
        {"role": "hook", "start": 0.0, "end": 6.0,
         "speech": "первый вопрос кому продаём и кто наш клиент"},
        {"role": "cta", "start": 6.0, "end": 20.0, "speech": "сохрани это видео"},
    ]}


def test_у_каждого_окна_есть_разрешённая_зона():
    from reels_factory.editplan import build_edit_plan
    from reels_factory.hf_layout import ALLOWED_ZONES

    plan = build_edit_plan(_timed_two_blocks(), {}, index={}, require_asset_files=False)
    assert plan["windows"], "план без окон — тест бессмыслен"
    for window in plan["windows"]:
        assert window["zone"] in ALLOWED_ZONES


def test_аватарное_окно_поверх_видео():
    from reels_factory.editplan import build_edit_plan

    plan = build_edit_plan(_timed_two_blocks(), {}, index={}, require_asset_files=False)
    for window in plan["windows"]:
        if window["coverage"] in {"avatar", "mixed"}:
            assert window["zone"] == "video-overlay"


def test_поле_камеры_не_потеряно():
    from reels_factory.editplan import build_edit_plan

    plan = build_edit_plan(_timed_two_blocks(), {}, index={}, require_asset_files=False)
    assert all("camera" in w for w in plan["windows"])


def test_даунгрейд_возвращает_зону_с_ведущим():
    from reels_factory.editplan import _downgrade_window

    window = {"id": "w", "phrase_ids": [], "role": "development",
              "coverage": "hyperframes", "zone": "fullscreen"}
    _downgrade_window({"phrases": []}, window, "нет ассета")
    assert window["zone"] == "video-overlay"
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_editplan.py -k "зон or камер or даунгрейд" -v`
Ожидание: FAIL — поля нет.

- [ ] **Шаг 3: Реализация**

В `editplan.py` над `_assign_window` добавить:

```python
# Зона выводится из смысла окна: где ведущий несёт смысл — карточка поверх
# видео, где важнее показать — кадр отдаётся показу. Три остальные зоны скила
# в вертикали лежат в полосе интерфейса приложения и нами запрещены.
_FACELESS_COVERAGE = {"full_broll", "hyperframes"}


def _zone_for(coverage: str) -> str:
    return "fullscreen" if coverage in _FACELESS_COVERAGE else "video-overlay"
```

В словарь `window` внутри `_assign_window`, сразу после `"camera": {"type": camera},`:

```python
        "zone": _zone_for(coverage),
```

В `_downgrade_window` (`:2102`) и `_downgrade_draft_window` (`:1353`), рядом со строкой `window["coverage"] = "avatar"`:

```python
    window["zone"] = _zone_for("avatar")
```

- [ ] **Шаг 4: Запустить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_editplan.py -v`
Ожидание: зелено, включая четыре новых.

- [ ] **Шаг 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/editplan.py plugins/reels-factory/engine/tests/test_editplan.py
git commit -m "feat(editplan): derive card zone from window meaning"
```

---

### Задача 6: Пропуск аватара под полноэкранной графикой

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/editplan.py` (`validate_edit_plan` `:2456-2462`, `_refresh_blocks_and_summary` `:1908-1916`, места создания окон `hyperframes`)
- Изменить: `plugins/reels-factory/engine/tests/test_editplan.py`

**Зачем:** это и есть обещанная экономия. Сейчас пропуск аватара разрешён только под видеовставкой; под полноэкранной графикой ведущей в кадре тоже нет, но аватар всё равно заказывается и оплачивается.

- [ ] **Шаг 1: Написать падающий тест**

Дописать в `plugins/reels-factory/engine/tests/test_editplan.py`:

```python
def test_полноэкранная_графика_разрешает_пропуск_аватара():
    from reels_factory.editplan import validate_edit_plan

    plan = {
        "format_version": 1, "status": "draft",
        "script": {"language": "ru"},
        "timeline": {"final_duration_seconds": 6.0},
        "blocks": [], "log": [],
        "phrases": [{"id": "p1", "text": "три вопроса", "block_index": 0,
                     "coverage": "hyperframes", "window_id": "w1"}],
        "windows": [{"id": "w1", "phrase_ids": ["p1"], "block_index": 0,
                     "coverage": "hyperframes", "zone": "fullscreen",
                     "safe_to_skip_avatar": True,
                     "effect": {"type": "chart_bars",
                                "hyperframes": {"block": "task_list"}}}],
    }
    report = validate_edit_plan(plan, require_final=False, require_asset_files=False)
    assert not any("HeyGen skip" in e for e in report["errors"])


def test_блок_без_ведущего_помечается_как_не_требующий_аватара():
    from reels_factory.editplan import _refresh_blocks_and_summary

    plan = {
        "blocks": [{"index": 0, "role": "development", "start": 0.0, "end": 6.0}],
        "phrases": [{"id": "p1", "block_index": 0, "coverage": "hyperframes",
                     "window_id": "w1"}],
        "windows": [{"id": "w1", "phrase_ids": ["p1"], "block_index": 0,
                     "coverage": "hyperframes", "safe_to_skip_avatar": True}],
        "summary": {},
    }
    _refresh_blocks_and_summary(plan)
    assert plan["blocks"][0]["avatar_required"] is False
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_editplan.py -k "пропуск or не_требующий" -v`
Ожидание: FAIL — валидатор запрещает, блок считается требующим аватара.

- [ ] **Шаг 3: Реализация**

В `validate_edit_plan` (`editplan.py:2456`) условие, запрещающее пропуск, расширить: пропуск разрешён, если **либо** полноэкранная видеовставка, **либо** полноэкранная графика:

```python
        faceless = (
            window.get("coverage") == "full_broll"
            and (window.get("effect") or {}).get("type") == "broll"
        ) or (
            window.get("coverage") == "hyperframes"
            and window.get("zone") == "fullscreen"
        )
        if window.get("safe_to_skip_avatar") and not faceless:
            errors.append(
                f'{window["id"]}: HeyGen skip разрешён только там, где ведущей '
                "нет в кадре")
```

В `_refresh_blocks_and_summary` (`:1895`, логика на `:1908-1912`) условие «блок не требует аватара» расширить теми же двумя случаями: фраза считается безлицевой, если её окно помечено `safe_to_skip_avatar` **и** её покрытие входит в `{"full_broll", "hyperframes"}`.

**Третье место, без которого ничего не заработает** — блочная проверка `editplan.py:2589-2603`: там требуется, чтобы у блока с `avatar_required=False` **все** окна были `full_broll` с безопасным пропуском. Расширить тем же условием `faceless`.

**Где ставить `safe_to_skip_avatar=True`.** В местах создания окон с `coverage="hyperframes"`: `editplan.py:1538`, `:1569`, `:1632`, `:1721`, `:2829`. Но **не безусловно**: `validate_edit_plan:2489-2493` запрещает пропуск для окон, чей эффект несёт метку `visual_director` (её ставит `_visual_director_effect`, `:926-946`). Такие окна — `:1632` и `:2829`. Для них флаг не ставим, иначе `enrich_visuals_with_llm` и `ensure_assetless_visual_coverage` бросят ошибку и упадут существующие тесты (`test_editplan.py:778`, `:823`).

Правило одной строкой: `safe_to_skip_avatar=True` ставим окнам `hyperframes` с зоной `fullscreen`, у которых в эффекте **нет** ключа `visual_director`.

- [ ] **Шаг 4: Запустить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_editplan.py tests/test_pipeline.py -v`
Ожидание: зелено. Тесты, считающие число заказанных кусков аватара, могут измениться — это и есть экономия; сверить числа и поправить ожидания.

- [ ] **Шаг 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/editplan.py plugins/reels-factory/engine/tests/test_editplan.py
git commit -m "feat(editplan): skip avatar under fullscreen graphics"
```

---

### Задача 7: Гейты раскадровки

**Файлы:**
- Создать: `plugins/reels-factory/engine/src/reels_factory/hf_gates.py`
- Создать: `plugins/reels-factory/engine/tests/test_hf_gates.py`

**Интерфейсы:**
- Производит: `check_storyboard(storyboard: dict, face: dict | None) -> dict` — `D8_face`, `D9_ui_band`, `D10_frame_grid`, `D11_zone`, `D12_core_box`. Значение — `"PASS"` либо `"FAIL: ..."`.
- Контракт раскадровки, который мы требуем от агента: у каждой карточки `id`, `startSec`, `endSec`, `zone`, `contentRect`.

- [ ] **Шаг 1: Написать падающий тест**

Создать `plugins/reels-factory/engine/tests/test_hf_gates.py`:

```python
"""Гейты раскадровки: движок этого не знает, значит проверяем мы."""
from reels_factory.hf_gates import check_storyboard

FACE = {"cx": 540, "cy": 520, "h": 260}


def _card(**over):
    card = {"id": "card-01", "startSec": 0.0, "endSec": 3.0, "zone": "video-overlay",
            "contentRect": {"left": 130, "top": 980, "width": 810, "height": 260}}
    card.update(over)
    return card


def test_чистая_раскадровка_проходит():
    assert set(check_storyboard({"cards": [_card()]}, FACE).values()) == {"PASS"}


def test_карточка_на_лице_валится():
    gates = check_storyboard(
        {"cards": [_card(contentRect={"left": 300, "top": 300, "width": 500, "height": 300})]},
        FACE)
    assert gates["D8_face"].startswith("FAIL")


def test_заход_в_полосу_интерфейса_валится():
    gates = check_storyboard(
        {"cards": [_card(contentRect={"left": 130, "top": 1100, "width": 810, "height": 260})]},
        FACE)
    assert gates["D9_ui_band"].startswith("FAIL")


def test_выход_за_ядро_валится():
    gates = check_storyboard(
        {"cards": [_card(contentRect={"left": 20, "top": 980, "width": 300, "height": 200})]},
        FACE)
    assert gates["D12_core_box"].startswith("FAIL")


def test_время_вне_сетки_кадров_валится():
    gates = check_storyboard({"cards": [_card(startSec=1.017)]}, FACE)
    assert gates["D10_frame_grid"].startswith("FAIL")


def test_запрещённая_зона_валится():
    gates = check_storyboard({"cards": [_card(zone="lower-third")]}, FACE)
    assert gates["D11_zone"].startswith("FAIL")


def test_карточка_без_прямоугольника_валится():
    card = _card()
    card.pop("contentRect")
    gates = check_storyboard({"cards": [card]}, FACE)
    assert gates["D12_core_box"].startswith("FAIL")


def test_пустая_раскадровка_проходит():
    assert set(check_storyboard({"cards": []}, FACE).values()) == {"PASS"}
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_gates.py -v`
Ожидание: FAIL — модуля нет.

- [ ] **Шаг 3: Реализация**

Создать `plugins/reels-factory/engine/src/reels_factory/hf_gates.py`:

```python
"""Проверка раскадровки, которую вернул агент-сборщик.

У скила нет ни безопасных зон, ни понятия лица, ни требования класть тайминги
на сетку кадров. Проверяем сами и до рендера — после рендера чинить дороже.
"""
from __future__ import annotations

from reels_factory.hf_layout import ALLOWED_ZONES, quantize, violations


def check_storyboard(storyboard: dict, face: dict | None) -> dict:
    """Гейты раскадровки. PASS либо FAIL с перечислением карточек."""
    face_bad, ui_bad, grid_bad, zone_bad, core_bad = [], [], [], [], []

    for card in storyboard.get("cards") or []:
        card_id = card.get("id", "?")

        if card.get("zone") not in ALLOWED_ZONES:
            zone_bad.append(f'{card_id}: зона {card.get("zone")!r} не разрешена')

        for field in ("startSec", "endSec"):
            value = float(card.get(field, 0.0))
            if abs(value - quantize(value)) > 0.0005:
                grid_bad.append(f"{card_id}: {field}={value} вне сетки кадров")

        rect = card.get("contentRect")
        if not rect:
            core_bad.append(f"{card_id}: не указан прямоугольник содержимого")
            continue
        for problem in violations(rect, face):
            if "лицо" in problem:
                face_bad.append(f"{card_id}: {problem}")
            elif "интерфейс" in problem:
                ui_bad.append(f"{card_id}: {problem}")
            else:
                core_bad.append(f"{card_id}: {problem}")

    def gate(problems: list[str]) -> str:
        return "PASS" if not problems else "FAIL: " + "; ".join(problems)

    return {"D8_face": gate(face_bad), "D9_ui_band": gate(ui_bad),
            "D10_frame_grid": gate(grid_bad), "D11_zone": gate(zone_bad),
            "D12_core_box": gate(core_bad)}
```

- [ ] **Шаг 4: Запустить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_gates.py -v`
Ожидание: 8 passed.

- [ ] **Шаг 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/hf_gates.py plugins/reels-factory/engine/tests/test_hf_gates.py
git commit -m "feat(hf): gate the storyboard on face, UI band, grid and core"
```

---

## Фаза Б — сборка агентом под скилами

### Задача 8: Задание агенту вместе с содержанием вставок

**Файлы:**
- Создать: `plugins/reels-factory/engine/src/reels_factory/hf_brief.py`
- Создать: `plugins/reels-factory/engine/tests/test_hf_brief.py`

**Интерфейсы:**
- Производит: `write_brief(rdir, plan, *, face, duration, media=None, retry_reason=None) -> Path`; `STYLE_NAME = "minimal"`.
- **В задание уходит содержание каждого окна:** текст фраз, заголовок вставки, её пункты, имя блока. Без этого агент придумает содержимое сам, план перестанет отвечать за картинку, а правило граундинга будет сторожить данные, которых агент не видит.
- `retry_reason` — текст провала гейтов при повторной сборке.

- [ ] **Шаг 1: Написать падающий тест**

Создать `plugins/reels-factory/engine/tests/test_hf_brief.py`:

```python
"""Задание агенту: правила числами и содержание вставок из плана."""
from reels_factory.hf_brief import STYLE_NAME, write_brief

PLAN = {
    "phrases": [{"id": "p1", "text": "первый вопрос кому продаём"}],
    "windows": [{
        "id": "window-000", "coverage": "hyperframes", "zone": "fullscreen",
        "phrase_ids": ["p1"], "final_timing": {"start": 0.0, "end": 6.0},
        "effect": {"type": "chart_bars", "title": "Три вопроса",
                   "hyperframes": {"block": "task_list",
                                   "variables": {"title": "Три вопроса",
                                                 "items": ["Кому продаём"]}}},
    }],
}


def _text(tmp_path, **kw):
    return write_brief(tmp_path, PLAN, face={"cx": 540, "cy": 520, "h": 260},
                       duration=41.5, **kw).read_text(encoding="utf-8")


def test_правила_числами(tmp_path):
    text = _text(tmp_path)
    assert "1080" in text and "1920" in text
    assert STYLE_NAME in text
    assert "Montserrat" in text
    assert "130" in text and "1300" in text
    assert "storyboard.json" in text and "contentRect" in text
    assert "1/30" in text


def test_содержание_вставки_передано(tmp_path):
    text = _text(tmp_path)
    assert "window-000" in text
    assert "Три вопроса" in text
    assert "Кому продаём" in text
    assert "task_list" in text
    assert "первый вопрос кому продаём" in text


def test_свободные_полосы_указаны(tmp_path):
    text = _text(tmp_path)
    assert "свободн" in text.lower()


def test_запреты_прописаны(tmp_path):
    text = _text(tmp_path)
    assert "не запускай" in text.lower()
    assert "внешн" in text.lower()


def test_причина_повтора_попадает_в_задание(tmp_path):
    text = _text(tmp_path, retry_reason="D8_face: card-01 перекрывает лицо")
    assert "перекрывает лицо" in text


def test_материал_перечислен(tmp_path):
    media = [{"file": "media/shot-1.png", "window_id": "window-000",
              "what": "снимок сайта"}]
    text = _text(tmp_path, media=media)
    assert "media/shot-1.png" in text and "снимок сайта" in text
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_brief.py -v`
Ожидание: FAIL — модуля нет.

- [ ] **Шаг 3: Реализация**

Создать `plugins/reels-factory/engine/src/reels_factory/hf_brief.py`:

```python
"""Задание агенту-сборщику композиции.

Монтажные решения принимает скил HeyGen. Наше дело — сообщить то, чего он
знать не может: вертикальный формат, наш стиль, безопасные полосы, где лицо,
какие тайминги истина и ЧТО показывать. Всё числами, без «сделай красиво».
"""
from __future__ import annotations

from pathlib import Path

from reels_factory.config import FPS, OUT_H, OUT_W
from reels_factory.face_detect import free_bands
from reels_factory.hf_layout import CORE_BOX, UI_BAND_TOP

STYLE_NAME = "minimal"
FONTS = "Montserrat, Inter"


def _window_block(window: dict, text_by_id: dict) -> str:
    timing = window.get("final_timing") or {}
    effect = window.get("effect") or {}
    variables = (effect.get("hyperframes") or {}).get("variables") or {}
    speech = " ".join(text_by_id.get(pid, "") for pid in window.get("phrase_ids") or [])

    lines = [
        f'### Окно `{window.get("id")}` — {timing.get("start")}–{timing.get("end")} с',
        f'- зона карточки: `{window.get("zone")}`',
        f'- что звучит: «{speech.strip()}»',
    ]
    if effect.get("type") and effect["type"] != "none":
        lines.append(f'- тип вставки: `{effect["type"]}`')
    block = (effect.get("hyperframes") or {}).get("block")
    if block:
        lines.append(f"- готовый блок: `{block}`")
    title = variables.get("title") or effect.get("title")
    if title:
        lines.append(f"- заголовок: «{title}»")
    items = [str(x) for x in (variables.get("items") or []) if isinstance(x, str)]
    if items:
        lines.append("- пункты: " + "; ".join(f"«{i}»" for i in items))
    if effect.get("type") in (None, "none"):
        lines.append("- вставки нет: показывай ведущую, карточку не рисуй")
    return "\n".join(lines)


def write_brief(rdir, plan: dict, *, face: dict | None, duration: float,
                media: list[dict] | None = None, retry_reason: str | None = None) -> Path:
    """Записать BRIEF.md рядом с материалом. Возвращает путь."""
    rdir = Path(rdir)
    rdir.mkdir(parents=True, exist_ok=True)

    text_by_id = {p["id"]: p.get("text", "") for p in plan.get("phrases") or []}
    windows = "\n\n".join(_window_block(w, text_by_id)
                          for w in plan.get("windows") or []) or "Окон нет."

    bands = "\n".join(
        f'- left={b["left"]}, top={b["top"]}, width={b["width"]}, height={b["height"]}'
        for b in free_bands(face)
    ) or "- свободных полос нет: карточки не ставь"

    face_line = (
        f'Лицо ведущей: центр ({face["cx"]}, {face["cy"]}), высота головы {face["h"]} px. '
        "Ведущая стоит по центру кадра, поэтому ставить карточку можно только в "
        "свободные полосы ниже."
        if face else "Лицо не найдено — считай запретной всю среднюю треть кадра."
    )

    media_block = "\n".join(
        f'- `{item["file"]}` → окно `{item["window_id"]}`: {item["what"]}'
        for item in (media or [])
    ) or "Материала нет."

    retry_block = (
        f"\n## Повторная сборка\n\nПрошлая версия не прошла проверку:\n\n"
        f"{retry_reason}\n\nИсправь именно это.\n"
        if retry_reason else ""
    )

    text = f"""# Задание на сборку композиции
{retry_block}
## Что надо сделать

Собрать композицию, в которой:

1. `base.mp4` играет **во весь кадр** от начала до конца ролика — это видео с ведущей.
2. `voice.wav` — **единственная аудиодорожка** композиции. Звук самого `base.mp4`
   выключен: у видеоэлемента `muted`, дорожка монтируется отдельным элементом.
3. **Пословные субтитры** построены по `words.json`: слово появляется ровно в свой
   `start`. Группы до пяти слов, разрыв на знаке препинания от трёх.
4. Поверх этого — графические карточки по окнам плана (раздел «Что показывать»).

Без пунктов 1–3 ролик не примут: без звука падает нормализация громкости,
без субтитров — проверка соответствия речи.

## Материал (лежит в public/)

- `base.mp4` — видео с ведущей, {OUT_W}×{OUT_H}, {FPS} кадров/с, длительность {duration:g} с
- `voice.wav` — единая озвучка, источник истины по времени
- `words.json` — **готовые пословные тайминги**. Своё распознавание речи **не запускай**:
  оно даст худшую точность и работает по-английски.
- `vendor/gsap.min.js` — библиотека анимации локально

## Формат

Холст {OUT_W}×{OUT_H}, {FPS} кадров/с, общая длительность ровно {duration:g} с.

## Стиль

Стиль `{STYLE_NAME}` из библиотеки стилей скила, один на весь ролик. Шрифты —
{FONTS}: только они содержат кириллицу и казахские ә ғ қ ң ө ұ ү һ і. Шрифты из
комплекта скила кириллицы не содержат. Подключай их именем семейства в
`font-family` — движок сам встроит их при компиляции. Ссылок на шрифты не пиши.

## Раскладка и зоны

Раскладка одна на весь ролик — `overlay`: видео во весь кадр, карточка поверх.
Разрешены только две зоны карточки: `video-overlay` (ведущая в кадре) и
`fullscreen` (ведущей в кадре нет, кадр отдан показу). Зоны `lower-third`,
`side-panel`, `whiteboard-area` в вертикали лежат в полосе интерфейса
приложения и запрещены.

## Жёсткие границы

- **Ядро вставки:** содержимое целиком внутри left={CORE_BOX["left"]},
  top={CORE_BOX["top"]}, width={CORE_BOX["width"]}, height={CORE_BOX["height"]}.
- **Полоса интерфейса:** ниже y={UI_BAND_TOP} не должно быть ничего, включая субтитры.
- {face_line}
- **Свободные полосы для карточек:**
{bands}
- **Сетка кадров:** любое время карточки кратно 1/{FPS} секунды.
- **Стык клипов:** клип живёт на кадр дольше своего окна, поэтому не ставь конец
  карточки вплотную к началу следующей — оставляй зазор не меньше 1/{FPS} секунды.
- **Внешних ссылок нет.** Только локальные файлы.

## Что показывать по окнам

Содержание задано планом монтажа. Не придумывай своё и не добавляй предметов,
которых нет в тексте окна.

{windows}

## Материал для вставок

{media_block}

## Что вернуть

1. `public/index.html` — собранная композиция.
2. `storyboard.json`. Формат скила сохраняй, но **добавь в каждую карточку поле
   `contentRect`** — прямоугольник видимого содержимого в пикселях. По нему
   проверяются границы и лицо, без него сборка не принимается.

```json
{{"cards": [
  {{"id": "card-01", "startSec": 0.0, "endSec": 3.0, "zone": "video-overlay",
    "contentRect": {{"left": 130, "top": 980, "width": 810, "height": 260}}}}
]}}
```
"""
    path = rdir / "BRIEF.md"
    path.write_text(text, encoding="utf-8")
    return path
```

- [ ] **Шаг 4: Запустить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_brief.py -v`
Ожидание: 6 passed.

- [ ] **Шаг 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/hf_brief.py plugins/reels-factory/engine/tests/test_hf_brief.py
git commit -m "feat(hf): brief carries rules and the plan's insert content"
```

---

### Задача 9: Запуск агента под скилами HeyGen

**Файлы:**
- Создать: `plugins/reels-factory/engine/src/reels_factory/hf_agent.py`
- Создать: `plugins/reels-factory/engine/tests/test_hf_agent.py`

**Интерфейсы:**
- Производит: `HeyGenAgentRunner` с методом `run(prompt: str, cwd) -> str` и полем `total_cost_usd`; `build_with_agent(rdir, *, runner=None) -> dict`.
- **Почему не `ClaudeSkillRunner`:** он работает в изолированном профиле `~/.reels-factory/claude` с `--setting-sources ""` (`llm.py:88`) и скилы HeyGen из `~/.claude/skills` не увидит. Здесь нужен обычный профиль пользователя, право писать файлы и запускать команды, рабочая папка ролика и таймаут под десятиминутную сборку.

- [ ] **Шаг 1: Написать падающий тест**

Создать `plugins/reels-factory/engine/tests/test_hf_agent.py`:

```python
"""Композицию собирает агент под скилами HeyGen, а не наш код."""
import json

import pytest

from reels_factory.hf_agent import build_with_agent


class _Runner:
    def __init__(self, rdir, make_files=True):
        self.rdir, self.make_files, self.prompts = rdir, make_files, []
        self.total_cost_usd = 0.0

    def run(self, prompt: str, cwd=None) -> str:
        self.prompts.append(prompt)
        if self.make_files:
            (self.rdir / "public").mkdir(parents=True, exist_ok=True)
            (self.rdir / "public" / "index.html").write_text("<html></html>", encoding="utf-8")
            (self.rdir / "storyboard.json").write_text(json.dumps({"cards": []}),
                                                       encoding="utf-8")
        return "готово"


def test_вход_через_парадную_дверь(tmp_path):
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    runner = _Runner(tmp_path)
    build_with_agent(tmp_path, runner=runner)
    assert runner.prompts and runner.prompts[0].lstrip().startswith("/hyperframes")


def test_раскадровка_возвращается(tmp_path):
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    assert build_with_agent(tmp_path, runner=_Runner(tmp_path)) == {"cards": []}


def test_без_композиции_ошибка(tmp_path):
    (tmp_path / "BRIEF.md").write_text("задание", encoding="utf-8")
    with pytest.raises(RuntimeError, match="index.html"):
        build_with_agent(tmp_path, runner=_Runner(tmp_path, make_files=False))


def test_без_задания_ошибка(tmp_path):
    with pytest.raises(RuntimeError, match="BRIEF"):
        build_with_agent(tmp_path, runner=_Runner(tmp_path))


def test_команда_видит_обычный_профиль_и_права(monkeypatch, tmp_path):
    from reels_factory import hf_agent

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["env"] = kw.get("env") or {}
        seen["cwd"] = kw.get("cwd")

        class P:
            returncode = 0
            stdout = json.dumps({"result": "ок", "total_cost_usd": 0.02})
            stderr = ""

        return P()

    monkeypatch.setattr(hf_agent.subprocess, "run", fake_run)
    runner = hf_agent.HeyGenAgentRunner()
    runner.run("/hyperframes привет", cwd=tmp_path)

    assert "CLAUDE_CONFIG_DIR" not in seen["env"]
    assert "--setting-sources" not in " ".join(map(str, seen["cmd"]))
    assert "acceptEdits" in " ".join(map(str, seen["cmd"]))
    assert str(seen["cwd"]) == str(tmp_path)
    assert runner.total_cost_usd == 0.02
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_agent.py -v`
Ожидание: FAIL — модуля нет.

- [ ] **Шаг 3: Реализация**

Создать `plugins/reels-factory/engine/src/reels_factory/hf_agent.py`:

```python
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
```

- [ ] **Шаг 4: Запустить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_agent.py -v`
Ожидание: 5 passed.

- [ ] **Шаг 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/hf_agent.py plugins/reels-factory/engine/tests/test_hf_agent.py
git commit -m "feat(hf): run the composing agent with HeyGen skills visible"
```

---

### Задача 10: Возобновляемые шаги и полная сборка

**Файлы:**
- Создать: `plugins/reels-factory/engine/src/reels_factory/hf_render.py`
- Создать: `plugins/reels-factory/engine/tests/test_hf_render.py`

**Интерфейсы:**
- Производит: `STEPS`, `step_done`, `run_step`, `reset_step`, `_cli(*args, cwd)`, `assemble_hyperframes(...) -> dict` с ключами `{"mp4", "dur", "timed_scenario", "words_fixed", "gates", "agent_cost_usd"}`.
- **Повтор при провале гейтов:** маркер `compose` сбрасывается, задание переписывается с причиной провала, агент зовётся ещё раз. Всего до двух попыток.
- `transcribe` не вызываем: слова уже лежат в `public/words.json`, и задание велит агенту брать их оттуда.

- [ ] **Шаг 1: Написать падающий тест**

Создать `plugins/reels-factory/engine/tests/test_hf_render.py`:

```python
"""Сборка разбита на шаги; провал гейтов запускает повтор."""
import json
from pathlib import Path

import pytest

from reels_factory.hf_render import STEPS, reset_step, run_step, step_done


def test_шаги_в_нужном_порядке():
    assert STEPS == ("prepare", "compose", "gates", "check", "render", "loudness")


def test_маркер_отмечает_шаг(tmp_path):
    assert step_done(tmp_path, "compose") is False
    run_step(tmp_path, "compose", lambda: None)
    assert step_done(tmp_path, "compose") is True
    reset_step(tmp_path, "compose")
    assert step_done(tmp_path, "compose") is False


def test_сделанный_шаг_не_повторяется(tmp_path):
    calls = []
    run_step(tmp_path, "render", lambda: calls.append(1))
    run_step(tmp_path, "render", lambda: calls.append(2))
    assert calls == [1]


def test_упавший_шаг_не_отмечается(tmp_path):
    with pytest.raises(RuntimeError):
        run_step(tmp_path, "check", lambda: (_ for _ in ()).throw(RuntimeError("упал")))
    assert step_done(tmp_path, "check") is False


def _fakes(monkeypatch, tmp_path, storyboards):
    from reels_factory import hf_render

    calls = []

    def fake_cli(*args, cwd):
        calls.append(args)
        if args[0] == "render":
            Path(args[args.index("--output") + 1]).write_bytes(b"mp4")

    monkeypatch.setattr(hf_render, "_cli", fake_cli)
    monkeypatch.setattr(hf_render, "_normalize_loudness",
                        lambda src, dst: (dst.write_bytes(b"n"), dst)[1])
    monkeypatch.setattr(hf_render, "_concat_islands", lambda *a, **k: tmp_path / "src.mp4")
    monkeypatch.setattr(hf_render, "vendor_gsap", lambda public: public)
    monkeypatch.setattr(hf_render, "face_box_for",
                        lambda video, out, **k: {"cx": 540, "cy": 520, "h": 260})

    queue = list(storyboards)

    def fake_agent(rdir, *, runner=None):
        (Path(rdir) / "public").mkdir(parents=True, exist_ok=True)
        (Path(rdir) / "public" / "index.html").write_text("<html></html>", encoding="utf-8")
        board = queue.pop(0)
        (Path(rdir) / "storyboard.json").write_text(json.dumps(board), encoding="utf-8")
        return board

    monkeypatch.setattr(hf_render, "build_with_agent", fake_agent)
    (tmp_path / "src.mp4").write_bytes(b"")
    (tmp_path / "voice.wav").write_bytes(b"")
    (tmp_path / "face.json").write_text(json.dumps({"cx": 540, "cy": 520, "h": 260}),
                                        encoding="utf-8")
    return calls


PLAN = {"windows": [], "phrases": [], "log": [],
        "timeline": {"final_duration_seconds": 6.0}}
TIMED = {"total": 6.0, "blocks": [{"role": "hook", "start": 0.0, "end": 6.0,
                                   "speech": "кому продаём"}]}
GOOD = {"cards": []}
BAD = {"cards": [{"id": "c1", "startSec": 0.0, "endSec": 3.0, "zone": "video-overlay",
                  "contentRect": {"left": 130, "top": 1100, "width": 810, "height": 260}}]}


def test_сборка_проходит_все_шаги(tmp_path, monkeypatch):
    from reels_factory import hf_render

    calls = _fakes(monkeypatch, tmp_path, [GOOD])
    res = hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav",
        alignment_words=[{"start": 0.2, "end": 0.9, "text": "Кому"}])

    assert (tmp_path / "BRIEF.md").exists()
    assert (tmp_path / "public" / "words.json").exists()
    assert not any(a[0] == "transcribe" for a in calls)
    assert any(a[0] == "check" for a in calls)
    assert any(a[0] == "render" for a in calls)
    assert res["gates"]["D8_face"] == "PASS"
    assert Path(res["mp4"]).exists()


def test_провал_гейтов_вызывает_повтор(tmp_path, monkeypatch):
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [BAD, GOOD])
    res = hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=[])
    assert res["gates"]["D9_ui_band"] == "PASS"
    assert "интерфейс" in (tmp_path / "BRIEF.md").read_text(encoding="utf-8")


def test_две_неудачи_подряд_роняют_сборку(tmp_path, monkeypatch):
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [BAD, BAD])
    with pytest.raises(RuntimeError, match="интерфейс"):
        hf_render.assemble_hyperframes(
            tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
            master_audio=tmp_path / "voice.wav", alignment_words=[])
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_render.py -v`
Ожидание: FAIL — модуля нет.

- [ ] **Шаг 3: Реализация**

Создать `plugins/reels-factory/engine/src/reels_factory/hf_render.py`:

```python
"""Сборка ролика движком HyperFrames, разбитая на возобновляемые шаги.

Длинная агентская сессия может оборваться посреди работы — это наблюдалось.
Каждый шаг пишет файл-маркер, повторный запуск подхватывает с места обрыва.

Шаг громкости пишет НОВЫЙ файл, а не заменяет исходный: иначе обрыв между
заменой и записью маркера привёл бы к повторной нормализации.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from reels_factory.config import FFMPEG, FPS, LUFS_TARGET, OUT_H, TP_TARGET
from reels_factory.face_detect import face_box_for, load_face
from reels_factory.hf_agent import build_with_agent
from reels_factory.hf_assets import vendor_gsap
from reels_factory.hf_brief import write_brief
from reels_factory.hf_gates import check_storyboard
from reels_factory.hf_layout import UI_BAND_TOP, quantize
from reels_factory.hyperframes_blocks import _HF_VERSION

STEPS = ("prepare", "compose", "gates", "check", "render", "loudness")
MAX_COMPOSE_ATTEMPTS = 2

# запретная полоса для гейта движка: доли кадра от UI_BAND_TOP до низа
CAPTION_ZONE = f"x0=0;y0={UI_BAND_TOP / OUT_H:.3f};x1=1;y1=1;severity=error"


def _marker(rdir: Path, step: str) -> Path:
    return Path(rdir) / f".hf-{step}.done"


def step_done(rdir, step: str) -> bool:
    return _marker(Path(rdir), step).exists()


def reset_step(rdir, step: str) -> None:
    _marker(Path(rdir), step).unlink(missing_ok=True)


def run_step(rdir, step: str, fn):
    """Выполнить шаг, если он ещё не выполнен. Возвращает результат fn."""
    rdir = Path(rdir)
    if step_done(rdir, step):
        return None
    result = fn()
    _marker(rdir, step).write_text("ok", encoding="utf-8")
    return result


def _cli(*args: str, cwd) -> None:
    """Вызов CLI движка. На Windows npx резолвится только через shell.

    Кавычим КАЖДЫЙ аргумент: у `--caption-zone` значение содержит `;` и `=`,
    а это разделители для cmd.exe и батника npx.cmd.
    """
    quoted = " ".join(f'"{a}"' for a in args)
    command = f'npx --yes hyperframes@{_HF_VERSION} {quoted}'
    result = subprocess.run(command, cwd=str(cwd), capture_output=True,
                            text=True, encoding="utf-8", shell=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"hyperframes {args[0]} упал ({result.returncode}): "
            f"{(result.stderr or result.stdout)[:500]}")


def _normalize_words(words: list[dict]) -> list[dict]:
    return [{"start": round(float(w["start"]), 3),
             "end": round(float(w["end"]), 3),
             "text": str(w.get("text") or w.get("word") or "")} for w in words]


def _normalize_loudness(src: Path, dst: Path) -> Path:
    subprocess.run(
        [FFMPEG, "-y", "-i", str(src),
         "-af", f"loudnorm=I={LUFS_TARGET}:TP={TP_TARGET}:LRA=11",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", str(dst)],
        check=True, capture_output=True)
    return dst


def _concat_islands(rdir: Path, avatar_mp4s: list, avatar_render_plan: dict | None,
                    timed_scenario: dict, height: int = OUT_H) -> Path:
    """Беззвучная база из клипов аватара.

    Островов по умолчанию нет (`avatar_islands.py:44` — enabled False), и тогда
    приходит по клипу на блок: их надо склеить по длительностям блоков, иначе
    база окажется длиной первого блока. Для этого случая в revideo есть готовая
    _concat_master_visuals (`revideo_render.py:139`).
    """
    from reels_factory.revideo_render import (
        _concat_avatar_island_visuals, _concat_master_visuals,
    )

    if avatar_render_plan is not None:
        return _concat_avatar_island_visuals(rdir, avatar_mp4s, avatar_render_plan,
                                             height=height)
    block_durations = [float(b["end"]) - float(b["start"])
                       for b in timed_scenario["blocks"]]
    return _concat_master_visuals(rdir, avatar_mp4s, block_durations, height=height)


def _media_from_plan(plan: dict, public: Path) -> list[dict]:
    """Локальные файлы вставок: копируем в public/media и описываем агенту."""
    media = []
    for window in plan.get("windows") or []:
        asset = window.get("asset") or {}
        source = asset.get("path")
        if not source or not Path(source).exists():
            continue
        target = public / "media" / Path(source).name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        media.append({"file": f"media/{target.name}",
                      "window_id": window["id"],
                      "what": window.get("visual_intent") or "материал вставки"})
    return media


def assemble_hyperframes(rdir, timed_scenario: dict, *, edit_plan: dict,
                         avatar_mp4s: list, master_audio, alignment_words: list,
                         avatar_render_plan: dict | None = None,
                         out_mp4=None, agent_runner=None) -> dict:
    """Материал -> агент под скилами -> гейты -> рендер -> громкость."""
    rdir = Path(rdir).resolve()
    public = rdir / "public"
    words = _normalize_words(alignment_words)
    duration = quantize(float(timed_scenario.get("total") or 0.0))

    def prepare() -> None:
        public.mkdir(parents=True, exist_ok=True)
        base = _concat_islands(rdir, avatar_mp4s, avatar_render_plan, timed_scenario)
        shutil.copyfile(str(base), str(public / "base.mp4"))
        shutil.copyfile(str(master_audio), str(public / "voice.wav"))
        (public / "words.json").write_text(
            json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        vendor_gsap(public)
        face_box_for(public / "base.mp4", rdir / "face.json")
        write_brief(rdir, edit_plan, face=load_face(rdir), duration=duration,
                    media=_media_from_plan(edit_plan, public))

    run_step(rdir, "prepare", prepare)

    gate_result, reason = None, None
    for attempt in range(MAX_COMPOSE_ATTEMPTS):
        if reason is not None:
            reset_step(rdir, "compose")
            reset_step(rdir, "gates")
            write_brief(rdir, edit_plan, face=load_face(rdir), duration=duration,
                        media=_media_from_plan(edit_plan, public), retry_reason=reason)

        board = run_step(rdir, "compose",
                         lambda: build_with_agent(rdir, runner=agent_runner))
        if board is None:
            board = json.loads((rdir / "storyboard.json").read_text(encoding="utf-8"))

        result = check_storyboard(board, load_face(rdir))
        failed = [f"{k}: {v}" for k, v in result.items() if v.startswith("FAIL")]
        if not failed:
            gate_result = result
            (rdir / "gates.json").write_text(json.dumps(result, ensure_ascii=False),
                                             encoding="utf-8")
            _marker(rdir, "gates").write_text("ok", encoding="utf-8")
            break
        reason = "; ".join(failed)
        if attempt == MAX_COMPOSE_ATTEMPTS - 1:
            raise RuntimeError("раскадровка не прошла гейты — " + reason)

    run_step(rdir, "check",
             lambda: _cli("check", "public", "--caption-zone", CAPTION_ZONE, cwd=rdir))

    raw = rdir / "reel.raw.mp4"
    run_step(rdir, "render",
             lambda: _cli("render", "public", "--output", str(raw),
                          "--fps", str(FPS), "--quality", "standard", cwd=rdir))

    final = Path(out_mp4) if out_mp4 else rdir / "reel.mp4"
    run_step(rdir, "loudness", lambda: _normalize_loudness(raw, final))

    (rdir / "scenario.timed.json").write_text(
        json.dumps(timed_scenario, ensure_ascii=False, indent=1), encoding="utf-8")
    (rdir / "words.fixed.json").write_text(
        json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")

    return {"mp4": str(final), "dur": duration, "timed_scenario": timed_scenario,
            "words_fixed": words, "gates": gate_result,
            "agent_cost_usd": getattr(agent_runner, "total_cost_usd", 0.0)}
```

- [ ] **Шаг 4: Запустить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_render.py -v`
Ожидание: 7 passed.

- [ ] **Шаг 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/hf_render.py plugins/reels-factory/engine/tests/test_hf_render.py
git commit -m "feat(hf): assemble with gate-driven retry, no transcribe step"
```

---

### Задача 11: Мастер-звук по умолчанию

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/config.py` (дефолт `master_audio.enabled`)
- Изменить: `plugins/reels-factory/engine/tests/` — тесты, полагавшиеся на путь без мастер-звука

**Зачем отдельной задачей:** новый сборщик работает только с единой озвучкой. Смена дефолта затрагивает много тестов, и делать это одновременно с переключением сборщика — значит не понять, что именно сломалось.

- [ ] **Шаг 1: Написать падающий тест**

Дописать в `plugins/reels-factory/engine/tests/test_master_audio.py`:

```python
def test_мастер_звук_включён_по_умолчанию(monkeypatch):
    from reels_factory.master_audio import master_audio_enabled

    monkeypatch.delenv("RF_MASTER_AUDIO_ENABLED", raising=False)
    assert master_audio_enabled({}) is True
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_master_audio.py -k мастер -v`
Ожидание: FAIL — сейчас дефолт `False`.

- [ ] **Шаг 3: Реализация**

Дефолт живёт в `master_audio.py:48-53`, в функции `master_audio_enabled(config)`; там же перекрытие через переменную окружения `RF_MASTER_AUDIO_ENABLED`. Перевести дефолт в `True`, поведение переменной окружения не менять.

- [ ] **Шаг 4: Прикрыть тесты конвейера фейком мастер-звука**

Из 27 тестов `test_pipeline.py` 26 идут через помощник `_fakes`, и лишь пять передают `master_audio_fn`. После смены дефолта остальные позовут настоящую сборку мастер-звука — то есть сеть и ElevenLabs. **До** смены дефолта добавить фейк мастер-звука в сам `_fakes`, чтобы он подставлялся всем тестам по умолчанию.

- [ ] **Шаг 5: Прогнать весь набор и починить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest -q -m "not slow"`
Ожидание: для каждого упавшего решить: либо тест проверяет поведение, которое сохраняется — поправить ожидания; либо тест проверяет путь без мастер-звука — переписать на мастер-звук, потому что старого пути больше нет.

- [ ] **Шаг 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/config.py plugins/reels-factory/engine/tests
git commit -m "feat(config): master audio is the default path"
```

---

### Задача 12: Переключить конвейер

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/pipeline.py` (`:36` импорт, `:39` сборщик, `:346-357` вызов, после `verify_reel`)
- Изменить: `plugins/reels-factory/engine/tests/test_pipeline.py` (фейк `:65-80` и ассерты)

**Что делать с параметрами старого вызова:**
- `format`, `voice_wavs` — путь `fullscreen` не переносится, добавляется явная ошибка.
- `caption_fixes` — уже посчитаны на `pipeline.py:152`; применяем к словам через `apply_caption_fixes`, который надо **дописать в импорт** на `:36`.
- `grade`, `grain`, `zoom`, `flash` — приёмы старой сцены, в новом пути их нет; из вызова уходят, флаги в конфиге остаются без действия.
- `master_timed_scenario` — новый сборщик получает ретаймленный сценарий первым позиционным аргументом.
- `out_mp4` — передаётся явно.

- [ ] **Шаг 1: Написать падающий тест**

Дописать в `plugins/reels-factory/engine/tests/test_pipeline.py`:

```python
def test_конвейер_собирает_новым_движком():
    import reels_factory.pipeline as pipeline

    assert pipeline._assemble.__module__ == "reels_factory.hf_render"
    assert pipeline._assemble.__name__ == "assemble_hyperframes"
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_pipeline.py::test_конвейер_собирает_новым_движком -v`
Ожидание: FAIL.

- [ ] **Шаг 3: Переключить импорт и вызов**

`pipeline.py:36` — дописать в существующий импорт из `compose`:

```python
from reels_factory.compose import apply_caption_fixes, build_caption_fixes
```

`pipeline.py:39`:

```python
from reels_factory.hf_render import assemble_hyperframes as _assemble
```

Вызов `:346-357` заменить на:

```python
        if fmt == "fullscreen":
            return fail("assemble", RuntimeError(
                "формат fullscreen не поддержан новым сборщиком"))
        if master is None:
            return fail("assemble", RuntimeError(
                "новый сборщик работает только с мастер-звуком; "
                "включи master_audio"))
        out_mp4 = wd / "reel.mp4"
        res = assemble_fn(wd,
                          master.timed_scenario if master else scenario,
                          edit_plan=edit_plan,
                          avatar_mp4s=avatar_mp4s or [],
                          master_audio=master.wav,
                          alignment_words=apply_caption_fixes(
                              list(master.words), caption_fixes),
                          avatar_render_plan=avatar_render_plan,
                          out_mp4=out_mp4)
```

После `verify_reel` (`:366`) дописать слияние гейтов вставок:

```python
        qa["gates"].update(res.get("gates") or {})
        qa["all_pass"] = all(
            not str(v).startswith("FAIL") for v in qa["gates"].values())
```

- [ ] **Шаг 4: Починить фейк сборщика**

В `tests/test_pipeline.py:65-80` заменить фейк, сохранив запись в `calls` и защиту `captured`:

```python
    def fake_assemble(rdir, timed_scenario, **kw):
        out = Path(kw.get("out_mp4") or (Path(rdir) / "reel.mp4"))
        out.write_bytes(b"")
        calls.append(("assemble", kw.get("avatar_render_plan"), timed_scenario))
        if captured is not None:
            captured.update(kw)
            captured["timed_scenario"] = timed_scenario
        return {"mp4": str(out), "dur": float(timed_scenario.get("total") or 0.0),
                "timed_scenario": timed_scenario,
                "words_fixed": kw.get("alignment_words") or [],
                "gates": {"D8_face": "PASS"}}
```

Пройти по файлу и поправить ассерты. Что именно исчезает из `captured` и где это используется:

- `captured["caption_fixes"]` (`:527-528`) — фиксы теперь применяются до вызова; проверять не словарь фиксов, а то, что исправленное слово пришло в `captured["alignment_words"]`;
- `captured["broll_segments"]` (`:529`, `:662`) и `captured["punch_windows"]` (`:544`) — новый сборщик их не принимает; ассерты снять вместе с проверяемым поведением;
- `captured["master_timed_scenario"]` (`:209`) — теперь `captured["timed_scenario"]`;
- `assemble_call[1]` (`:113`, `:131`, `:151`, `:449`) — это больше не формат: в новом фейке вторым элементом идёт `avatar_render_plan`;
- тест на `fullscreen` (`:129-131`) — переписать в проверку того, что конвейер падает понятной ошибкой.

- [ ] **Шаг 5: Прогнать весь набор**

Запуск: `cd plugins/reels-factory/engine && python -m pytest -q -m "not slow"`
Ожидание: зелено. Правки затронут почти все 27 тестов `test_pipeline.py` — это цена смены контракта, она предусмотрена.

- [ ] **Шаг 6: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/pipeline.py plugins/reels-factory/engine/tests/test_pipeline.py
git commit -m "feat(pipeline): switch assembly to the hyperframes path"
```

---

### Задача 13: Живая сборка на реальном материале

**Файлы:**
- Создать: `plugins/reels-factory/engine/tests/test_hf_live.py`

**Материал:** `C:\Users\123\Videos\Reels\work\bot-583558720-1784873847` — `top.mp4` (41.5 с), `reel-audio.wav`, `words.fixed.json` (102 слова), `scenario.timed.json`.

- [ ] **Шаг 1: Написать медленный тест**

Создать `plugins/reels-factory/engine/tests/test_hf_live.py`:

```python
"""Живая сборка на готовом материале. Платных вызовов к HeyGen нет."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from reels_factory.config import FFPROBE

WORK = Path(r"C:\Users\123\Videos\Reels\work\bot-583558720-1784873847")


@pytest.mark.slow
def test_живая_сборка_ролика(tmp_path):
    if not WORK.exists():
        pytest.skip("нет рабочей папки с материалом")

    from reels_factory.hf_render import assemble_hyperframes

    shutil.copyfile(WORK / "top.mp4", tmp_path / "top.mp4")
    shutil.copyfile(WORK / "reel-audio.wav", tmp_path / "voice.wav")
    words = json.loads((WORK / "words.fixed.json").read_text(encoding="utf-8"))
    timed = json.loads((WORK / "scenario.timed.json").read_text(encoding="utf-8"))
    timed["total"] = 41.5

    plan = {"timeline": {"final_duration_seconds": 41.5},
            "phrases": [{"id": "p1", "text": " ".join(w["text"] for w in words[:12])}],
            "windows": [{"id": "window-000", "coverage": "avatar",
                         "zone": "video-overlay", "phrase_ids": ["p1"],
                         "final_timing": {"start": 0.0, "end": 6.0},
                         "effect": {"type": "none"}}],
            "log": []}

    res = assemble_hyperframes(
        tmp_path, timed, edit_plan=plan, avatar_mp4s=[tmp_path / "top.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=words)

    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,nb_frames",
         "-of", "default=nw=1", res["mp4"]],
        capture_output=True, text=True, check=True).stdout
    assert "width=1080" in probe and "height=1920" in probe
    frames = int(probe.split("nb_frames=")[1].split()[0])
    assert abs(frames - 1245) <= 1, f"кадров {frames}, ожидали 1245±1"
    assert all(v == "PASS" for v in res["gates"].values())
```

- [ ] **Шаг 2: Запустить**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_live.py -v -m slow`
Ожидание: PASS. Сборка агентом плюс рендер — от десяти до двадцати минут.

- [ ] **Шаг 3: Посмотреть глазами**

```bash
ffmpeg -y -ss 15 -i <путь к reel.mp4> -frames:v 1 frame15.png
```
Проверить: лицо не перекрыто и не обрезано, ниже 1300 пикселей пусто, субтитры на своих словах, кириллица не рассыпалась.

- [ ] **Шаг 4: Коммит**

```bash
git add plugins/reels-factory/engine/tests/test_hf_live.py
git commit -m "test(hf): live assembly on real material"
```

---

## Фаза В — источники материала

### Задача 14: Снимок сайта с кэшем

**Файлы:**
- Создать: `plugins/reels-factory/engine/src/reels_factory/capture_site.py`
- Создать: `plugins/reels-factory/engine/tests/test_capture_site.py`

**Интерфейсы:**
- Производит: `cache_key(url) -> str`, `capture(url, out_dir) -> dict`, `cached_capture(url, cache_dir, max_age_days=7) -> dict`.
- Свежесть считается по времени изменения первого кадра.

- [ ] **Шаг 1: Написать падающий тест**

Создать `plugins/reels-factory/engine/tests/test_capture_site.py`:

```python
"""Снимок сайта: берётся движком, кэшируется по адресу, стареет."""
import os
import time

from reels_factory.capture_site import cache_key, cached_capture


def _fake_shot(root, url):
    target = root / cache_key(url) / "screenshots"
    target.mkdir(parents=True, exist_ok=True)
    (target / "scroll-000.png").write_bytes(b"x")
    return target / "scroll-000.png"


def test_ключ_кэша_по_адресу():
    assert cache_key("https://elevenlabs.io/") == cache_key("https://elevenlabs.io")
    assert cache_key("https://a.io") != cache_key("https://b.io")


def test_свежий_снимок_не_пересобирается(tmp_path, monkeypatch):
    from reels_factory import capture_site

    calls = []
    monkeypatch.setattr(capture_site, "capture",
                        lambda url, out_dir: calls.append(url) or {"dir": str(out_dir)})
    _fake_shot(tmp_path, "https://a.io")
    cached_capture("https://a.io", tmp_path)
    assert calls == []


def test_протухший_снимок_пересобирается(tmp_path, monkeypatch):
    from reels_factory import capture_site

    calls = []
    monkeypatch.setattr(capture_site, "capture",
                        lambda url, out_dir: calls.append(url) or {"dir": str(out_dir)})
    shot = _fake_shot(tmp_path, "https://a.io")
    old = time.time() - 8 * 24 * 3600
    os.utime(shot, (old, old))
    cached_capture("https://a.io", tmp_path, max_age_days=7)
    assert calls == ["https://a.io"]


def test_отсутствующий_снимок_собирается(tmp_path, monkeypatch):
    from reels_factory import capture_site

    calls = []
    monkeypatch.setattr(capture_site, "capture",
                        lambda url, out_dir: calls.append(url) or {"dir": str(out_dir)})
    cached_capture("https://b.io", tmp_path)
    assert calls == ["https://b.io"]
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_capture_site.py -v`
Ожидание: FAIL — модуля нет.

- [ ] **Шаг 3: Реализация**

Создать `plugins/reels-factory/engine/src/reels_factory/capture_site.py`:

```python
"""Снимок сайта как источник достоверной вставки.

Движок снимает страницу: кадры по мере прокрутки, саму страницу, шрифты и
цвета. Ключей и денег это не требует. Кэшируем по адресу — иначе на популярной
теме мы пойдём на один сайт сотни раз.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from reels_factory.hf_render import _cli


def cache_key(url: str) -> str:
    return hashlib.sha1(url.strip().rstrip("/").lower().encode("utf-8")).hexdigest()[:16]


def _result(out_dir: Path) -> dict:
    shots = sorted((out_dir / "screenshots").glob("scroll-*.png"))
    return {"dir": str(out_dir), "screenshots": [str(p) for p in shots],
            "page": str(out_dir / "extracted" / "page.html")}


def capture(url: str, out_dir) -> dict:
    """Снять сайт. Возвращает кадры прокрутки и сохранённую страницу."""
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    _cli("capture", url, "-o", str(out_dir), "--timeout", "120000",
         "--max-screenshots", "8", cwd=out_dir.parent)
    return _result(out_dir)


def cached_capture(url: str, cache_dir, max_age_days: int = 7) -> dict:
    """Снять сайт, если свежего снимка нет."""
    target = Path(cache_dir) / cache_key(url)
    shots = sorted((target / "screenshots").glob("scroll-*.png")) if target.exists() else []
    if shots and (time.time() - shots[0].stat().st_mtime) / 86400 <= max_age_days:
        return _result(target)
    return capture(url, target)
```

- [ ] **Шаг 4: Запустить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_capture_site.py -v`
Ожидание: 4 passed.

- [ ] **Шаг 5: Живая проверка**

```bash
cd plugins/reels-factory/engine && python -c "from reels_factory.capture_site import capture; print(capture('https://elevenlabs.io', 'C:/tmp/cap')['screenshots'][:2])"
```
Ожидание: два пути к PNG.

- [ ] **Шаг 6: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/capture_site.py plugins/reels-factory/engine/tests/test_capture_site.py
git commit -m "feat(capture): site screenshots with freshness cache"
```

---

### Задача 15: Экранный маршрут

**Файлы:**
- Создать: `plugins/reels-factory/engine/src/reels_factory/screen_route.py`
- Создать: `plugins/reels-factory/engine/tests/test_screen_route.py`
- Создать: `plugins/reels-factory/engine/package.json`

**Интерфейсы:**
- Производит: `validate_steps`, `chrome_path() -> str`, `build_script(steps, *, width, height, browser_path, frames_dir) -> str`, `record_route(steps, out_mp4, *, width=1080, height=1920, fps=30) -> Path`.
- Браузер берётся тот, который движок уже скачал: `~/.cache/puppeteer/chrome-headless-shell/**`.
- `puppeteer-core` ставится в `engine/node_modules`; скрипт маршрута исполняется **с рабочей папкой `engine`**, чтобы модуль разрешился, а кадры пишутся по абсолютным путям.

- [ ] **Шаг 1: Написать падающий тест**

Создать `plugins/reels-factory/engine/tests/test_screen_route.py`:

```python
"""Экранный маршрут: сценарий действий -> кадры -> видео."""
import pytest

from reels_factory.screen_route import build_script, validate_steps

STEPS = [
    {"type": "goto", "url": "https://google.com"},
    {"type": "type", "selector": "textarea[name=q]", "text": "hyperframes github"},
    {"type": "click", "selector": "h3"},
    {"type": "scroll", "pixels": 1200},
]


def test_неизвестный_шаг_отклоняется():
    with pytest.raises(ValueError, match="неизвестный шаг"):
        validate_steps([{"type": "танцевать"}])


def test_маршрут_обязан_начинаться_с_перехода():
    with pytest.raises(ValueError, match="переход"):
        validate_steps([{"type": "scroll", "pixels": 400}])


def test_пустой_маршрут_отклоняется():
    with pytest.raises(ValueError, match="пустой"):
        validate_steps([])


def test_сценарий_содержит_путь_к_браузеру_и_кадрам(tmp_path):
    script = build_script(STEPS, width=1080, height=1920,
                          browser_path="C:/chrome/chrome-headless-shell.exe",
                          frames_dir=tmp_path / "frames")
    assert "executablePath" in script and "chrome-headless-shell" in script
    assert "page.goto" in script and "hyperframes github" in script
    assert "1080" in script and "1920" in script
    assert "frames" in script
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_screen_route.py -v`
Ожидание: FAIL — модуля нет.

- [ ] **Шаг 3: Реализация**

Создать `plugins/reels-factory/engine/package.json`:

```json
{
  "name": "reels-factory-engine-node",
  "private": true,
  "description": "Node-зависимости движка: браузерная автоматизация экранных маршрутов",
  "dependencies": {
    "puppeteer-core": "^23.0.0"
  }
}
```

Создать `plugins/reels-factory/engine/src/reels_factory/screen_route.py`:

```python
"""Экранный маршрут: браузер сам проходит путь, мы записываем это видео.

Закрывает класс вставок «покажи, как до этого дойти»: ввод запроса, выбор
ссылки, переход, прокрутка. Браузер берём тот, который движок уже скачал для
рендера — второй копии Chrome на диске не появляется.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

STEP_TYPES = {"goto", "type", "click", "scroll", "wait"}
ENGINE_DIR = Path(__file__).resolve().parents[2]


def chrome_path() -> str:
    """Путь к браузеру, который движок скачал для рендера."""
    root = Path.home() / ".cache" / "puppeteer" / "chrome-headless-shell"
    candidates = sorted(root.glob("**/chrome-headless-shell*"))
    if not candidates:
        raise RuntimeError(
            "браузер движка не найден; выполни npx hyperframes@0.7.70 browser install")
    return str(candidates[-1])


def validate_steps(steps: list[dict]) -> None:
    if not steps:
        raise ValueError("пустой маршрут")
    required = {"goto": "url", "type": "text", "click": "selector",
                "scroll": "pixels", "wait": "seconds"}
    for step in steps:
        kind = step.get("type")
        if kind not in STEP_TYPES:
            raise ValueError(f"неизвестный шаг: {kind!r}")
        if required[kind] not in step:
            raise ValueError(f"шаг {kind}: нет поля {required[kind]}")
    if steps[0].get("type") != "goto":
        raise ValueError("маршрут обязан начинаться с перехода на страницу")


def build_script(steps: list[dict], *, width: int, height: int,
                 browser_path: str, frames_dir) -> str:
    """Код для браузера: пройти маршрут и снять кадры в frames_dir."""
    validate_steps(steps)
    frames = json.dumps(str(Path(frames_dir).as_posix()))
    lines = [
        "const puppeteer = require('puppeteer-core');",
        "(async () => {",
        # именно 'shell': chrome-headless-shell не понимает --headless=new
        f"  const browser = await puppeteer.launch({{headless: 'shell', "
        f"executablePath: {json.dumps(browser_path)}, "
        f"args: ['--no-sandbox', '--window-size={width},{height}']}});",
        "  const page = await browser.newPage();",
        f"  await page.setViewport({{width: {width}, height: {height}}});",
        f"  const dir = {frames};",
        "  let frame = 0;",
        "  const shot = async () => { await page.screenshot("
        "{path: `${dir}/${String(frame++).padStart(5,'0')}.png`}); };",
    ]
    for step in steps:
        kind = step["type"]
        if kind == "goto":
            lines.append(f"  await page.goto({json.dumps(step['url'])}, "
                         "{waitUntil: 'networkidle2'});")
            lines.append("  for (let i = 0; i < 15; i++) await shot();")
        elif kind == "type":
            lines.append(f"  await page.click({json.dumps(step['selector'])});")
            lines.append(f"  for (const ch of {json.dumps(step['text'])}) "
                         "{ await page.keyboard.type(ch); await shot(); }")
        elif kind == "click":
            lines.append(f"  await page.click({json.dumps(step['selector'])});")
            lines.append("  await page.waitForNetworkIdle({idleTime: 500}).catch(() => {});")
            lines.append("  for (let i = 0; i < 15; i++) await shot();")
        elif kind == "scroll":
            lines.append(f"  for (let y = 0; y < {int(step['pixels'])}; y += 24) "
                         "{ await page.evaluate(() => window.scrollBy(0, 24)); await shot(); }")
        elif kind == "wait":
            lines.append(f"  for (let i = 0; i < {int(float(step['seconds']) * 30)}; i++) "
                         "await shot();")
    lines += ["  await browser.close();", "})();"]
    return "\n".join(lines)


def record_route(steps: list[dict], out_mp4, *, width: int = 1080,
                 height: int = 1920, fps: int = 30) -> Path:
    """Пройти маршрут и собрать кадры в видео."""
    from reels_factory.config import FFMPEG

    out_mp4 = Path(out_mp4).resolve()
    frames_dir = out_mp4.parent / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    script = out_mp4.parent / "route.js"
    script.write_text(
        build_script(steps, width=width, height=height,
                     browser_path=chrome_path(), frames_dir=frames_dir),
        encoding="utf-8")

    # запускаем из каталога движка, иначе require не найдёт puppeteer-core
    result = subprocess.run(["node", str(script)], cwd=str(ENGINE_DIR),
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"маршрут не прошёл: {(result.stderr or '')[:400]}")

    subprocess.run(
        [FFMPEG, "-y", "-framerate", str(fps), "-i", str(frames_dir / "%05d.png"),
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out_mp4)],
        check=True, capture_output=True)
    return out_mp4
```

- [ ] **Шаг 4: Поставить зависимость**

```bash
cd plugins/reels-factory/engine && npm install
```

- [ ] **Шаг 5: Запустить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_screen_route.py -v`
Ожидание: 4 passed.

- [ ] **Шаг 6: Живая проверка**

```bash
cd plugins/reels-factory/engine && python -c "from reels_factory.screen_route import record_route; print(record_route([{'type':'goto','url':'https://github.com/heygen-com/hyperframes'},{'type':'scroll','pixels':1200}], 'C:/tmp/route/route.mp4'))"
```
Ожидание: путь к mp4, в нём видно прокрутку страницы.

- [ ] **Шаг 7: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/screen_route.py plugins/reels-factory/engine/tests/test_screen_route.py plugins/reels-factory/engine/package.json
git commit -m "feat(route): record a browser walkthrough as insert footage"
```

---

## Фаза Г — уборка

### Задача 16: Удалить старый рендер

**Выполняется только после того, как задача 13 прошла и результат принят человеком.**

**Файлы:**
- Изменить: `hf_render.py` (перенести склейку островов внутрь)
- Изменить: `tests/test_editplan.py:165` (и использования на `:219`, `:611`), `tests/test_hyperframes_blocks.py:7` и раздел на `:65`
- Изменить: `engine/README.md:254`, `docs/EDIT-PLAN.md:5`, `docs/VISUAL-DIRECTOR.md:5` — упоминания удаляемых файлов
- Удалить: `src/reels_factory/revideo_render.py`, `src/reels_factory/revideo_adapter.py`, `tests/test_revideo_render.py`, `tests/test_revideo_adapter.py`, каталог `revideo/`

**`tz_validator.py` и `hyperframes_blocks.py` НЕ удаляем.** Первый проверяет формат задания и его судьба решается отдельно; второй остаётся источником `_HF_VERSION` и восьми блоков, содержание которых теперь уходит агенту заданием.

- [ ] **Шаг 1: Перенести склейку островов**

Скопировать в `hf_render.py` функцию `_concat_avatar_island_visuals` из `revideo_render.py:182` **вместе с зависимостями**: вложенной `add_gap`, импортами `FFMPEG`, `OUT_W`, `FPS` из `config` и `VENC` из `compose` (в `config` его нет — он объявлен в `render.py:13`). В `_concat_islands` заменить импорт на вызов локальной копии.

- [ ] **Шаг 2: Прогнать тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest -q -m "not slow"`
Ожидание: зелено — старые файлы ещё на месте.

- [ ] **Шаг 3: Починить импортёров**

- `tests/test_editplan.py:165` — импорт `revideo_adapter` и тесты на `:219` и `:611` удалить: проекции в задание Revideo больше не существует.
- `tests/test_hyperframes_blocks.py:7` и раздел «интеграция в revideo_render» (`:65`) — удалить раздел; сами блоки остаются покрытыми остальными тестами файла.
- В `engine/README.md:254`, `docs/EDIT-PLAN.md:5`, `docs/VISUAL-DIRECTOR.md:5` — убрать упоминания удаляемых файлов и описать новый путь одной строкой.

- [ ] **Шаг 4: Удалить файлы**

```bash
git rm plugins/reels-factory/engine/src/reels_factory/revideo_render.py plugins/reels-factory/engine/src/reels_factory/revideo_adapter.py
git rm plugins/reels-factory/engine/tests/test_revideo_render.py plugins/reels-factory/engine/tests/test_revideo_adapter.py
git rm -r plugins/reels-factory/engine/revideo
```

- [ ] **Шаг 5: Прогнать тесты снова**

Запуск: `cd plugins/reels-factory/engine && python -m pytest -q -m "not slow"`
Ожидание: зелено.

- [ ] **Шаг 6: Коммит**

```bash
git commit -m "refactor(engine): drop the revideo renderer"
```

---

### Задача 17: Выбросить старый жёлтый

**Файлы:**
- Изменить: `plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py` (17 вхождений `#FFE500`)
- Создать тест: `plugins/reels-factory/engine/tests/test_hf_env.py` (дописать)

**Выполняется после задачи 16** — иначе тест поймает жёлтый в `revideo_adapter.py`, который к тому времени уже удалён.

- [ ] **Шаг 1: Написать падающий тест**

Дописать в `tests/test_hf_env.py`:

```python
def test_старый_жёлтый_не_используется():
    """Хардкод #FFE500 не был решением — он просто был. Стиль берём у скила."""
    for path in SRC.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "#ffe500" not in text, f"{path.name}: старый жёлтый"
        assert "255,229,0" not in text.replace(" ", ""), f"{path.name}: он же в rgba"
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

Запуск: `cd plugins/reels-factory/engine && python -m pytest tests/test_hf_env.py -k жёлтый -v`
Ожидание: FAIL — в `hyperframes_blocks.py` 19 вхождений `#FFE500` в 17 строках плюс 15 вхождений того же цвета в форме `rgba(255,229,0,…)`.

- [ ] **Шаг 3: Реализация**

Ввести в `hyperframes_blocks.py` константы акцента и заменить на них **обе формы** записи цвета.

Стиль `minimal` описан как «pure black/white, huge type» с акцентом `#000000` — он рассчитан на светлый фон. Наши блоки тёмные (`hyperframes_blocks.py:65, 166, 244, 319` — `#0b0b0a`, `#090a0b`), поэтому на тёмном фоне акцент этого стиля — белый:

```python
# Стиль minimal: чистые чёрный и белый, крупный шрифт, без цветных акцентов.
# Фон наших блоков тёмный, значит акцент — белый. Прежний #FFE500 решением не был.
ACCENT = "#FFFFFF"
ACCENT_SOFT = "rgba(255,255,255,0.14)"   # вместо rgba(255,229,0,…)
```

- [ ] **Шаг 4: Запустить тесты**

Запуск: `cd plugins/reels-factory/engine && python -m pytest -q -m "not slow"`
Ожидание: зелено.

- [ ] **Шаг 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py plugins/reels-factory/engine/tests/test_hf_env.py
git commit -m "refactor(style): drop the legacy yellow hardcode"
```

---

## Открытые вопросы — решить до или во время выполнения

Это не забытое, а сознательно оставленное на живую проверку. Исполнителю: если упрёшься — не выдумывай, спроси.

1. **`contentRect` — самоотчёт агента.** Гейты верят тому, что агент написал в раскадровке, а не тому, что реально отрисовалось. Честная проверка — снять кадр движком и сверить пиксели. Решается после первой живой сборки, когда станет видно, врёт ли агент.
2. **Полноэкранная карточка и ядро вставки.** Сейчас ядро применяется ко всем карточкам, включая `fullscreen`, то есть полноэкранная графика обязана уместиться в 810×970 по центру. Возможно, для `fullscreen` нужны свои границы — смотреть на живом ролике.
3. **Стеклянная карточка скила стоит не там.** В его раскладке `overlay` карточка по умолчанию занимает `{24, 1280, 1032×564}` — это целиком наша запретная полоса. Задание требует ставить содержимое в свободные полосы, но проверить, не спорит ли это с внутренними правилами стиля, можно только прогоном.
4. **Стоимость сборочной сессии не учитывается.** `assemble_hyperframes` возвращает `agent_cost_usd`, но `pipeline` не передаёт раннер и не пишет расход в журнал. Подключить к учёту денег отдельно — это касается биллинга, а не рендера.
5. **Гейт `D6_broll_bed`** (`verify.py:160-176`) при формате не-`avatar` меряет громкость фоновой дорожки в паузе после хука. В новом пути фоновой дорожки нет — проверить на живой сборке, не даёт ли он ложный отказ.
6. **Приём «ведущий в пузыре»** (`coverage="mixed"`, `effect.bubble`) в новом пути не описан. Либо переносим, либо честно снимаем — решать после первой сборки.
7. **Флаги `grade`, `grain`, `zoom`, `flash`** остаются в конфиге без действия. Либо чистим конфиг, либо переносим приёмы.

## Отложено сознательно

1. **Правило «каждые три секунды»** — проверка таймлайна на дыры без событий. Решение заказчика: сначала приёмы, потом ритм.
2. **Разбор чужих залетевших роликов** — источник YouTube официально, разбор моделью по ссылке без скачивания. После того, как выжмем скилы HeyGen.
3. **Приём «было и стало» на двух снимках** — сейчас блок работает только на текстовых парах.
4. **Апгрейд движка с 0.7.70** — отдельной задачей с полным перепрогоном.
5. **Судьба `tz_validator.py`** — после переезда он проверяет формат, которого больше нет.
6. **Подключение снимков и маршрутов к планировщику** — модули готовы (задачи 14, 15), но решение «здесь нужен снимок сайта» принимает планировщик, и это отдельная работа после живой проверки.

## Чего в плане намеренно нет

- Своего скила-монтажёра и своей вёрстки карточек: знание монтажа берём у HeyGen как есть.
- Облачного рендера — два открытых бага со звуком.
- Каталога готовых блоков HeyGen — почти весь горизонтальный и данными не настраивается.
- Формата `fullscreen` и пути без мастер-звука — оба не переносятся, конвейер падает понятной ошибкой.
