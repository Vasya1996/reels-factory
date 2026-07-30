# Пилотный ролик HyperFrames — заметки

## Кириллица: доказательство

Задача 1 (`hf_fonts.py`) проверена тестами на уровне файлов шрифтов
(fontTools/getBestCmap). Здесь — проверка глазами того, что реально выходит
из их рендера, плюс контрольный негатив, доказывающий, что проверка вообще
способна поймать поломку.

### Проект

```
cd "C:\Users\123\Videos\Reels" && npx --yes hyperframes@0.7.70 init cyr-test --resolution portrait --example blank --non-interactive
```

Брифовая команда (`init cyr-test --resolution portrait --non-interactive`, без
`--example`) отбита самим CLI: «Non-interactive init requires --example,
--video, or --audio». Добавлен `--example blank` — ровно то, что предлагает
собственная подсказка CLI для пустого стартового проекта; версия и остальные
параметры не менялись.

### Композиция

Три строки текстом `hf_fonts.KAZAKH_PROBE` = `Привет, әлем: ғ қ ң ө ұ ү һ і`:

- **A** — `font-family:'Manrope'; font-weight:700` (наш `@font-face`, донор Noto Sans на 5 недостающих букв);
- **B** — `font-family:'Montserrat'; font-weight:900` (их канонический бандл, негативный контроль);
- **C** — `font-family:'Montserrat'; font-weight:800` (вес вне канонического 900-бандла).

CSS собран через `hf_fonts.fonts_css()`. Разметка приведена к контракту
HyperFrames (root `data-composition-id`/`data-start`/`data-width`/
`data-height`/`data-duration`, `class="clip"` на секции, регистрация
`window.__timelines`) — брифовый скелет использовал только `class="clip row a"`
и `data-duration` на `<body>`, что `lint` отклонил тремя ошибками
(`root_missing_composition_id`, `missing_timeline_registry`,
`timed_element_missing_clip_class`). Это ожидаемо по тексту брифа: «Ошибки про
`class="clip"` или `data-duration` — чинить разметку, а не игнорировать».
Сам текст трёх строк и `fonts_css()`/`KAZAKH_PROBE` не менялись.

`npx --yes hyperframes@0.7.70 lint .` → `0 errors, 0 warnings`.

`npx --yes hyperframes@0.7.70 check . --json` → `"ok": true` по всем секциям
(lint/runtime/layout/motion/contrast). В логе компилятора:

```
[INFO] [Compiler] Fetched 11 font face(s) for "Montserrat" from Google Fonts (cached to ...\fonts\montserrat)
[INFO] [Compiler] Injected deterministic @font-face rules for 1 requested font families
```

Это подтверждает механизм, который и должен сработать: `Montserrat` не имеет
собственного `@font-face` в `fonts_css()` (в `hf_fonts.DONOR_RANGES` есть
только `manrope` и `unbounded`), поэтому их инжектор шрифтов сам подставляет
канонический Google-бандл Montserrat — то самое каноническое поведение,
которое строка B должна разоблачить.

### Снимок

```
npx --yes hyperframes@0.7.70 snapshot . --at 1 --output snaps
```
→ `C:\Users\123\Videos\Reels\cyr-test\snaps\frame-00-at-1s.png`

### Вердикт по трём строкам (осмотрено глазами, Read на PNG)

- **Строка A** (Manrope 700, наш `@font-face`): весь текст — единый
  геометричный гротеск, кириллица и все девять казахских букв
  (ә ғ қ ң ө ұ ү һ і) на одном шрифте, без переключений начертания.
  Буквы читаются и не превращаются в пустые прямоугольники (tofu).
- **Строка B** (Montserrat 900, канонический бандл, негатив): базовое слово
  «Привет, әлем» отрисовано **другим, засечковым (serif) шрифтом** — заметно
  отличается от геометричного гротеска строки A и от собственного продолжения
  строки B. После двоеточия казахские буквы (ғ қ ң ө ұ ү һ) неожиданно снова
  сан-сериф — то есть даже внутри одной строки два разных шрифта. Это ровно
  та поломка, которую негатив должен ловить: на весе 900 у Montserrat
  Google-бандл, судя по всему, не несёт нормальной кириллицы вообще (только
  латиница), и браузер откатывается на системный засечковый шрифт для базовых
  русских букв, а для казахских добавочных берёт грани из другого
  зафетченного веса той же семьи, где кириллица есть.
- **Строка C** (Montserrat 800, вес вне 900-бандла): единый гротеск на всю
  строку, включая все казахские буквы — визуально ровно как у строки A по
  структуре (только другая гарнитура). Значит на этом весе у Google-Montserrat
  кириллица (в т.ч. cyrillic-ext) реально есть, и брифовое «C читается» не
  просто читается, а читается ОДНИМ шрифтом без разрывов.

**Негативный контроль сработал**: B заметно и однозначно хуже A —
переключение шрифта посреди строки, часть текста в чужом (засечковом,
непредназначенном) начертании. Проверка способна поймать поломку.

Снимок: `C:\Users\123\Videos\Reels\cyr-test\snaps\frame-00-at-1s.png`
(плюс покадровые вырезки строк для контроля:
`snaps\row_a_crop.png`, `snaps\row_b_crop.png`, `snaps\row_c_crop.png`).

Проект `cyr-test` — одноразовый, в `C:\Users\123\Videos\Reels\`, в git не
входит.
