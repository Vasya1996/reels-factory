# ТЗ: этап 1 — полный каталог HyperFrames для workflow POC

## 0. Статус и границы задачи

Это ТЗ предназначено для модели-исполнителя, которая не должна самостоятельно
переосмысливать задачу. Выполняй пункты строго по порядку. Не переходи к
следующему этапу эксперимента.

На этом этапе нужно только собрать, нормализовать, проверить и показать человеку
все доступные для эксперимента визуальные строительные блоки. Нельзя создавать
`edit_plan`, вызывать LLM, монтировать тестовый ролик, запускать ElevenLabs,
HeyGen или иные платные API.

Результат этапа — локальная интерактивная HTML-галерея, машиночитаемый каталог
и полный русскоязычный справочник монтажных/визуальных приёмов, по которым
пользователь выберет разрешённый набор компонентов для этапа 2.

Рабочая ветка:

```text
codex/hyperframes-workflow-poc
```

Корень рабочего дерева:

```text
C:\Users\Asus\Documents\personal_ai\projects\content_factory\reels-factory-hyperframes-workflow-poc
```

Все создаваемые на этапе файлы, кроме этого ТЗ, должны находиться только в:

```text
experiments/hyperframes-workflow-poc/stage-01-catalog/
```

Запрещено изменять существующий production-код, `docs/EDIT-PLAN.md`, текущие
HyperFrames-шаблоны, файлы исторического каталога и upstream snapshot.

## 1. Цель этапа

Собрать в одном месте четыре группы сущностей:

1. Все upstream HyperFrames blocks — ожидается 113.
2. Все upstream HyperFrames components — ожидается 25.
3. Все текущие локальные Reels Factory HyperFrames blocks — ожидается 8.
4. Все layouts и transitions из ранее одобренного montage-каталога — ожидается
   10 layouts и 5 transitions.

Итого ожидается 161 карточка для просмотра:

```text
113 + 25 + 8 + 10 + 5 = 161
```

Upstream examples в количестве 8 нужно учесть в отчёте об источнике, но не
включать в основные 161 карточку. Examples являются демо-проектами, а не
переиспользуемыми blocks/components.

Если фактическое количество отличается, не подгоняй данные и не удаляй
«лишние» элементы. Останови генерацию итоговой галереи, запиши расхождение в
`reports/blockers.md` и заверши задачу со статусом `blocked`.

## 2. Источники данных

### 2.1. Замороженный upstream HyperFrames

Используй только этот распакованный snapshot:

```text
C:\Users\Asus\Documents\personal_ai\projects\content_factory\reference-audit\hyperframes-main-20260801-complete\hyperframes-main
```

Архив-источник:

```text
C:\Users\Asus\Documents\personal_ai\projects\content_factory\reference-audit\hyperframes-main-20260801.zip
```

Ожидаемый SHA-256 архива:

```text
CCA9B08B39A4A5FA29E55D9260F49020B1B6D455C68A674B42D4C3661D185BE3
```

Версии `packages/cli`, `packages/core`, `packages/producer` и `packages/sdk` в
snapshot должны быть `0.7.87`.

Нужные upstream-пути:

```text
registry/registry.json
registry/blocks/*/registry-item.json
registry/blocks/**/*
registry/components/*/registry-item.json
registry/components/**/*
```

Не используй сеть для получения более нового registry. Этап должен быть
воспроизводимым на замороженном snapshot.

### 2.2. Текущие локальные Reels Factory blocks

Источник:

```text
plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py
plugins/reels-factory/engine/hyperframes/
```

Ожидаемые восемь block IDs:

```text
before_after
complexity_cloud
concept_nodes
persona_card
sequence_flow
stat_number
task_list
value_layers
```

HTML этих блоков генерируется Python builder-функциями, поэтому отсутствие
постоянного `index.html` в каталоге блока не является ошибкой. Извлеки название
builder-функции и contract переменных из словаря `BLOCKS` и сигнатуры
соответствующей функции. Не выполняй и не изменяй builder на этом этапе.

### 2.3. Ранее одобренный montage-каталог

Используй как дизайн-референс и источник уже одобренной хореографии:

```text
C:\Users\Asus\Documents\personal_ai\projects\content_factory\plan-previews\two-reel-catalog-proxy-20260729
```

Обязательные файлы для чтения:

```text
catalog/catalog.json
assets/catalog.js
assets/catalog.css
REVIEW-MAP.md
snapshots/contact-sheet.jpg
data/avatar-bot.edit_plan.json
data/skills.edit_plan.json
```

Не копируй исходные MP4/WAV из `assets/media`, `assets/sfx` и `renders` в новый
каталог. В inventory можно сохранить только путь-источник и признак наличия.

### 2.4. Актуальные решения проекта

Перед классификацией прочитай:

```text
C:\Users\Asus\Documents\personal_ai\projects\content_factory\REELS-FACTORY-MEMORY.md
C:\Users\Asus\Documents\personal_ai\projects\content_factory\TZ-HYPERFRAMES-CATALOG-PIPELINE.md
AGENTS.md
docs/EDIT-PLAN.md
docs/VISUAL-DIRECTOR.md
```

Более новые решения проекта имеют приоритет над историческим каталогом.
В частности, `avatar_cutout_overlay` нужно показать в галерее как исторический
layout, но обязательно пометить:

```json
{
  "review_status": "forbidden",
  "runtime_allowed": false,
  "reason": "Запрещён актуальными решениями проекта; сохранён только для истории."
}
```

Нельзя возвращать его в shortlist.

## 3. Что не входит в задачу

Исполнитель не должен:

- создавать или менять монтажную архитектуру;
- создавать production-ready параметризованные версии блоков;
- исправлять upstream HTML;
- устанавливать blocks через `hyperframes add`;
- запускать `hyperframes render`;
- запускать paid/provider команды;
- создавать `edit_plan`;
- выбирать финальный approved-набор вместо пользователя;
- копировать весь upstream registry в git;
- скачивать preview MP4;
- добавлять npm/pip зависимости;
- коммитить изменения;
- переходить к этапу 2.

## 4. Обязательная структура результата

Создай строго такую структуру:

```text
experiments/hyperframes-workflow-poc/stage-01-catalog/
  README.md
  source-manifest.json
  inventory/
    catalog.schema.json
    items.json
    techniques.schema.json
    techniques.json
    upstream-summary.json
    local-summary.json
    approved-summary.json
  gallery/
    index.html
    assets/
      gallery.css
      gallery.js
      placeholder.svg
      posters/
    data/
      catalog.json
  shortlist/
    auto-shortlist.json
    human-review.template.json
  reports/
    catalog-audit.md
    techniques-catalog.md
    validation.json
    preview-downloads.json
    blockers.md
  scripts/
    extract-catalog.mjs
    build-gallery.mjs
    validate-catalog.mjs
```

Не создавай другие каталоги или временные файлы внутри репозитория. Временные
файлы при необходимости создавай в системном temp и удаляй только свои
конкретные файлы после успешного выполнения.

## 5. Общие технические требования

- Скрипты: Node.js ESM (`.mjs`), только стандартная библиотека Node.
- Не устанавливать зависимости.
- Все JSON: UTF-8, отступ 2 пробела, завершающий перевод строки.
- Все массивы items сортировать по `id`.
- Все пути внутри итоговых JSON хранить с `/`, даже на Windows.
- Не сохранять секреты, cookies, API keys или содержимое `.env`.
- Не сохранять абсолютные пути в `gallery/data/catalog.json`; для UI нужны
  только относительные пути и безопасные source labels.
- Абсолютные source paths допустимы только в `source-manifest.json` и
  `reports/catalog-audit.md`.
- Максимальный размер одного добавленного бинарного файла — 2 MB.
- Preview-видео не скачивать. Разрешено сохранить его HTTPS URL.
- Official poster разрешено скачать. Если скачивание не удалось, используй
  `placeholder.svg` и зафиксируй ошибку, но не удаляй item.
- Не делать вывод о качестве элемента только по названию.

## 6. Единая модель данных item

Каждая карточка в `inventory/items.json` и `gallery/data/catalog.json` должна
соответствовать следующей логической структуре. Создай эквивалентную JSON Schema
в `inventory/catalog.schema.json`.

```json
{
  "id": "upstream:block:data-chart",
  "source": "upstream",
  "kind": "block",
  "name": "data-chart",
  "title": "Data Chart",
  "description": "...",
  "tags": ["chart", "data", "statistics"],
  "source_ref": {
    "manifest": "registry/blocks/data-chart/registry-item.json",
    "implementation": ["registry/blocks/data-chart/data-chart.html"]
  },
  "dimensions": {
    "width": 1920,
    "height": 1080,
    "orientation": "landscape"
  },
  "duration_seconds": 15,
  "preview": {
    "poster_remote": "https://.../data-chart.png",
    "poster_local": "assets/posters/upstream-block-data-chart.png",
    "video_remote": "https://.../data-chart.mp4",
    "available": true,
    "error": null
  },
  "parameterization": {
    "manifest_params": [],
    "declared_variables": [],
    "uses_variable_values": false,
    "uses_data_var_bindings": false,
    "hardcoded_content_detected": true,
    "level": "none"
  },
  "runtime": {
    "animation_engines": ["gsap"],
    "media_types": [],
    "remote_dependencies": [],
    "uses_sub_compositions": false,
    "uses_shader_or_webgl": false,
    "determinism_risk": "low"
  },
  "capabilities": {
    "roles": ["data_visualization"],
    "placement": ["fullscreen"],
    "supports_portrait_as_is": false,
    "supports_overlay": false,
    "supports_text_content": true,
    "supports_media_content": false
  },
  "assessment": {
    "score": 4,
    "score_breakdown": ["+3: data/chart role", "+1: official preview"],
    "review_status": "adapt",
    "runtime_allowed": false,
    "adaptation_needed": ["portrait layout", "content variables"],
    "risks": [],
    "reason": "Полезен для числовых тезисов, но исходник landscape и контент запечён."
  },
  "human_review": {
    "decision": "undecided",
    "notes": ""
  }
}
```

### 6.1. Допустимые значения enum

`source`:

```text
upstream | local | approved
```

`kind`:

```text
block | component | layout | transition
```

`orientation`:

```text
portrait | landscape | square | adaptive | unknown
```

`parameterization.level`:

```text
declarative | manifest_only | generated_python | none | unknown
```

`assessment.review_status`:

```text
ready | adapt | reference_only | forbidden
```

`human_review.decision`:

```text
undecided | approve | adapt | reject | reference
```

## 7. Правила идентификаторов

Используй namespace, чтобы одинаковые названия из разных источников не
конфликтовали:

```text
upstream:block:<name>
upstream:component:<name>
local:block:<name>
approved:layout:<name>
approved:transition:<name>
```

ID должен быть lowercase и содержать только `a-z`, `0-9`, `_`, `-`, `:`.
Дубликаты ID являются hard error.

## 8. Пошаговый алгоритм исполнения

### Шаг 8.1. Preflight

1. Убедись, что текущая ветка — `codex/hyperframes-workflow-poc`.
2. Убедись, что все четыре источника из раздела 2 доступны для чтения.
3. Проверь SHA-256 upstream ZIP.
4. Проверь версии четырёх upstream packages.
5. Проверь наличие 113 block manifests и 25 component manifests.
6. Проверь восемь ключей локального словаря `BLOCKS`.
7. Проверь 10 layouts и 5 transitions в approved catalog.
8. Если любой обязательный пункт не совпал, создай только
   `reports/blockers.md`, ничего не выдумывай и остановись.

### Шаг 8.2. Создание `source-manifest.json`

Запиши:

- дату выполнения в ISO 8601;
- название ветки;
- пути источников;
- SHA-256 архива;
- версии packages;
- ожидаемые и фактические counts;
- факт отсутствия сетевого обновления registry;
- список прочитанных project-decision документов.

### Шаг 8.3. Извлечение upstream items

Для каждого `registry-item.json`:

1. Прочитай manifest полностью.
2. Проверь, что `name` совпадает с именем каталога.
3. Определи `kind` по `type`.
4. Сохрани title, description, tags, dimensions, duration, preview и params.
5. Разреши каждый `files[].path` относительно каталога item.
6. Проверь существование каждого файла.
7. Просканируй все текстовые `.html`, `.js`, `.mjs`, `.css`, `.json` файлы item.
8. Не копируй implementation-файлы в результат. Сохрани относительные ссылки
   в `source_ref`.

### Шаг 8.4. Статический анализ upstream implementation

Для каждого item зафиксируй evidence, используя только явные признаки:

- `data-composition-variables` → `declared_variables`;
- `data-variable-values` → `uses_variable_values`;
- `data-var-*` → `uses_data_var_bindings`;
- manifest `params` → `manifest_params`;
- `gsap` → animation engine `gsap`;
- `lottie` → `lottie`;
- `THREE`, `three.js`, WebGL → `three_or_webgl`;
- `HyperShader`, shader imports → `shader`;
- CSS `@keyframes` → `css_keyframes`;
- `Element.animate` → `waapi`;
- `<video>`, `<audio>`, `<img>`, inline `<svg>` → соответствующие media types;
- `data-composition-src` → `uses_sub_compositions`;
- `http://`/`https://` в runtime source → `remote_dependencies`;
- видимые текстовые литералы в markup, не связанные с variables →
  `hardcoded_content_detected: true`.

Не называй manifest `params` полноценными HyperFrames variables, если в коде
нет `data-composition-variables` или другого явного механизма применения.

Правило `parameterization.level`:

- `declarative`: есть `data-composition-variables`;
- `manifest_only`: есть manifest params, но нет декларативных variables;
- `generated_python`: только для восьми local blocks;
- `none`: нет ни variables, ни params;
- `unknown`: анализ невозможен, и причина записана в risks.

### Шаг 8.5. Извлечение local blocks

Для каждого ключа словаря `BLOCKS`:

1. Найди project subdir и builder function.
2. Найди сигнатуру builder function.
3. Поля функции, кроме `duration`, запиши как variable contract.
4. Значения по умолчанию запиши как defaults.
5. Для `**variables` не придумывай поля: проследи фактический вызов builder и
   явно используемые аргументы.
6. Проставь `parameterization.level: generated_python`.
7. Сохрани путь к функции и номер строки в `source_ref`.
8. Не генерируй HTML и не запускай render/snapshot.
9. Preview для local blocks — `placeholder.svg`, если в project docs нет уже
   существующего подходящего статического preview.

### Шаг 8.6. Извлечение approved layouts/transitions

1. Прочитай `catalog/catalog.json` и связанные JS/CSS.
2. Создай отдельный item для каждого layout и transition.
3. Не смешивай layouts с blocks: у них `kind: layout`.
4. Не смешивай transitions с components: у них `kind: transition`.
5. Используй `snapshots/contact-sheet.jpg` как общий reference poster. Не
   дублируй файл 15 раз: скопируй один раз и ссылайся на него.
6. Сохрани связанные selectors/functions из `catalog.js` как source evidence.
7. `avatar_cutout_overlay` обязательно классифицируй как `forbidden`.
8. Остальные approved patterns получают `review_status: ready`, но это ещё не
   означает автоматическое разрешение в runtime — финальное решение принимает
   пользователь.

### Шаг 8.7. Orientation

Для block с dimensions:

- `height > width * 1.1` → `portrait`;
- `width > height * 1.1` → `landscape`;
- иначе → `square`.

Для component → `adaptive`, если код явно не задаёт фиксированный canvas;
иначе вычисли по фиксированным width/height.

Для approved layout используй canvas исторического каталога и фактическую
логику CSS. Если однозначно определить нельзя → `unknown` и risk.

### Шаг 8.8. Capabilities и роли

Роли определяй по tags, description и фактической разметке. Разрешены:

```text
caption
lower_third
title
quote
data_visualization
stat
comparison
list
process
code
map
social_overlay
texture
vfx
transition
media_treatment
layout
brand
other
```

Placement:

```text
fullscreen
overlay
lower_third
side_panel
picture_in_picture
background
inline_effect
unknown
```

Если роль не доказана manifest/code evidence, используй `other`, а не
угадывай.

### Шаг 8.9. Детерминированный score

Score используется только для сортировки, не как финальное решение.
Записывай каждое начисление в `score_breakdown`.

Начинай с 0:

- `+5` — source `approved` и item не запрещён;
- `+4` — source `local`;
- `+3` — роль caption/lower_third/title/quote/data_visualization/stat/
  comparison/list/process/social_overlay/transition/layout;
- `+2` — orientation portrait или adaptive;
- `+2` — parameterization declarative или generated_python;
- `+1` — manifest params;
- `+1` — доступен official poster;
- `-2` — landscape block без явного responsive/portrait режима;
- `-2` — есть runtime remote dependency;
- `-2` — shader/WebGL/Three.js как обязательная часть;
- `-3` — роль code или map без связи с текущим generic talking-head use case;
- `-100` — item запрещён актуальными решениями проекта.

Не ограничивай score диапазоном.

### Шаг 8.10. `review_status`

Применяй правила сверху вниз:

1. Явно запрещено project decisions → `forbidden`, `runtime_allowed: false`.
2. Approved item без запрета → `ready`, `runtime_allowed: true`.
3. Local block → `ready`, `runtime_allowed: true`.
4. Upstream item с подходящей ролью, portrait/adaptive canvas и рабочей
   параметризацией → `ready`, но `runtime_allowed: false` до human approval.
5. Подходящая роль, но требуется portrait/content/runtime адаптация → `adapt`.
6. Узкоспециализированный code/map/showcase или item без доказанного применения
   к Reels → `reference_only`.
7. При сомнении → `adapt`, перечислив сомнения в `risks`.

Нельзя ставить upstream item `runtime_allowed: true` на этапе 1.

### Шаг 8.11. Preview posters

1. Для upstream используй `preview.poster` из manifest.
2. Скачивай только poster, не video.
3. Имя локального файла формируй из полного item ID с заменой `:` на `-`.
4. Разрешённые форматы: PNG, JPG/JPEG, WebP, GIF; сохраняй реальное расширение.
5. Проверь HTTP success, Content-Type image и размер не более 2 MB.
6. При ошибке используй общий `placeholder.svg`.
7. В `reports/preview-downloads.json` запиши для каждого item:
   `id`, URL, status, local path, bytes, error.
8. Remote preview video URL сохрани для lazy playback в галерее, но не
   скачивай.
9. Для approved patterns скопируй только `snapshots/contact-sheet.jpg`.
10. Для local blocks используй placeholder, если готового изображения нет.

Сетевая ошибка preview не блокирует каталог.

### Шаг 8.12. Auto-shortlist

`shortlist/auto-shortlist.json` должен содержать:

- все `ready` items;
- все `adapt` items со score `>= 3`;
- ни одного `forbidden`;
- для каждого item: ID, title, kind, score, reason, adaptation_needed, risks.

Это только предложение для просмотра. Не записывай `human_review.decision`
кроме `undecided`.

`shortlist/human-review.template.json` должен содержать все 161 item и поля:

```json
{
  "catalog_version": 1,
  "decisions": [
    {
      "id": "...",
      "decision": "undecided",
      "notes": ""
    }
  ]
}
```

### Шаг 8.13. Галерея

`gallery/index.html` должна открываться двойным кликом без web server и без
build step.

Обязательные элементы интерфейса:

- summary counts по source/kind/status/orientation;
- поиск по name/title/description/tags;
- фильтры source, kind, role, orientation, review_status;
- переключатель «только auto-shortlist»;
- сортировка по score, title, kind;
- карточка каждого из 161 items;
- poster или placeholder;
- кнопка/ссылка «Preview motion», если есть remote video URL;
- title, ID, source, kind, tags, dimensions, duration;
- parameterization level;
- capabilities/placement;
- review status и score breakdown;
- adaptation_needed, risks и reason;
- ссылки/текст source_ref;
- выбор human decision: approve/adapt/reject/reference/undecided;
- поле notes;
- сохранение review в `localStorage`;
- кнопка «Export review JSON», скачивающая файл, совместимый с
  `human-review.template.json`;
- кнопка «Reset review» с подтверждением;
- заметная красная плашка на forbidden items;
- русский интерфейс.

Не используй React/Vue/CDN-библиотеки. Только локальные HTML/CSS/JS.
Галерея не должна пытаться писать на файловую систему.

### Шаг 8.14. README

`README.md` должен объяснять пользователю:

1. Что вошло в каталог.
2. Как открыть `gallery/index.html`.
3. Как фильтровать карточки.
4. Как выставлять решения.
5. Как экспортировать `human-review.json`.
6. Куда положить экспортированный файл:

```text
experiments/hyperframes-workflow-poc/stage-01-catalog/shortlist/human-review.json
```

7. Что этап 2 запрещено начинать до утверждения этого файла.

### Шаг 8.15. Справочник всех доступных приёмов

После построения inventory обязательно создай два связанных артефакта:

```text
inventory/techniques.json
reports/techniques-catalog.md
```

Это не короткое summary и не список названий blocks. Нужно описать все
фактически доступные после этапа визуальные и монтажные приёмы человеческим
языком: что именно увидит зритель, зачем приём нужен и какими элементами
каталога его можно реализовать.

#### Разница между item и technique

- `item` — конкретная реализация: block, component, layout или transition.
- `technique` — визуальный/монтажный приём, который может иметь одну или
  несколько реализаций.
- Один item может поддерживать несколько techniques.
- Несколько похожих items могут быть вариантами одного technique.
- Каждый из 161 items обязан быть привязан минимум к одному technique.
- Нельзя создавать 161 бессодержательное описание вида «использовать block X».
  Группируй реализации только там, где у них действительно одинаковый приём.
- Нельзя сваливать разные хореографии переходов, титров или data visuals в один
  общий пункт, если manifest/code evidence показывает визуально разные способы.

#### Обязательные категории techniques

Используй одну из категорий:

```text
speaker_layout
composition_layout
caption_and_typography
title_and_lower_third
data_and_statistics
comparison_and_process
social_and_editorial_overlay
transition
texture_and_finishing
media_treatment
vfx_and_shader
spatial_motion
code_and_terminal
map_and_diagram
brand_and_outro
other
```

Категория `other` допустима только если ни одна точная категория не подходит.
Не более 10% items могут быть привязаны только к `other`; превышение является
validation error и означает, что классификация сделана слишком поверхностно.

#### Структура `techniques.json`

Создай `inventory/techniques.schema.json` и проверь следующий contract:

```json
{
  "catalog_version": 1,
  "techniques": [
    {
      "id": "animated_stat_countup",
      "name_ru": "Анимированный счётчик числа",
      "category": "data_and_statistics",
      "description_ru": "Число увеличивается от начального значения до ключевой цифры и фиксирует внимание на измеримом тезисе.",
      "viewer_sees_ru": "Крупную цифру, которая быстро досчитывается до целевого значения; рядом могут появиться единица измерения и подпись.",
      "use_when_ru": [
        "В речи произносится одна важная цифра или процент.",
        "Нужно превратить абстрактное преимущество в измеримый результат."
      ],
      "avoid_when_ru": [
        "В одном окне нужно сравнить много рядов данных.",
        "Цифра не подтверждается сценарием."
      ],
      "implementation_ids": ["local:block:stat_number"],
      "variants_ru": [],
      "controllable_fields_ru": ["значение", "префикс", "суффикс", "верхняя и нижняя подписи"],
      "placement_ru": ["fullscreen"],
      "portrait_support": "ready",
      "adaptation_notes_ru": [],
      "dependencies_ru": [],
      "risks_ru": ["Не использовать несколько count-up чисел одновременно."],
      "evidence": ["local:block:stat_number"]
    }
  ],
  "item_to_techniques": [
    {
      "item_id": "local:block:stat_number",
      "technique_ids": ["animated_stat_countup"]
    }
  ]
}
```

Требования:

- `technique.id`: lowercase `a-z`, `0-9`, `_`, уникальный;
- все описательные поля — на русском;
- `implementation_ids` содержат только существующие catalog item IDs;
- `evidence` указывает item IDs, manifest fields или source refs, на которых
  основано описание;
- `portrait_support`: `ready | adapt | no | unknown`;
- `controllable_fields_ru` перечисляет только реально обнаруженные controls;
- если контент запечён, явно напиши «контент запечён, нужна параметризация»;
- если приём существует только как reference/forbidden, это должно быть явно
  указано в adaptation/risk, а не скрыто;
- `avatar_cutout_overlay` может фигурировать только как запрещённая
  историческая реализация и не должен создавать впечатление доступного приёма.

#### Структура `techniques-catalog.md`

Справочник должен быть удобен человеку, который не открывал исходный HTML.
Начни с оглавления по категориям. Для каждого technique создай отдельный
подраздел:

```markdown
### Анимированный счётчик числа

- ID: `animated_stat_countup`
- Категория: данные и статистика
- Статус: доступен / нужна адаптация / только референс / запрещён
- Что видит зритель: ...
- Когда применять: ...
- Когда не применять: ...
- Реализации: `local:block:stat_number`, ...
- Управляемые параметры: ...
- Размещение: ...
- Поддержка 9:16: ...
- Что нужно адаптировать: ...
- Зависимости и риски: ...
```

После описаний добавь обязательные разделы:

1. **Матрица «item → приёмы»** — все 161 items без пропусков.
2. **Матрица «приём → реализации»**.
3. **Доступно сразу** — techniques, у которых есть хотя бы одна approved/local
   ready implementation.
4. **Станет доступно после адаптации** — techniques только с adapt items.
5. **Только референсы** — техники без runtime-ready реализации.
6. **Запрещённые исторические решения** — отдельно, с причиной запрета.
7. **Пробелы каталога** — какие полезные для talking-head/Reels приёмы
   отсутствуют полностью; не придумывай реализации, только назови gap и
   evidence, почему его нет.

Описание должно быть конкретным. Запрещены пустые формулировки вроде «делает
видео красивее», «улучшает вовлечение» или «современная анимация» без объяснения
того, что реально происходит в кадре.

Добавь techniques в карточки галереи и отдельный фильтр по technique. В UI
пользователь должен видеть русское название приёма и открыть его краткое
описание, не переходя к Markdown-файлу.

### Шаг 8.16. Validation

`scripts/validate-catalog.mjs` должен проверить:

- JSON Schema и обязательные поля;
- ровно 161 item;
- 113 upstream blocks;
- 25 upstream components;
- 8 local blocks;
- 10 approved layouts;
- 5 approved transitions;
- уникальность ID;
- сортировку items по ID;
- наличие каждого source manifest/implementation reference;
- наличие poster либо placeholder у каждого item;
- отсутствие скачанных MP4/WAV/MOV;
- отсутствие `runtime_allowed: true` у upstream items;
- `avatar_cutout_overlay` имеет forbidden/false;
- auto-shortlist не содержит forbidden;
- gallery data содержит те же ID, что inventory;
- human-review template содержит те же 161 ID;
- `techniques.json` соответствует `techniques.schema.json`;
- каждый из 161 items встречается в `item_to_techniques` ровно один раз как
  ключ mapping и имеет минимум один technique ID;
- каждый technique ID из mapping существует;
- каждый `implementation_id` существует в основном inventory;
- каждый technique имеет хотя бы одну implementation;
- не более 10% items привязаны только к категории `other`;
- forbidden/reference-only implementations не описаны как runtime-ready;
- `techniques-catalog.md` содержит обе матрицы и все обязательные разделы;
- все gallery relative paths существуют;
- все JSON заканчиваются переводом строки.

Скрипт должен завершаться code 0 только при полном успехе. Он должен записать
`reports/validation.json` со структурой:

```json
{
  "ok": true,
  "checks": [],
  "errors": [],
  "warnings": [],
  "counts": {}
}
```

Warnings по недоступным remote posters допустимы. Ошибки counts/schema/IDs/
forbidden policy недопустимы.

## 9. Требования к `catalog-audit.md`

Отчёт должен содержать:

- какие источники прочитаны;
- версии и SHA-256;
- counts по всем группам;
- сколько items имеют declarative variables;
- сколько имеют только manifest params;
- сколько не параметризованы;
- распределение orientation;
- распределение review_status;
- распределение runtime engines;
- список remote dependencies;
- список missing/broken previews;
- список top-30 auto-shortlist с причинами;
- отдельный раздел local blocks;
- отдельный раздел approved patterns;
- явное подтверждение, что `avatar_cutout_overlay` запрещён;
- что не было сделано на этом этапе;
- команды, использованные для extraction/build/validation.

Не пиши «всё отлично» без чисел и evidence.

`reports/techniques-catalog.md` является отдельным обязательным пользовательским
результатом, а не приложением, которое можно заменить несколькими абзацами в
audit. После выполнения пользователь должен иметь возможность прочитать в нём
описание каждого доступного приёма, даже если не открывает галерею и исходники.

## 10. Команды, которые должны работать после реализации

Из корня тестового рабочего дерева:

```powershell
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/extract-catalog.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/build-gallery.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/validate-catalog.mjs
```

Повторный запуск должен быть идемпотентным: одинаковые источники должны давать
семантически одинаковые JSON и не создавать дубликаты. Поле времени разрешено
только в `source-manifest.json`; оно не должно попадать в основной inventory.

## 11. Stop conditions

Остановись и создай `reports/blockers.md`, если:

- не совпал SHA-256 upstream ZIP;
- upstream package versions не `0.7.87`;
- отсутствует обязательный source directory/file;
- counts не совпали с ожидаемыми;
- локальный `BLOCKS` нельзя однозначно распарсить;
- approved catalog не содержит ожидаемые layouts/transitions;
- project decisions противоречат этому ТЗ;
- для выполнения требуется изменить production-код;
- для выполнения требуется платный API;
- для выполнения требуется скачать/добавить большой бинарный набор.

При blocker не пытайся «починить» источник, не переключайся на live registry и
не продолжай с частичным каталогом.

## 12. Definition of Done

Этап считается выполненным только если одновременно:

1. Создана вся структура из раздела 4.
2. Extraction, build и validation команды завершаются code 0.
3. `reports/validation.json` содержит `ok: true`.
4. В inventory ровно 161 item ожидаемого состава.
5. Галерея открывается локально и показывает 161 карточку.
6. Поиск, фильтры, сортировка, shortlist и фильтр по techniques работают.
7. Human decisions сохраняются и экспортируются в корректный JSON.
8. Forbidden item нельзя случайно принять как runtime-ready без явного
   визуального предупреждения.
9. В git не добавлены upstream source tree, MP4/WAV/MOV или файлы > 2 MB.
10. Существующий production-код не изменён.
11. LLM/provider/render вызовов не было.
12. `git status --short` показывает только ожидаемые файлы этого этапа и данное
    ТЗ.
13. Созданы `inventory/techniques.json` и
    `reports/techniques-catalog.md`.
14. Каждый из 161 catalog items связан минимум с одним содержательно описанным
    приёмом.
15. В справочнике есть матрицы item → techniques и technique → implementations,
    а также разделы ready/adapt/reference/forbidden/gaps.

## 13. Финальный отчёт модели-исполнителя

Ответ модели после выполнения должен быть коротким и доказательным:

```text
Stage 01 catalog: COMPLETE | BLOCKED

Создано:
- <пути к главным артефактам>

Counts:
- upstream blocks: N
- upstream components: N
- local blocks: N
- approved layouts: N
- approved transitions: N
- total: N
- techniques: N

Справочник приёмов:
- <путь к techniques-catalog.md>
- категории: <список категорий и количество приёмов в каждой>
- ready/adapt/reference/forbidden: <counts>

Validation:
- command: <команда>
- result: PASS | FAIL

Ограничения/предупреждения:
- <только реальные предупреждения>

Не выполнялось:
- LLM/edit_plan/render/provider calls
```

Если задача blocked, укажи точный failing check и путь к `reports/blockers.md`.
Не заявляй completion при неполном каталоге или failing validation.
