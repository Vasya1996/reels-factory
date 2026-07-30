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

## Задача 3: доустановка жанровых скиллов

### `skills check` до установки

```
hyperframes skills
  Location  C:\Users\123\.claude\skills (claude-code)
  ✓ 9 current   ◦ 10 available on demand
  Available on demand (installed when their workflow first runs):
    ◦ embedded-captions
    ◦ faceless-explainer
    ◦ figma
    ◦ general-video
    ◦ motion-graphics
    ◦ music-to-video
    ◦ pr-to-video
    ◦ product-launch-video
    ◦ remotion-to-hyperframes
    ◦ slideshow
  ◇  Installed skills are up to date
```

**Расхождение с ожиданием брифа**: бриф предполагал на эту дату «4 актуальны,
5 устарели». По факту все 9 уже установленных скиллов на момент проверки были
актуальны (`Installed skills are up to date`), устаревших не было вовсе.
Возможные причины (не проверял) — более ранние задачи плана или отдельный
`skills update` уже подтянули их до latest. Записываю как факт, а не как то,
что бриф ожидал.

### Команда установки

```
npx --yes hyperframes@0.7.70 skills update product-launch-video faceless-explainer embedded-captions music-to-video
```

Вывод инсталлятора явно перечислил обновлёнными/поставленными только эти
четыре: `Installed/updated 4 skill(s): embedded-captions, faceless-explainer,
music-to-video, product-launch-video`. Про остальные пять (уже стоявшие)
инсталлятор ничего не сообщил отдельно — версии каждого скилла до команды я
не снимал (бриф просил сохранить именно вывод `skills check`, не версии
поштучно), поэтому не могу подтвердить и не могу опровергнуть, что они тоже
молча обновились до latest, как предполагало решение №2 брифа. Итоговый
`skills check` (ниже) показывает рост только на 4 новых, что согласуется и с
«пятёрка была и осталась актуальной», и не противоречит «пятёрка тоже
обновилась молча».

### `skills check` после установки

```
hyperframes skills
  Location  C:\Users\123\.claude\skills (claude-code)
  ✓ 13 current   ◦ 6 available on demand
  Available on demand (installed when their workflow first runs):
    ◦ figma
    ◦ general-video
    ◦ motion-graphics
    ◦ pr-to-video
    ◦ remotion-to-hyperframes
    ◦ slideshow
  ◇  Installed skills are up to date
```

Сравнение: 9→13 актуальных, 10→6 доступных по требованию. Разница — ровно
четыре запрошенных скилла (`embedded-captions`, `faceless-explainer`,
`music-to-video`, `product-launch-video`), подтверждено также листингом
`C:\Users\123\.claude\skills\` (15 директорий, включая инфраструктурные
`hyperframes*`, `media-use`, `skill-creator`, `talking-head-recut`,
`vael-reels`). Версия CLI не менялась — все команды выполнялись через
`npx --yes hyperframes@0.7.70`.

### Скрипты: путь из брифа/решения → фактический путь → существует

| Скрипт | Путь | Существует |
|---|---|---|
| `safe-zones.cjs` | `C:\Users\123\.claude\skills\embedded-captions\scripts\safe-zones.cjs` | да |
| `check-occlusion.cjs` | `C:\Users\123\.claude\skills\embedded-captions\scripts\check-occlusion.cjs` | да |
| `assemble-index.mjs` | `C:\Users\123\.claude\skills\product-launch-video\scripts\assemble-index.mjs` | да |
| `dimensions.mjs` | `C:\Users\123\.claude\skills\faceless-explainer\scripts\lib\dimensions.mjs` | да |
| `captions.mjs` | `C:\Users\123\.claude\skills\faceless-explainer\scripts\captions.mjs` **и** `C:\Users\123\.claude\skills\product-launch-video\scripts\captions.mjs` | да, в обоих скиллах (разные копии, не единый общий файл) |
| `transitions.mjs` | `C:\Users\123\.claude\skills\faceless-explainer\scripts\transitions.mjs` **и** `C:\Users\123\.claude\skills\product-launch-video\scripts\transitions.mjs` | да, в обоих скиллах |
| `preview-frames.cjs` | `C:\Users\123\.claude\skills\embedded-captions\scripts\preview-frames.cjs` | да |
| `transcribe.cjs` | `C:\Users\123\.claude\skills\embedded-captions\scripts\transcribe.cjs` | да |
| `resolve.mjs` (media-use) | `C:\Users\123\.claude\skills\media-use\scripts\resolve.mjs` | да |
| `transcript-cut.mjs` (media-use) | `C:\Users\123\.claude\skills\media-use\scripts\transcript-cut.mjs` | да |
| `analyze-beatgrid.py` (music-to-video) | `C:\Users\123\.claude\skills\music-to-video\scripts\analyze-beatgrid.py` | да |

Первые четыре пути совпали с путями из брифа буквально — подгонять
предположения не пришлось. `captions.mjs` и `transitions.mjs` оказались не
общими файлами, а отдельными копиями в двух скиллах каждый — задачи 4-6
должны явно указывать, из какого скилла берут файл.

### Точечные тесты движка (по решению, не полный набор)

```
cd plugins/reels-factory/engine && python -m pytest tests/test_hf_fonts.py tests/test_hyperframes_blocks.py -q
```
→ `27 passed`. Скиллы (тексты/скрипты на диске) движок не задели, как и
ожидалось.

### Сомнения

- Не подтверждено (и не опровергнуто) молчаливое обновление пяти ранее
  установленных скиллов версией `skills update` — инсталлятор отчитался
  только по четырём запрошенным именам, версии по одиночным скиллам до
  команды не снимались.
- `captions.mjs` и `transitions.mjs` существуют как минимум в двух местах
  каждый (`faceless-explainer` и `product-launch-video`) — не единый файл;
  дальнейшим задачам (4-6) нужно указывать конкретный скилл, а не имя файла.
