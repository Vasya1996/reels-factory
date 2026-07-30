# Кириллица и пилотный ролик на пути HyperFrames — план реализации

> **Для исполнителя-агента:** ОБЯЗАТЕЛЬНЫЙ САБ-СКИЛЛ: используй superpowers:subagent-driven-development (рекомендуется) или superpowers:executing-plans, чтобы вести план задача за задачей. Шаги помечены чекбоксами (`- [ ]`).

**Цель:** доказать, что русский и казахский текст переживают конвейер HyperFrames, и один раз собрать вертикальный ролик целиком их средствами на архивном материале.

**Архитектура:** кириллица решается собственным `@font-face` с уникальным именем семейства — оба их инжектора шрифтов пропускают семейство, у которого объявлен свой `@font-face`. В нашем конвейере этот приём уже работает для русского; план чинит казахский, выносит шрифты в общий модуль и проверяет, переживает ли приём их скиллы. Затем — пилот: доустановка жанровых скиллов и сборка ролика их процессом на архивных клипах.

**Стек:** Python 3.11 (движок), Node ≥ 20 (`npx hyperframes`), pytest, ffmpeg.

## Глобальные ограничения

- CLI фреймворка закреплён на `0.7.70` (`hyperframes_blocks.py:25`, `hf_render.py:59`). Версию **не менять** до конца пилота.
- Команда `hyperframes skills update` обновляет **все** установленные скиллы до последней версии — поставить новый скилл, не обновив существующие пять, нельзя. Это принятое следствие: скиллы поедут на latest, CLI остаётся `0.7.70`.
- HeyGen не вызывать: каждый рендер стоит денег. Только архивные `work/*/avatar_*.mp4`.
- Рабочая область сборок — `C:\Users\123\Videos\Reels`. Всё в `work/` — черновое.
- Скачивание файлов шрифтов требует явного подтверждения человека — шаг помечен отдельно.
- Тесты движка: `python -m pytest` из `plugins/reels-factory/engine`.
- Ветка `feat/vasya-hyperframes`, коммиты после каждой задачи, push и PR — только после «ок» от Васи.

## Карта файлов

| Файл | Ответственность |
|---|---|
| `engine/src/reels_factory/hf_fonts.py` | **создать** — единственный источник правды по шрифтам: CSS `@font-face` с data-URI, диапазоны символов, списки пригодных стилей субтитров и запрещённых тем |
| `engine/src/reels_factory/hyperframes_blocks.py:27-49` | **изменить** — убрать дубль, брать CSS из `hf_fonts` |
| `engine/hyperframes/_fonts/` | **пополнить** — сабсеты `cyrillic-ext` для Manrope и Unbounded |
| `engine/tests/test_hf_fonts.py` | **создать** — тесты модуля шрифтов |
| `C:\Users\123\Videos\Reels\cyr-test\` | одноразовый проект-доказательство, в гит не идёт |
| `C:\Users\123\Videos\Reels\pilot-hf\` | пилотный ролик, в гит не идёт |
| `docs/superpowers/notes/2026-07-31-pilot-report.md` | **создать** — отчёт по пилоту |

---

### Задача 1: починить казахский в наших шрифтах

Русский уже работает — доказано кадром живой сборки от 29.07. Казахский сломан: диапазон `U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116` (`hyperframes_blocks.py:33`) не покрывает **ә** (U+04D9), **ғ** (U+0493), **қ** (U+049B), **ң** (U+04A3), **ө** (U+04E9), **ү** (U+04AF), **һ** (U+04BB), и самих файлов `cyrillic-ext` в `_fonts/` нет.

**Файлы:**
- Создать: `plugins/reels-factory/engine/src/reels_factory/hf_fonts.py`
- Создать: `plugins/reels-factory/engine/tests/test_hf_fonts.py`
- Изменить: `plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py:27-49`
- Пополнить: `plugins/reels-factory/engine/hyperframes/_fonts/`

**Интерфейсы:**
- Отдаёт наружу: `fonts_css() -> str` (CSS всех `@font-face`), `FONT_RANGES: dict[str, str]`, `KAZAKH_PROBE: str`, `ALLOWED_CAPTION_STYLES: tuple[str, ...]`, `BLOCKED_CAPTION_THEMES: frozenset[str]`.
- Потребители: `hyperframes_blocks.py`, задачи 2 и 6 этого плана.

- [ ] **Шаг 1: спросить у человека разрешение на скачивание шрифтов**

Нужны четыре файла сабсета `cyrillic-ext` с Google Fonts: Manrope 500/600/700 и Unbounded 600/700. Показать человеку список и дождаться явного «да». Без подтверждения — не качать.

- [ ] **Шаг 2: скачать сабсеты после подтверждения**

```bash
node -e "const u='https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700&family=Unbounded:wght@600;700&display=block';fetch(u,{headers:{'User-Agent':'Mozilla/5.0 Chrome/120'}}).then(r=>r.text()).then(t=>{const b=[...t.matchAll(/\/\*\s*([a-z-]+)\s*\*\/[^}]*?font-family:\s*'([^']+)'[^}]*?font-weight:\s*(\d+)[^}]*?src:\s*url\((https:[^)]+\.woff2)\)/g)];console.log(JSON.stringify(b.map(m=>({subset:m[1],fam:m[2],w:m[3],url:m[4]})).filter(x=>x.subset==='cyrillic-ext'),null,1))})"
```

Ожидаемо: пять записей с `subset: "cyrillic-ext"`. Скачать каждую в `engine/hyperframes/_fonts/` с именем `<семейство>-<вес>-cyrillicext.woff2` (без дефиса внутри последнего сегмента — иначе `rsplit("-", 2)` в разборе имени разъедется).

- [ ] **Шаг 3: написать падающий тест**

```python
# plugins/reels-factory/engine/tests/test_hf_fonts.py
import re
from reels_factory import hf_fonts

KAZAKH = "әғқңөұүһі"


def test_kazakh_letters_covered_by_some_range():
    """Каждая казахская буква попадает хотя бы в один unicode-range."""
    ranges = []
    for spec in hf_fonts.FONT_RANGES.values():
        for part in spec.split(","):
            part = part.strip().removeprefix("U+")
            if not part:
                continue
            lo, _, hi = part.partition("-")
            ranges.append((int(lo, 16), int(hi or lo, 16)))
    uncovered = [c for c in KAZAKH
                 if not any(lo <= ord(c) <= hi for lo, hi in ranges)]
    assert uncovered == [], f"вне диапазонов: {uncovered}"


def test_cyrillic_ext_files_present():
    """Для каждого семейства есть файл с казахскими глифами."""
    stems = {p.stem for p in hf_fonts.FONTS_DIR.glob("*.woff2")}
    families = {s.rsplit("-", 2)[0] for s in stems}
    for fam in families:
        assert any(s.startswith(f"{fam}-") and s.endswith("-cyrillicext")
                   for s in stems), f"нет cyrillic-ext для {fam}"


def test_fonts_css_embeds_every_file():
    css = hf_fonts.fonts_css()
    assert css.count("@font-face") == len(list(hf_fonts.FONTS_DIR.glob("*.woff2")))
    assert "data:font/woff2;base64," in css
    assert re.search(r"font-family:'(Manrope|Unbounded)'", css)
```

- [ ] **Шаг 4: убедиться, что тест падает**

Из `plugins/reels-factory/engine`:
```bash
python -m pytest tests/test_hf_fonts.py -v
```
Ожидаемо: `ModuleNotFoundError: No module named 'reels_factory.hf_fonts'`.

- [ ] **Шаг 5: написать модуль**

```python
# plugins/reels-factory/engine/src/reels_factory/hf_fonts.py
"""Единственный источник правды по шрифтам в композициях HyperFrames.

Приём: собственный @font-face с data-URI под именем семейства, которого нет
в их карте алиасов (packages/parsers/src/fontAliases.ts). Тогда не срабатывает
ни подмена имён, ни латинский бандл продюсера — оба инжектора пропускают
семейство с уже объявленным @font-face.
"""
import base64
import functools
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parents[2] / "hyperframes" / "_fonts"

FONT_RANGES = {
    "latin": ("U+0000-00FF, U+0131, U+0152-0153, U+2000-206F, U+2074, "
              "U+20AC, U+2122, U+2212, U+2215"),
    "cyrillic": "U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116",
    "cyrillicext": ("U+0460-052F, U+1C80-1C88, U+20B4, U+2DE0-2DFF, "
                    "U+A640-A69F, U+FE2E-FE2F"),
}

#: Строка для проверки отрисовки: русский плюс все казахские буквы.
KAZAKH_PROBE = "Привет, әлем: ғ қ ң ө ұ ү һ і"

#: Стили субтитров из их каталога, пригодные без замены шрифта: семейство
#: несёт кириллицу И вес отсутствует в латинском бандле продюсера.
ALLOWED_CAPTION_STYLES = (
    "caption-highlight",       # Montserrat 800
    "caption-neon-accent",     # Montserrat 800
    "caption-weight-shift",    # Montserrat 300
)

#: Темы embedded-captions на штриховых шрифтах Hershey: неизвестный символ
#: даёт пустой контур, русское слово отрисуется пустотой без ошибки.
BLOCKED_CAPTION_THEMES = frozenset({
    "aurora", "brush", "chalkboard", "graffiti", "neonsign", "spectrum",
})


@functools.lru_cache(maxsize=1)
def fonts_css() -> str:
    """@font-face с data-URI для всех woff2 в _fonts/ (имя family-weight-subset)."""
    faces = []
    for f in sorted(FONTS_DIR.glob("*.woff2")):
        fam, wght, subset = f.stem.rsplit("-", 2)
        b64 = base64.b64encode(f.read_bytes()).decode("ascii")
        faces.append(
            f"@font-face{{font-family:'{fam.capitalize()}';font-style:normal;"
            f"font-weight:{wght};font-display:block;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');"
            f"unicode-range:{FONT_RANGES.get(subset, '')};}}")
    return "\n      ".join(faces)
```

- [ ] **Шаг 6: убедиться, что тест прошёл**

```bash
python -m pytest tests/test_hf_fonts.py -v
```
Ожидаемо: три теста PASS.

- [ ] **Шаг 7: убрать дубль из блоков**

В `hyperframes_blocks.py` удалить `_FONTS_DIR`, `_FONT_RANGES` и `_fonts_css()` (строки 27-49), вместо них:

```python
from reels_factory.hf_fonts import fonts_css as _fonts_css
```

Проверить, что `base64` и `functools` больше нигде в файле не нужны, и убрать осиротевшие импорты.

- [ ] **Шаг 8: прогнать весь набор тестов движка**

```bash
python -m pytest
```
Ожидаемо: всё зелёное, включая `tests/test_hyperframes_blocks.py`.

- [ ] **Шаг 9: коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/hf_fonts.py plugins/reels-factory/engine/tests/test_hf_fonts.py plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py plugins/reels-factory/engine/hyperframes/_fonts/
git commit -m "feat(fonts): казахские глифы и общий модуль шрифтов"
```

---

### Задача 2: доказать кириллицу рендером, с контрольным негативом

Тест из задачи 1 проверяет диапазоны, а не картинку. Здесь проверяем глазами то, что реально выходит из их рендера — и убеждаемся, что проверка вообще способна поймать поломку.

**Файлы:**
- Создать: `C:\Users\123\Videos\Reels\cyr-test\` (одноразовый, в гит не идёт)

**Интерфейсы:**
- Использует: `hf_fonts.fonts_css()`, `hf_fonts.KAZAKH_PROBE` из задачи 1.
- Даёт: подтверждение, что приём работает; в гит уходит только вывод в отчёт задачи 7.

- [ ] **Шаг 1: создать проект**

```bash
cd "C:\Users\123\Videos\Reels" && npx --yes hyperframes@0.7.70 init cyr-test --resolution portrait --non-interactive
```
Ожидаемо: каталог `cyr-test` с `index.html`.

- [ ] **Шаг 2: сгенерировать композицию с тремя полосами**

Скрипт кладёт три строки: наш Manrope, их каноническое Montserrat 900 (негативный контроль) и их Montserrat 800 (вес вне бандла).

```python
# запустить из plugins/reels-factory/engine питоном рабочей области
from pathlib import Path
from reels_factory.hf_fonts import fonts_css, KAZAKH_PROBE

out = Path(r"C:\Users\123\Videos\Reels\cyr-test\index.html")
out.write_text(f"""<!doctype html>
<html lang="ru">
<head><meta charset="utf-8">
<style>
  {fonts_css()}
  body {{ margin:0; background:#111; color:#fff; }}
  .row {{ position:absolute; left:40px; width:1000px; font-size:64px; }}
  .a {{ top:200px; font-family:'Manrope'; font-weight:700; }}
  .b {{ top:500px; font-family:'Montserrat'; font-weight:900; }}
  .c {{ top:800px; font-family:'Montserrat'; font-weight:800; }}
</style></head>
<body data-duration="2" data-width="1080" data-height="1920">
  <div class="clip row a" data-start="0" data-duration="2">A {KAZAKH_PROBE}</div>
  <div class="clip row b" data-start="0" data-duration="2">B {KAZAKH_PROBE}</div>
  <div class="clip row c" data-start="0" data-duration="2">C {KAZAKH_PROBE}</div>
</body></html>""", encoding="utf-8")
```

- [ ] **Шаг 3: проверить композицию**

```bash
cd "C:\Users\123\Videos\Reels\cyr-test" && npx --yes hyperframes@0.7.70 lint . && npx --yes hyperframes@0.7.70 check . --json
```
Ожидаемо: `lint` без ошибок, `check` отдаёт JSON. Ошибки про `class="clip"` или `data-duration` — чинить разметку, а не игнорировать.

- [ ] **Шаг 4: снять кадр**

```bash
cd "C:\Users\123\Videos\Reels\cyr-test" && npx --yes hyperframes@0.7.70 snapshot . --at 1 --output snaps
```

- [ ] **Шаг 5: посмотреть PNG и записать вердикт**

Открыть снимок инструментом Read. Ожидаемо:
- строка **A** — все буквы на месте, включая ә ғ қ ң ө ұ ү һ і;
- строка **B** — казахские и/или русские буквы уехали в другой шрифт либо пропали;
- строка **C** — читается.

**Если B выглядит так же хорошо, как A — проверка не ловит поломку.** Тогда остановиться и разобраться, почему негативный контроль не сработал: возможно, в системе стоит шрифт, который Chrome подставляет молча. Без работающего негатива вся задача бессмысленна.

- [ ] **Шаг 6: записать результат в заметку**

Создать `docs/superpowers/notes/2026-07-31-pilot-report.md` с разделом «Кириллица: доказательство», приложить вердикт по трём строкам и путь к снимку.

- [ ] **Шаг 7: коммит**

```bash
git add docs/superpowers/notes/2026-07-31-pilot-report.md
git commit -m "docs(pilot): доказательство отрисовки кириллицы с контрольным негативом"
```

---

### Задача 3: доустановить жанровые скиллы

**Файлы:**
- Изменяет: `C:\Users\123\.claude\skills\` (вне репозитория)

**Интерфейсы:**
- Даёт: скиллы `product-launch-video`, `faceless-explainer`, `embedded-captions`, `music-to-video` на диске — их скрипты нужны задачам 4-6.

- [ ] **Шаг 1: зафиксировать текущее состояние**

```bash
npx --yes hyperframes@0.7.70 skills check
```
Ожидаемо (на 31.07.2026): 4 актуальны, 5 устарели, 10 доступны по требованию. Сохранить вывод в отчёт — понадобится, если после обновления что-то сломается.

- [ ] **Шаг 2: поставить нужные**

```bash
npx --yes hyperframes@0.7.70 skills update product-launch-video faceless-explainer embedded-captions music-to-video
```
Помнить: команда заодно обновит все пять устаревших до последней версии. Это принято.

- [ ] **Шаг 3: убедиться, что скрипты на месте**

```bash
ls "C:\Users\123\.claude\skills\embedded-captions\scripts\safe-zones.cjs" "C:\Users\123\.claude\skills\embedded-captions\scripts\check-occlusion.cjs" "C:\Users\123\.claude\skills\product-launch-video\scripts\assemble-index.mjs" "C:\Users\123\.claude\skills\faceless-explainer\scripts\lib\dimensions.mjs"
```
Ожидаемо: все четыре файла существуют. Если путь другой — найти фактический и записать его в отчёт, дальше пользоваться им.

- [ ] **Шаг 4: проверить, что наш конвейер не сломался**

```bash
cd plugins/reels-factory/engine && python -m pytest
```
Ожидаемо: зелено. Скиллы — это тексты и скрипты, на движок влиять не должны; если что-то упало, причина в другом, и её надо найти до продолжения.

- [ ] **Шаг 5: записать состав и версии в отчёт, коммит**

```bash
git add docs/superpowers/notes/2026-07-31-pilot-report.md
git commit -m "docs(pilot): состав установленных скиллов до и после"
```

---

### Задача 4: снять карту кадра их средствами

Это прямая замена нашему `face_detect.py`: их скрипт считает свободные полосы по настоящей маске человека, отдельно на каждое окно времени, и выдаёт вердикт «класть текст за человека или поверх».

**Файлы:**
- Создать: `C:\Users\123\Videos\Reels\pilot-hf\`
- Читает: `C:\Users\123\Videos\Reels\work\bot-583558720-1784873847\avatar_0.mp4`

**Интерфейсы:**
- Даёт: `pilot-hf/alpha.webm` (ведущая с прозрачным фоном) и JSON со свободными зонами — вход для задач 5 и 6.

- [ ] **Шаг 1: вырезать ведущую по альфе**

```bash
cd "C:\Users\123\Videos\Reels" && mkdir pilot-hf && npx --yes hyperframes@0.7.70 remove-background "work\bot-583558720-1784873847\avatar_0.mp4" -o "pilot-hf\alpha.webm"
```
Ожидаемо: `alpha.webm`, VP9 с альфа-каналом. Первый запуск скачивает модель сегментации — это долго, но однократно.

- [ ] **Шаг 2: убедиться, что альфа есть**

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt,width,height -of default=nw=1 "C:\Users\123\Videos\Reels\pilot-hf\alpha.webm"
```
Ожидаемо: `pix_fmt=yuva420p` (буква «a» обязательна — иначе прозрачности нет), 1080×1920.

- [ ] **Шаг 3: посчитать свободные зоны**

```bash
node "C:\Users\123\.claude\skills\embedded-captions\scripts\safe-zones.cjs" "C:\Users\123\Videos\Reels\pilot-hf"
```
Если скрипт требует иных аргументов — прочитать его первые 40 строк и вызвать как задумано; путь к скрипту зафиксирован в задаче 3.

- [ ] **Шаг 4: сверить с нашим расчётом**

Прогнать наш `face_detect.py` на том же клипе и сравнить: где обе стороны говорят «свободно слева/справа», где расходятся. Расхождения записать — это ответ на вопрос, заменяет ли их скрипт наш.

- [ ] **Шаг 5: записать в отчёт, коммит**

```bash
git add docs/superpowers/notes/2026-07-31-pilot-report.md
git commit -m "docs(pilot): карта свободных зон их скриптом против нашего"
```

---

### Задача 5: транскрипт для их конвейера

**Файлы:**
- Создать: `C:\Users\123\Videos\Reels\pilot-hf\transcript.json`

**Интерфейсы:**
- Даёт: пословный транскрипт с границами — вход для субтитров в задаче 6.

- [ ] **Шаг 1: достать звук из архивного клипа**

```bash
ffmpeg -y -i "C:\Users\123\Videos\Reels\work\bot-583558720-1784873847\avatar_0.mp4" -vn -ac 1 -ar 16000 "C:\Users\123\Videos\Reels\pilot-hf\voice.wav"
```

- [ ] **Шаг 2: расшифровать их командой**

```bash
cd "C:\Users\123\Videos\Reels\pilot-hf" && npx --yes hyperframes@0.7.70 transcribe voice.wav --engine whisper --model large-v3 --language ru
```
Движок указывать явно: по умолчанию стоит англоязычная модель. Для казахского — тот же вызов; whisperx не использовать, для kk у него нет модели выравнивания и откат происходит молча.

- [ ] **Шаг 3: проверить, что слова на месте**

Открыть результат и убедиться: слова русские (не транслитерация), у каждого есть начало и конец, границы похожи на правду в первых пяти секундах.

- [ ] **Шаг 4: сравнить с нашим faster-whisper**

Прогнать наш `transcribe.py` на том же `voice.wav`. Сравнить число слов и расхождение границ. Записать в отчёт: какой путь точнее и стоит ли менять.

- [ ] **Шаг 5: коммит отчёта**

```bash
git add docs/superpowers/notes/2026-07-31-pilot-report.md
git commit -m "docs(pilot): сравнение транскрипции их CLI и нашей"
```

---

### Задача 6: собрать пилотный ролик их процессом

Главная задача плана. Здесь проверяется сращивание двух жанров: реальный клип монтирует только `product-launch-video`, вертикальные правила есть только у `faceless-explainer`.

**Файлы:**
- Создать: `C:\Users\123\Videos\Reels\pilot-hf\index.html` и сопутствующие
- Итог: `C:\Users\123\Videos\Reels\pilot-hf-2026-07-31.mp4`

**Интерфейсы:**
- Использует: `alpha.webm` и зоны из задачи 4, `transcript.json` из задачи 5, `fonts_css()` и списки из задачи 1.

- [ ] **Шаг 1: прочитать их справочники перед сборкой**

Обязательно, до первой строки разметки: процедура выбора визуального решения, доктрина движения и каталог склеек в установленных скиллах. Из них взять и записать в отчёт числа, которым будет следовать сборка: доля главного элемента в кадре, число слоёв глубины, длительности входов, запрет пружинных кривых.

- [ ] **Шаг 2: поставить блоки каталога**

```bash
cd "C:\Users\123\Videos\Reels\pilot-hf" && npx --yes hyperframes@0.7.70 add lt-clean-bar lt-mask-reveal freeze-frame-dressing editorial-flash-overlay parallax-zoom tiktok-follow
```
Если команда не принимает несколько имён сразу — ставить по одному. Наложения свёрстаны в процентах, размеры не трогать. Проверить, что каждый блок появился в каталоге проекта и подключается через `data-composition-src`.

- [ ] **Шаг 3: собрать композицию по их процессу**

Вертикаль 1080×1920, клип ведущей подложкой, поверх — карточки и субтитры. Шрифты только из `hf_fonts.fonts_css()`. Стили субтитров — только из `ALLOWED_CAPTION_STYLES`. Темы из `BLOCKED_CAPTION_THEMES` не использовать ни при каких условиях.

Субтитры и переходы — их скриптами, а не своими: `captions.mjs` (группировка слов по темпу речи, разрыв на паузе 0,18 с) и `transitions.mjs inject` (реестр из пяти переходов; продлевает только уходящий кадр, не двигая звук). Скрипты лежат в каталогах установленных скиллов, пути зафиксированы в задаче 3.

- [ ] **Шаг 4: проверить композицию всеми гейтами**

```bash
cd "C:\Users\123\Videos\Reels\pilot-hf" && npx --yes hyperframes@0.7.70 check . --json --frame-check --snapshots
```
Ожидаемо: перекрытие лица, вылет за кадр, статика, контраст — без нарушений. Каждое нарушение чинить, а не подавлять флагом.

- [ ] **Шаг 5: посмотреть кадры до рендера**

```bash
cd "C:\Users\123\Videos\Reels\pilot-hf" && npx --yes hyperframes@0.7.70 snapshot . --at 1 --at 5 --at 10 --at 20 --output snaps
```
Открыть снимки. Кириллица на месте, текст не закрывает лицо, карточки не выходят за кадр.

- [ ] **Шаг 6: отрендерить**

```bash
cd "C:\Users\123\Videos\Reels\pilot-hf" && npx --yes hyperframes@0.7.70 render . --output "C:\Users\123\Videos\Reels\pilot-hf-2026-07-31.mp4" --fps 30 --quality standard
```

- [ ] **Шаг 7: проверить готовый файл**

```bash
ffprobe -v error -show_entries format=duration:stream=width,height,codec_name -of default=nw=1 "C:\Users\123\Videos\Reels\pilot-hf-2026-07-31.mp4"
```
Ожидаемо: 1080×1920, h264, длительность совпадает с задуманной в пределах секунды.

- [ ] **Шаг 8: коммит наработок, которые уходят в репозиторий**

В гит идут только изменения в движке и отчёт; сам ролик и рабочий каталог — нет.

---

### Задача 7: приёмка и отчёт

**Файлы:**
- Изменить: `docs/superpowers/notes/2026-07-31-pilot-report.md`

- [ ] **Шаг 1: сравнить со старым роликом**

Открыть рядом `pilot-hf-2026-07-31.mp4` и `work\bot-583558720-1784873847\reel.mp4`. Смотреть: живость, читаемость субтитров, уместность карточек, нет ли мёртвых участков.

- [ ] **Шаг 2: посчитать стоимость**

Из логов сессии сборки взять расход на Клода за задачу 6 и записать цену одного ролика в модели «агент рисует каждый кадр». Это входной параметр решения, менять ли модель сборки.

- [ ] **Шаг 3: записать ответы на три вопроса спеки**

Срослись ли два жанровых процесса; сколько стоит ролик; какие их правила конфликтуют с нашими решениями (заранее известны два: запрет пружинных входов при нашем `back.out(1.6)` и потолок в 19 слов и 9 секунд на кадр).

- [ ] **Шаг 4: перечислить, что из нашего кода после пилота лишнее**

Кандидаты известны из разбора: `face_detect.py` (заменяется их картой зон), задача про подбор материала (заменяется их `resolve.mjs`), гейт ритма (заменяется их проверкой статики). Подтвердить или опровергнуть по факту пилота — удаление отдельным планом.

- [ ] **Шаг 5: финальный коммит и показать диф человеку**

```bash
git add docs/superpowers/notes/2026-07-31-pilot-report.md
git commit -m "docs(pilot): итоги пилотного ролика на пути HyperFrames"
```
Показать Васе изменения простыми словами и дождаться «ок» перед push и PR.
