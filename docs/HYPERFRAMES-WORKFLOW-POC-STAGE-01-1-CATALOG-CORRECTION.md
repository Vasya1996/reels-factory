# ТЗ: Stage 01.1 — исправление каталога HyperFrames после независимого аудита

## 0. Задача исполнителю

Исправь уже созданный Stage 01 catalog. Не начинай работу заново и не переходи
к Stage 02.

Работай в существующей ветке:

```text
codex/hyperframes-workflow-poc
```

Рабочий каталог:

```text
experiments/hyperframes-workflow-poc/stage-01-catalog/
```

Исходное ТЗ остаётся главным описанием Stage 01:

```text
docs/HYPERFRAMES-WORKFLOW-POC-STAGE-01-CATALOG.md
```

Это ТЗ уточняет исправления, которые обязательны после аудита. Если требования
двух документов конфликтуют, для перечисленных ниже дефектов применяй это ТЗ.

Нельзя отвечать `COMPLETE`, пока не выполнены все проверки из разделов 12 и 14.
Старый результат `validation PASS` не является доказательством завершения.

## 1. Цель

После исправления пользователь должен получить каталог, в котором:

1. Сохранены все 161 catalog items.
2. Для upstream items реально загружены доступные poster-изображения.
3. Runtime dependencies извлечены только из исполняемого кода.
4. Параметризация описывает реальные контракты, а не придуманные variables.
5. Score вычисляется строго по исходному ТЗ.
6. Каждый фактически существующий визуальный или монтажный приём описан отдельно.
7. Один item может быть связан с несколькими techniques.
8. Описательные поля techniques написаны по-русски.
9. Галерея пригодна для человеческого отбора.
10. Validator проверяет факты по источникам, а не только наличие полей.

Итог Stage 01.1 — исправленный каталог и галерея. Не создавай `edit_plan`, видео
или Stage 02 артефакты.

## 2. Известные дефекты, которые нельзя оставить

Исполнитель обязан исправить каждый пункт:

1. В `reports/preview-downloads.json` записано `attempted: false`; 146 карточек
   используют один placeholder.
2. Каждый item принудительно связан ровно с одним technique.
3. Preview URLs, JSON Schema URLs и XML namespace ошибочно попадают в
   `runtime.remote_dependencies`.
4. Пятнадцать approved layouts/transitions ошибочно помечены как
   `parameterization.level: declarative`.
5. Score начинается с 1 и ограничивается диапазоном 1–5, хотя ТЗ требует начать
   с 0 и не ограничивать диапазон.
6. Значительная часть полей `description_ru` и `viewer_sees_ru` содержит
   английские предложения.
7. Эвристики по подстрокам ошибочно классифицируют, например,
   `texture-mask-text` как map, `vignette` как transition и `motion-blur` как
   transition.
8. `source_ref.implementation` approved items содержит псевдоссылки вида
   `evidence:...`, а не только реальные файлы.
9. Validator разрешает пропустить загрузку poster и не проверяет точную формулу
   score, доказательства параметризации и полноту внутренних variants.

## 3. Границы задачи

### 3.1. Разрешено

- Изменять файлы только внутри
  `experiments/hyperframes-workflow-poc/stage-01-catalog/`.
- Добавить данный документ в `docs/`.
- Читать frozen upstream, local blocks, approved catalog и project decision docs.
- Скачать только upstream poster-изображения, указанные в frozen manifests.
- Добавлять небольшие PNG/JPG/JPEG/WebP/GIF poster-файлы размером до 2 MB каждый.
- Добавлять и изменять Node.js scripts без сторонних npm-зависимостей.
- Пересоздавать generated JSON, Markdown и HTML Stage 01.

### 3.2. Запрещено

- Не изменять production-код Reels Factory.
- Не изменять frozen upstream snapshot.
- Не обновлять upstream registry из сети.
- Не выполнять `hyperframes add`, `init`, render, snapshot или publish.
- Не скачивать preview MP4, MOV, WAV или другие видео/аудио.
- Не вызывать LLM API, HeyGen, ElevenLabs или платные API.
- Не создавать `edit_plan`.
- Не создавать Stage 02.
- Не удалять пользовательские или несвязанные файлы.
- Не коммитить и не push-ить изменения без отдельной команды пользователя.
- Не объявлять сетевую ошибку успешной загрузкой.
- Не подменять доказательства предположениями по одному имени item.

## 4. Источники и неизменяемые значения

Прочитай `source-manifest.json` и проверь пути до начала изменений.

Ожидается:

```text
upstream ZIP SHA-256:
CCA9B08B39A4A5FA29E55D9260F49020B1B6D455C68A674B42D4C3661D185BE3

HyperFrames packages:
cli      0.7.87
core     0.7.87
producer 0.7.87
sdk      0.7.87
```

Неизменяемые counts catalog items:

```text
upstream blocks:       113
upstream components:    25
local blocks:             8
approved layouts:        10
approved transitions:     5
total catalog items:     161
```

Upstream examples не являются catalog cards и не входят в 161.

Количество techniques заранее не фиксировать. Оно должно быть получено из
фактических реализаций после разделения внутренних variants.

## 5. Обязательные файлы после исправления

Сохрани существующую структуру и добавь:

```text
stage-01-catalog/
  gallery/
    assets/
      posters/
        <скачанные upstream posters>
  inventory/
    items.json
    catalog.schema.json
    techniques.json
    techniques.schema.json
  reports/
    preview-downloads.json
    runtime-dependencies.json
    technique-extraction-audit.json
    catalog-audit.md
    techniques-catalog.md
    validation.json
    blockers.md
  scripts/
    extract-catalog.mjs
    download-posters.mjs
    technique-curation.json
    build-gallery.mjs
    validate-catalog.mjs
```

`scripts/technique-curation.json` — проверяемый человеком source of truth для
семантической классификации приёмов. Нельзя снова строить весь справочник одной
эвристикой по имени item.

`reports/technique-extraction-audit.json` — доказательство, какие исходники были
прочитаны и почему item связан с указанными techniques.

`reports/runtime-dependencies.json` — список только настоящих runtime dependency
с `item_id`, URL, типом использования, файлом и строкой evidence.

## 6. Preflight

До правок выполни и зафиксируй в отчёте:

```powershell
git branch --show-current
git status --short
node --version
```

Затем:

1. Проверь существование всех source paths из `source-manifest.json`.
2. Повтори SHA-256 frozen ZIP.
3. Повтори package versions.
4. Сохрани текущие counts 161 items и 127 techniques как baseline, но не как
   ожидаемый финальный count techniques.
5. Не удаляй текущие generated артефакты до успешной новой сборки.

Если branch, SHA-256, versions или source paths не совпали — остановись по
разделу 13.

## 7. Исправление inventory

### 7.1. Реальные source references

В `source_ref.manifest` и `source_ref.implementation` разрешены только реальные
относительные пути к существующим файлам источника.

Запрещены значения:

```text
evidence:avatar_broll_split
evidence:function renderAvatarFullscreen
function render...
```

Добавь отдельное поле `evidence_refs`:

```json
[
  {
    "path": "assets/catalog.js",
    "symbol": "renderSplit",
    "line_start": 332,
    "line_end": 340,
    "reason_ru": "Функция строит split-layout аватара и B-roll."
  }
]
```

Правила:

- `path` обязан существовать относительно source root данного item.
- `line_start` и `line_end` — положительные числа внутри файла.
- `line_end >= line_start`.
- `symbol` может быть `null`, если evidence находится в markup.
- `reason_ru` обязан объяснять, что доказывает этот фрагмент.
- Validator должен открыть файл и проверить диапазон строк.

### 7.2. Runtime dependencies

Не собирай URL регулярным выражением из объединённого HTML/JS/CSS/JSON текста.

Для runtime-анализа используй только implementation-файлы:

```text
.html
.js
.mjs
.css
```

`registry-item.json`, docs, Markdown и preview metadata не являются runtime
source.

URL считается runtime dependency только при явном использовании в одном из
контекстов:

- `<script src="...">`;
- `<link rel="stylesheet" href="...">`;
- `<img src>`, `<video src>`, `<audio src>`, `<source src>`;
- CSS `url(...)` или `@import`;
- JavaScript `fetch(...)`, dynamic import, `new URL(...)`;
- явная настройка внешнего loader/runtime asset path.

Не считать runtime dependency:

- `preview.poster` и `preview.video` из manifest;
- `$schema`;
- `xmlns="http://www.w3.org/..."`;
- URL в обычном тексте, комментарии, документации или author/social link;
- URL, найденный только в `registry-item.json`.

Для каждой зависимости запиши:

```json
{
  "item_id": "upstream:block:data-chart",
  "url": "https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js",
  "usage": "script_src",
  "path": "registry/blocks/data-chart/data-chart.html",
  "line": 123
}
```

`items.json[].runtime.remote_dependencies` должен содержать уникальные URL из
этого evidence report.

Обязательные regression assertions:

- ни один `static.heygen.ai/.../docs/images/catalog/...png|mp4` не попадает в
  runtime dependencies только потому, что он указан как preview;
- `https://hyperframes.heygen.com/schema/registry-item.json` отсутствует;
- `http://www.w3.org/2000/svg` отсутствует;
- `http://www.w3.org/1999/xhtml` отсутствует.

### 7.3. Parameterization

Обнови enum `parameterization.level`:

```text
declarative
manifest_only
generated_python
approved_js_contract
none
unknown
```

Применяй строго:

- `declarative` — в runtime source реально найден
  `data-composition-variables`.
- `manifest_only` — manifest имеет `params`, но runtime не доказывает
  `data-composition-variables`.
- `generated_python` — только восемь local blocks, поля получены из builder
  function/call site.
- `approved_js_contract` — только approved layout/transition с доказанным
  входным JS-контрактом.
- `none` — controls не найдены.
- `unknown` — анализ невозможен, причина обязательно записана в `risks`.

Добавь `parameterization.contract_fields`. Поле содержит только доказанные
управляемые поля.

Для approved items:

- `declared_variables: []`, если в коде нет
  `data-composition-variables`;
- `uses_variable_values: false`, если нет `data-variable-values`;
- не придумывай `layout_id`, `coverage`, `text`, `emphasis`, `purpose`, `preset`
  или `length` только потому, что они кажутся логичными;
- найди фактическую render/animate function и обращения к `windowSpec`, `spec`
  или другим входам;
- запиши доказанные поля в `contract_fields`;
- добавь line-based `evidence_refs`.

Validator должен пересчитать уровень из evidence и сравнить с inventory.

### 7.4. Capabilities и роли

Не определяй роли по совпадению произвольной подстроки. Используй:

1. точные manifest tags;
2. токены имени, разделённые `-` и `_`;
3. description;
4. фактическую markup/animation choreography;
5. явный override в `technique-curation.json`, если автоматическое правило
   неоднозначно.

Используй границы слов. Строка `mask` не должна совпадать с `map`.

Обязательные regression assertions:

- `upstream:component:texture-mask-text` не имеет role `map`;
- `upstream:component:vignette` не имеет role `transition`;
- `upstream:component:motion-blur` не имеет role `transition`, если source не
  показывает самостоятельную transition choreography;
- роль `transition` не назначается только из-за слов `blur`, `radial`, `wipe`
  вне явного transition-контекста.

При сомнении используй `other` и запиши risk. Не угадывай.

### 7.5. Score

Полностью замени текущую формулу. Начинай с `0` и применяй все подходящие
правила:

```text
+5   source approved и item не запрещён
+4   source local
+3   роль caption/lower_third/title/quote/data_visualization/stat/
     comparison/list/process/social_overlay/transition/layout
+2   orientation portrait или adaptive
+2   parameterization declarative или generated_python
+1   есть manifest params
+1   есть official poster URL в frozen manifest
-2   landscape block без доказанного responsive/portrait режима
-2   есть настоящая runtime remote dependency
-2   shader/WebGL/Three.js обязателен для приёма
-3   роль code или map без связи с generic talking-head use case
-100 item запрещён актуальными решениями проекта
```

Не ограничивай score снизу или сверху. Допустимы отрицательные значения и
значения больше 5.

Каждое применённое правило запиши отдельной строкой в `score_breakdown`.

В validator реализуй независимую функцию `recomputeScore(item)`. Она не должна
вызывать функцию scoring из extractor. Для каждого из 161 items сравни:

```text
stored score === independently recomputed score
```

Несовпадение хотя бы одного item — validation error.

После score заново рассчитай `review_status` и `auto-shortlist.json` по исходному
ТЗ. Upstream item не может получить `runtime_allowed: true` на Stage 01.

## 8. Загрузка poster-изображений

Создай `scripts/download-posters.mjs` на стандартном Node.js без npm packages.

### 8.1. Что загружать

- Загружай только `preview.poster` upstream block/component.
- Не загружай `preview.video`.
- Approved items продолжают использовать один существующий contact sheet.
- Local items используют существующий локальный preview или placeholder.

### 8.2. Безопасность и ограничения

- Разрешай только `http:` и `https:` URL, полученные из frozen manifest.
- Имя файла: полный item ID с заменой `:` на `-`.
- Разрешённые MIME-типы: `image/png`, `image/jpeg`, `image/webp`, `image/gif`.
- Максимальный размер одного файла: 2 MB.
- Установи timeout 20 секунд на request.
- Если `Content-Length > 2 MB`, не скачивай body и запиши ошибку.
- Если заголовка размера нет, прекращай чтение после превышения 2 MB.
- Расширение файла выбирай по фактическому MIME, а не по URL.
- Сначала сохраняй во временный файл внутри `gallery/assets/posters/`, затем
  переименовывай после полной проверки.
- Не оставляй partial-файлы после ошибки.

### 8.3. Повторный запуск

Если локальный poster уже существует:

1. Проверь размер и сигнатуру/MIME.
2. Не загружай повторно валидный файл.
3. Запиши status `cached`.

Повторный запуск должен быть безопасным и не создавать дубликаты.

### 8.4. Отчёт

`reports/preview-downloads.json`:

```json
{
  "attempted": true,
  "entries": [
    {
      "id": "upstream:block:data-chart",
      "url": "https://...png",
      "status": "downloaded",
      "local_path": "gallery/assets/posters/upstream-block-data-chart.png",
      "content_type": "image/png",
      "bytes": 123456,
      "http_status": 200,
      "error": null
    }
  ],
  "counts": {
    "downloaded": 0,
    "cached": 0,
    "failed": 0,
    "not_applicable": 0
  }
}
```

Допустимые statuses:

```text
downloaded
cached
failed
not_applicable
```

В `entries` должны присутствовать все 161 item. Для каждого upstream item с
poster URL status обязан быть `downloaded`, `cached` или `failed`. Статус
`not_applicable` допустим только для item без remote poster.

Сетевая ошибка отдельного poster не является validation error, если попытка
действительно была и ошибка записана. Но Stage 01.1 нельзя назвать готовым для
человеческого просмотра, если большинство upstream posters осталось
недоступно. В таком случае финальный статус `BLOCKED_FOR_REVIEW` и точное число
ошибок.

После загрузки `items.json[].preview.poster_local` должен указывать на реальный
poster либо на `assets/placeholder.svg` при зафиксированной ошибке.

## 9. Полный справочник techniques

### 9.1. Главный принцип

`item` и `technique` — разные сущности.

- Item — конкретный HyperFrames block/component или локальная реализация.
- Technique — отдельный зрительский визуальный или монтажный приём.
- Один item может содержать несколько techniques.
- Несколько items могут реализовывать один technique.
- Внутренние demos/styles нельзя терять.

Запрещено снова использовать конструкцию вида:

```js
const ids = [oneTechniqueForItem(item)];
```

### 9.2. Обязательная ручная curation map

Создай `scripts/technique-curation.json`:

```json
{
  "catalog_version": 1,
  "techniques": [
    {
      "id": "transition_directional_blur",
      "name_ru": "Направленное размытие при смене кадра",
      "category": "transition",
      "description_ru": "Новый кадр входит через размытие, вытянутое по направлению движения.",
      "viewer_sees_ru": "Кадр смазывается по горизонтали или вертикали и уступает место следующему.",
      "use_when_ru": ["Нужно связать смену кадра с направленным движением."],
      "avoid_when_ru": ["Сцена должна смениться незаметно."],
      "variants_ru": [],
      "controllable_fields_ru": [],
      "placement_ru": ["fullscreen"],
      "portrait_support": "adapt",
      "adaptation_notes_ru": ["Перестроить исходный landscape canvas под 1080x1920."],
      "dependencies_ru": ["GSAP"],
      "risks_ru": ["Контент исходного showcase запечён." ]
    }
  ],
  "items": [
    {
      "item_id": "upstream:block:transitions-blur",
      "reviewed": true,
      "technique_ids": [
        "transition_blur_through",
        "transition_directional_blur",
        "transition_calm_blur_through"
      ],
      "evidence_refs": [
        {
          "path": "registry/blocks/transitions-blur/transitions-blur.html",
          "line_start": 179,
          "line_end": 190,
          "reason_ru": "Исходник явно перечисляет три разных варианта blur transition."
        }
      ]
    }
  ]
}
```

Для всех 161 items обязателен ровно один объект в `items`, но массив
`technique_ids` содержит один или несколько ID.

`reviewed: true` разрешено ставить только после чтения manifest и всех
implementation text files данного item.

### 9.3. Как извлекать внутренние variants

Для каждого item по очереди:

1. Прочитай manifest полностью.
2. Прочитай каждый HTML/JS/MJS/CSS implementation file.
3. Найди пользовательские названия variants в headings, labels, `.info-name`,
   `.info-desc`, массивах конфигурации и UI captions.
4. Найди комментарии `DEMO`, `TRANSITION`, `STYLE`, `VARIANT`, но подтверждай
   их реальной отдельной choreography/timeline.
5. Сравни GSAP timelines, CSS classes, shader modes и разные reveal-механики.
6. Создай отдельный technique, если зритель видит самостоятельный приём, который
   можно выбрать независимо.
7. Не создавай отдельный technique для технической фазы одного эффекта:
   `enter`, `hold`, `exit`, reset и cleanup — не отдельные приёмы.
8. Объединяй variants разных items только если их viewer-visible choreography
   действительно одинакова.
9. Сохраняй прежний technique ID, если смысл не изменился. Создавай новый ID
   только для реально отдельного приёма.
10. Запиши точные source lines в evidence.

### 9.4. Обязательные regression cases

Минимально должны быть представлены следующие независимые варианты:

```text
upstream:block:transitions-blur
- transition_blur_through
- transition_directional_blur
- transition_calm_blur_through

upstream:block:transitions-cover
- transition_staggered_blocks
- transition_horizontal_blinds
- transition_vertical_blinds

upstream:block:transitions-push
- transition_push_slide
- transition_vertical_push
- transition_elastic_push
- transition_squeeze

upstream:block:transitions-dissolve
- transition_crossfade
- transition_blur_crossfade
- transition_focus_pull
- transition_dip_to_black

upstream:block:transitions-light
- transition_light_leak
- transition_overexposure_burn
- transition_film_burn
```

Это минимальные известные случаи, а не полный список multi-technique items.
Проверь аналогичным способом все остальные showcase blocks.

Validator должен проверить минимальное количество technique IDs в этих
mappings: `3, 3, 4, 4, 3` соответственно.

### 9.5. Генерация `techniques.json`

`inventory/techniques.json` генерируй из curation map и `items.json`.

Для каждого technique:

- `implementation_ids` вычисляй обратным индексом mapping;
- `evidence` собирай из item IDs и реальных evidence refs;
- `availability` вычисляй по implementation statuses;
- не добавляй implementation, которой нет в inventory;
- не добавляй controllable field без parameterization evidence.

Допустимые `availability`:

```text
ready
adapt
reference_only
forbidden
```

Правила сверху вниз:

1. Есть хотя бы одна approved/local ready implementation → `ready`.
2. Нет ready, но есть `adapt` implementation → `adapt`.
3. Все незапрещённые implementations `reference_only` → `reference_only`.
4. Все implementations запрещены → `forbidden`.

Запрещённая implementation не делает весь technique forbidden, если существует
другая разрешённая implementation. Но её запрет должен быть явно показан.

### 9.6. Русский язык

Следующие поля должны быть написаны русскими предложениями:

```text
name_ru
description_ru
viewer_sees_ru
use_when_ru
avoid_when_ru
variants_ru
controllable_fields_ru
placement_ru
adaptation_notes_ru
dependencies_ru
risks_ru
evidence_refs.reason_ru
```

Допустимо сохранять внутри русского текста технические имена `GSAP`, `WebGL`,
`Light Leak`, `Apple`, CSS properties и ID. Недопустимо оставлять целое
английское предложение с припиской «Для Reels Factory...». Например:

```text
Плохо:
Auto-inverting text using mix-blend-mode: difference ... Для Reels Factory...

Хорошо:
Текст автоматически меняется между белым и чёрным в зависимости от яркости
фона благодаря CSS-режиму mix-blend-mode: difference.
```

Validator должен:

- обнаруживать описательные строки без кириллицы;
- обнаруживать длинные английские предложения;
- разрешать короткие технические tokens из allowlist;
- выводить technique ID и JSON path каждой ошибки.

### 9.7. Отчёт обо всех приёмах

Полностью пересоздай `reports/techniques-catalog.md`.

Для каждого technique опиши:

- русское название и ID;
- категорию;
- availability;
- что увидит зритель;
- когда применять;
- когда не применять;
- implementations;
- внутренние variants;
- управляемые поля;
- placement;
- готовность к 9:16;
- необходимую адаптацию;
- dependencies и risks;
- source evidence.

В конце обязательны:

1. Матрица `item → techniques` для всех 161 items.
2. Матрица `technique → implementations`.
3. Доступно сразу.
4. Станет доступно после адаптации.
5. Только референсы.
6. Запрещённые исторические решения.
7. Пробелы каталога.
8. Counts по категориям.
9. Counts `ready/adapt/reference_only/forbidden`.
10. Отдельный список multi-technique items и число приёмов в каждом.

## 10. Галерея

Пересобери `gallery/index.html` и data после исправления inventory.

Обязательно:

- 161 карточка;
- локальный poster используется первым;
- placeholder только при documented download failure или отсутствии preview;
- remote video не загружается заранее, только lazy по действию пользователя;
- поиск;
- фильтры source/kind/role/orientation/review status/technique;
- сортировка по score без предположения, что score находится в диапазоне 1–5;
- показ всех techniques item, а не одного;
- русское название и краткое описание technique доступны в карточке;
- forbidden banner;
- human decision и notes сохраняются в localStorage;
- export выдаёт корректный `human-review.json` для всех 161 items;
- reset требует подтверждения;
- галерея работает прямым открытием `file://`, без fetch локального JSON и без
  web server.

Если данные встраиваются в HTML для `file://`, не создавай второй независимый
источник истины: HTML должен генерироваться из `gallery/data/catalog.json`.

## 11. Усиление validator

`scripts/validate-catalog.mjs` должен самостоятельно проверить всё ниже.

### 11.1. Schema и структура

- Фактически загрузи `catalog.schema.json` и `techniques.schema.json`.
- Проверь используемые schema keywords, а не только ручной список нескольких
  required fields.
- Можно реализовать локальный self-contained validator для используемого subset
  JSON Schema; нельзя добавлять npm dependency только ради этой задачи.
- Для ошибки выводи файл и JSON pointer.

### 11.2. Counts и IDs

- ровно 161 item;
- source/kind counts `113/25/8/10/5`;
- уникальные и отсортированные item IDs;
- уникальные и отсортированные technique IDs;
- все mapping keys уникальны;
- ровно 161 mapping objects;
- каждый mapping имеет минимум один technique ID;
- каждый technique имеет минимум одну implementation;
- все ID в обеих сторонах существуют.

### 11.3. Source evidence

- каждый manifest path существует;
- каждый implementation path существует;
- никаких `evidence:` pseudo paths;
- каждый evidence path существует;
- line ranges валидны;
- reason написан по-русски.

### 11.4. Runtime

- `runtime-dependencies.json` согласован с items;
- запрещённые metadata/preview/namespace URL отсутствуют;
- каждая dependency имеет runtime usage и line evidence;
- upstream `runtime_allowed` всегда false;
- forbidden item имеет `runtime_allowed: false`.

### 11.5. Parameterization и score

- уровень параметризации независимо выводится из evidence;
- approved items не имеют level `declarative` без реальных HyperFrames
  variables;
- local items имеют `generated_python` и доказанные builder fields;
- score всех 161 items независимо пересчитан и совпадает;
- score не clamp-ится;
- shortlist пересчитан из новых score/status;
- forbidden отсутствует в shortlist.

### 11.6. Posters

- `attempted === true`;
- в отчёте ровно 161 entry;
- у каждого remote poster есть реальная попытка или валидный cached file;
- downloaded/cached path существует;
- файл является разрешённым image MIME и не превышает 2 MB;
- extension соответствует MIME;
- в Stage 01 нет скачанных MP4/MOV/WAV;
- каждый placeholder объяснён `failed` или `not_applicable` entry.

Нельзя превращать `attempted: false` в warning. Это validation error.

### 11.7. Techniques и язык

- все 161 curation entries имеют `reviewed: true`;
- нет автоматического one-technique ограничения;
- regression mappings `transitions-*` имеют `3/3/4/4/3` или больше;
- category входит в enum исходного ТЗ;
- `other` используется максимум для 10% items;
- русские описательные поля проходят language check;
- `controllable_fields_ru` подтверждены source contracts;
- forbidden/reference-only implementation не описана как runtime-ready;
- `avatar_cutout_overlay` явно запрещён.

### 11.8. Gallery и файлы

- gallery data содержит те же 161 IDs;
- каждый local relative path существует;
- HTML содержит необходимые controls;
- JS проходит `node --check`;
- JSON заканчиваются переводом строки;
- отсутствуют файлы больше 2 MB;
- отсутствуют скачанные видео/аудио;
- generated outputs детерминированы.

При любой обязательной ошибке:

- process exit code `1`;
- `reports/validation.json.ok: false`;
- ошибка перечислена с item/technique ID;
- нельзя печатать `PASS`.

## 12. Порядок выполнения и команды

Выполняй строго по порядку.

### Шаг 1. Исправить scripts и schemas

Не меняй generated JSON вручную как финальное решение. Исправь генераторы,
curation map и validator.

### Шаг 2. Заполнить curation map

Прочитай все 161 items и заполни `scripts/technique-curation.json`. Не переходи
дальше, пока для каждого item нет reviewed mapping и evidence.

### Шаг 3. Extraction

```powershell
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/extract-catalog.mjs
```

### Шаг 4. Posters

```powershell
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/download-posters.mjs
```

Если среда запрещает сеть, запроси разрешение штатным способом. Не записывай
`attempted: true`, пока requests действительно не выполнялись.

### Шаг 5. Повторная extraction после poster cache

```powershell
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/extract-catalog.mjs
```

Она должна обнаружить валидные cached posters и сохранить local paths.

### Шаг 6. Gallery

```powershell
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/build-gallery.mjs
```

### Шаг 7. Validation

```powershell
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/validate-catalog.mjs
```

### Шаг 8. JS syntax

```powershell
node --check experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/extract-catalog.mjs
node --check experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/download-posters.mjs
node --check experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/build-gallery.mjs
node --check experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/validate-catalog.mjs
node --check experiments/hyperframes-workflow-poc/stage-01-catalog/gallery/assets/gallery.js
```

### Шаг 9. Idempotence

1. Вычисли SHA-256 для:
   - `inventory/items.json`;
   - `inventory/techniques.json`;
   - `gallery/data/catalog.json`;
   - `shortlist/auto-shortlist.json`;
   - `reports/runtime-dependencies.json`;
   - `reports/technique-extraction-audit.json`.
2. Повтори Steps 3, 5, 6, 7 без изменения sources.
3. Повтори SHA-256.
4. Все перечисленные hashes должны совпасть.

Timestamp разрешён только в `source-manifest.json` и download log entry при
необходимости. Timestamp не должен влиять на перечисленные deterministic files.

### Шаг 10. Проверка галереи

Открой:

```text
experiments/hyperframes-workflow-poc/stage-01-catalog/gallery/index.html
```

Проверь вручную:

1. Показывается 161 карточка.
2. Большинство upstream карточек имеют разные реальные posters.
3. Поиск меняет выдачу.
4. Каждый фильтр меняет выдачу.
5. Multi-technique item показывает все techniques.
6. Сортировка корректна при отрицательных score и score больше 5.
7. Decision и notes сохраняются после reload.
8. Export содержит 161 decision.
9. Reset очищает данные только после подтверждения.
10. Forbidden item визуально выделен.

Если среда не позволяет открыть `file://`, не утверждай, что визуальная проверка
пройдена. Запиши это отдельным ограничением в финальном отчёте.

## 13. Stop conditions

Остановись, создай/обнови `reports/blockers.md` и ответь `BLOCKED`, если:

- branch не `codex/hyperframes-workflow-poc`;
- SHA-256 upstream ZIP изменился;
- package versions изменились;
- source path отсутствует;
- counts items не равны `113/25/8/10/5/161`;
- для исправления требуется production-code change;
- требуется платный API;
- требуется скачать видео/аудио или файл больше 2 MB;
- невозможно доказательно классифицировать один или несколько items;
- validator продолжает падать после документированных попыток исправления.

Глобальная сетевая недоступность posters не разрешает писать `COMPLETE`. Используй
`BLOCKED_FOR_REVIEW`, приложи реальные ошибки requests и не подделывай отчёт.

## 14. Definition of Done

Stage 01.1 считается завершённым только если одновременно:

1. Inventory содержит ровно 161 item ожидаемого состава.
2. Все generated files получаются scripts, а не одноразовой ручной правкой.
3. Poster download действительно выполнялся.
4. Для всех доступных posters есть валидные локальные изображения; отдельные
   документированные сетевые ошибки допустимы.
5. Preview/video/schema/XML URLs не загрязняют runtime dependencies.
6. Каждая runtime dependency имеет usage и source line evidence.
7. Approved items не выданы за declarative HyperFrames variables.
8. У каждого parameterization field есть source evidence.
9. Score строго соответствует исходной формуле и не clamp-ится.
10. Shortlist пересчитан из исправленных score/status.
11. Все 161 items имеют reviewed curation mapping.
12. Multi-variant showcase blocks разделены на самостоятельные techniques.
13. Известные transition regression cases проходят.
14. Все описательные поля techniques написаны по-русски.
15. `techniques-catalog.md` описывает все полученные приёмы и содержит обе
    матрицы, availability sections, gaps и multi-technique list.
16. Галерея содержит 161 карточку, реальные posters и все technique chips.
17. Human review export содержит все 161 IDs.
18. `avatar_cutout_overlay` остаётся forbidden/runtime false.
19. Upstream items остаются runtime false до human approval.
20. Все syntax checks проходят.
21. Idempotence hashes совпадают.
22. `validation.json.ok === true`, errors пусты.
23. В Stage 01 нет MP4/MOV/WAV и файлов больше 2 MB.
24. Production-код не изменён.
25. Stage 02, edit plan, render и provider calls не выполнялись.
26. `git status --short` содержит только ожидаемые файлы Stage 01/01.1.

## 15. Финальный отчёт модели-исполнителя

Ответ должен иметь точный формат:

```text
Stage 01.1 catalog correction: COMPLETE | BLOCKED | BLOCKED_FOR_REVIEW

Исправлено:
- posters: downloaded N, cached N, failed N, not applicable N
- runtime dependencies: N items, N unique URLs
- parameterization: declarative N, manifest_only N, generated_python N,
  approved_js_contract N, none N, unknown N
- scoring: independently verified for 161/161 items

Catalog counts:
- upstream blocks: N
- upstream components: N
- local blocks: N
- approved layouts: N
- approved transitions: N
- total items: N

Techniques:
- total: N
- multi-technique items: N
- categories: <category=count>
- ready/adapt/reference_only/forbidden: N/N/N/N
- справочник: <path>

Validation:
- extract: PASS | FAIL
- download-posters: PASS | PARTIAL | FAIL
- build-gallery: PASS | FAIL
- validate: PASS | FAIL
- syntax: PASS | FAIL
- idempotence: PASS | FAIL
- visual gallery check: PASS | NOT_RUN | FAIL

Изменённые файлы:
- <только главные пути>

Оставшиеся ограничения:
- нет | <точный список>

Не выполнялось:
- edit_plan
- render
- Stage 02
- LLM/provider calls
- production changes
```

Если что-то не проверено, укажи `NOT_RUN`. Нельзя заменять `NOT_RUN` словом
`PASS`.

После отчёта остановись. Не начинай Stage 02 без отдельной команды пользователя.
