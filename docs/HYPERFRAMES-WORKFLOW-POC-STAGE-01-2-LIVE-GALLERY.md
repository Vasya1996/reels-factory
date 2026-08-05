# ТЗ Stage 01.2 — живая HTML-галерея всех элементов каталога HyperFrames

## 0. Роль исполнителя

Ты исполнитель технической задачи. Не придумывай новые шаблоны, не улучшай
дизайн исходных шаблонов и не принимай творческих решений. Твоя задача — взять
каждую существующую реализацию из уже собранного каталога, запустить её в
корректном HTML/HyperFrames host и сделать доступной для визуального просмотра.

Это отдельный этап аудита каталога. Это не монтаж ролика и не адаптация
компонентов для production.

## 1. Рабочее место

Репозиторий:

```text
C:\Users\Asus\Documents\personal_ai\projects\content_factory\reels-factory-hyperframes-workflow-poc
```

Рабочая ветка:

```text
codex/hyperframes-workflow-poc
```

Работай в существующей ветке. Не создавай новую ветку. Не делай commit, push,
PR или deploy.

До любых изменений прочитай полностью:

```text
AGENTS.md
docs\HYPERFRAMES-WORKFLOW-POC-STAGE-01-CATALOG.md
docs\HYPERFRAMES-WORKFLOW-POC-STAGE-01-1-CATALOG-CORRECTION.md
experiments\hyperframes-workflow-poc\stage-01-catalog\README.md
experiments\hyperframes-workflow-poc\stage-01-catalog\source-manifest.json
experiments\hyperframes-workflow-poc\stage-01-catalog\reports\catalog-audit.md
experiments\hyperframes-workflow-poc\stage-01-catalog\inventory\items.json
```

Также прочитай обязательные локальные skills HyperFrames:

```text
C:\Users\Asus\.codex\skills\hyperframes\SKILL.md
C:\Users\Asus\.codex\skills\hyperframes-core\SKILL.md
C:\Users\Asus\.codex\skills\hyperframes-registry\SKILL.md
C:\Users\Asus\.codex\skills\hyperframes-cli\SKILL.md
```

Следуй ссылочным инструкциям skills для реально запускаемых CLI-команд.

## 2. Зачем нужен этап

Текущая галерея содержит 161 карточку, но она не является полной живой
HTML-галереей:

- у части карточек показаны только official posters;
- 48 карточек используют placeholder;
- для 33 элементов preview помечен как недоступный;
- один и тот же contact sheet используется как poster нескольких approved
  layouts;
- по статичной карточке нельзя понять движение и поведение компонента;
- component snippets и transitions не запускаются как самостоятельные сцены.

Пользователь хочет открыть одну страницу, увидеть все элементы каталога и для
каждого элемента посмотреть его настоящее визуальное поведение.

## 3. Точный scope

Источник истины — существующий файл:

```text
experiments\hyperframes-workflow-poc\stage-01-catalog\inventory\items.json
```

Обработать ровно 161 уникальный catalog item:

| Source/kind | Количество |
|---|---:|
| upstream blocks | 113 |
| upstream components | 25 |
| local blocks | 8 |
| approved layouts | 10 |
| approved transitions | 5 |
| Итого | 161 |

Не исключать `adapt`, `reference_only` или `forbidden`: пользователь хочет
увидеть весь каталог. Статусы сохранить и явно показать badge на карточке.
`forbidden` означает «нельзя использовать в production», а не «скрыть из
галереи».

Не добавлять upstream examples: они не входят в эти 161 item.

## 4. Строгие запреты

- Не рисовать новый вариант существующего блока вручную.
- Не заменять реальную реализацию похожей самодельной карточкой.
- Не выдавать official poster за live HTML preview.
- Не создавать вымышленные variants, techniques, catalog IDs или parameters.
- Не менять `inventory/items.json`, `inventory/techniques.json`, assessment,
  status, score или shortlist.
- Не менять Stage 02 edit plan и Stage 03 render ТЗ.
- Не вызывать LLM/provider API, HeyGen, ElevenLabs, TTS, image generation или
  другие платные API.
- Не использовать runtime network assets в итоговой галерее.
- Не запускать массовый video render 161 MP4: для задачи нужны live HTML pages
  и локальные thumbnails, а не отдельный MP4 для каждого item.
- Не переписывать исходный registry snapshot.
- Не заявлять `COMPLETE`, если существуют placeholder-карточки, незаписанные
  ошибки или отсутствующие catalog IDs.

## 5. Источники реализаций

Используй `source_ref` каждого item. Не угадывай путь по имени.

### 5.1. Upstream

Frozen source snapshot:

```text
C:\Users\Asus\Documents\personal_ai\projects\content_factory\reference-audit\hyperframes-main-20260801-complete\hyperframes-main
```

Для каждого upstream item:

1. прочитай `source_ref.manifest`;
2. прочитай все `source_ref.implementation`;
3. скопируй необходимые implementation/assets в изолированный preview;
4. сохрани исходное визуальное поведение;
5. локализуй runtime dependencies, не меняя смысл реализации.

### 5.2. Local blocks

Источники:

```text
plugins\reels-factory\engine\src\reels_factory\hyperframes_blocks.py
plugins\reels-factory\engine\hyperframes\
```

Используй существующие Python generators и их реальные defaults. Не копируй
внешний вид вручную в новый HTML.

### 5.3. Approved layouts и transitions

Источники:

```text
C:\Users\Asus\Documents\personal_ai\projects\content_factory\plan-previews\two-reel-catalog-proxy-20260729\assets\catalog.js
C:\Users\Asus\Documents\personal_ai\projects\content_factory\plan-previews\two-reel-catalog-proxy-20260729\assets\catalog.css
```

Используй функции/стили, указанные в `source_ref` и `evidence_refs`. Не
восстанавливай approved layouts по screenshot.

Для speaker layouts используй как fixture реальное видео:

```text
C:\Users\Asus\Downloads\Продажи\1.mp4
```

В preview embedded audio этого файла должен быть выключен.

## 6. Что считается настоящим preview

Для каждого catalog item должен существовать отдельный runnable HTML preview,
который использует его настоящую implementation.

### 6.1. Upstream block

Block — самостоятельная sub-composition. Подключай его в минимальный host через
`data-composition-src` по правилам HyperFrames registry. Внутренний
`data-composition-id`, host ID и timeline key должны совпадать.

Не вставляй block source как screenshot или background image.

### 6.2. Upstream component

Component — snippet без собственного canvas. Для него разрешено создать
нейтральный host fixture, потому что без target element компонент невозможно
увидеть.

Правила host fixture:

- использовать фактический HTML/CSS/JS snippet без изменения visual logic;
- создавать только минимальный target, который прямо требуется компоненту;
- caption component получает короткую тестовую русскую фразу;
- media treatment получает локальный image/video fixture;
- text effect получает нейтральный крупный текст;
- transition-like component получает две нейтральные сцены A/B;
- fixture не должен выглядеть как новый авторский шаблон;
- в manifest указать, какая часть является upstream component, а какая —
  техническим host fixture.

### 6.3. Approved transition

Покажи реальный переход между двумя нейтральными full-frame состояниями A и B.
Preview обязан включать время до перехода, сам переход и состояние после него.

### 6.4. Approved layout

Покажи layout с реальным `1.mp4`, нейтральным коротким текстом и необходимым
media fixture. Используй настоящие `render*`/`animate*` функции и CSS исходного
approved catalog.

### 6.5. Local block

Сгенерируй HTML существующим generator. Если generator принимает parameters,
используй его реальные defaults либо documented test values. Не добавляй новый
дизайн.

## 7. Fixtures

Создай один набор локальных fixture assets, повторно используемый previews:

```text
live-gallery\assets\fixtures\
  avatar.mp4
  neutral-video.mp4
  neutral-image.jpg
  neutral-square.png
  neutral-code.txt
```

Правила:

- `avatar.mp4` — локальная копия `Продажи\1.mp4`, muted в preview;
- остальные fixtures получить локально из уже существующих repository/media
  файлов или кадра существующего видео;
- не генерировать изображения внешней моделью;
- не скачивать случайные stock assets;
- fixture должен помогать увидеть эффект, но не заменять его;
- все fonts, images, videos, LUTs, textures, shaders и runtime scripts должны
  загружаться локально.

Если implementation ссылается на remote URL, сначала найди соответствующий
файл во frozen upstream snapshot. Только если файла там объективно нет, запиши
URL и ошибку в audit. Не оставляй сетевой запрос в runnable preview.

## 8. Выходная структура

Добавляй новый каталог, существующую `gallery/` не удаляй и не переписывай:

```text
experiments\hyperframes-workflow-poc\stage-01-catalog\live-gallery\
  README.md
  index.html
  assets\
    gallery.css
    gallery.js
    fixtures\
    runtime\
  previews\
    <safe-catalog-id>\
      index.html
      item-manifest.json
      assets\
  thumbnails\
    <safe-catalog-id>.jpg
  contact-sheets\
    sheet-01.jpg
    ...
  reports\
    live-gallery-manifest.json
    live-gallery-audit.md
    runtime-results.json
    failures.json
  scripts\
    build-live-gallery.mjs
    capture-live-gallery.mjs
    validate-live-gallery.mjs
    serve-live-gallery.mjs
```

`safe-catalog-id` должен быть детерминированно получен из полного catalog ID.
Создай reverse mapping в `live-gallery-manifest.json`.

## 9. Поведение главной страницы

`live-gallery/index.html` должна содержать 161 карточку и работать через
локальный HTTP server.

На каждой карточке показать:

- thumbnail, снятый с реального runnable preview;
- title;
- полный catalog ID;
- source;
- kind;
- review status;
- orientation и исходные dimensions;
- duration;
- короткое description;
- кнопки `Открыть live preview` и `Показать source`;
- badge `host fixture`, если это component/transition harness;
- заметную маркировку `forbidden`.

Фильтры:

- поиск;
- source;
- kind;
- review status;
- orientation;
- live status (`PASS`/`FAIL`).

Не загружай 161 iframe одновременно. При открытии карточки лениво загружай один
preview в modal/drawer. При закрытии удаляй iframe.

В modal должны быть:

- preview с сохранением aspect ratio;
- Play/Pause;
- Restart;
- time scrubber или минимум кнопки Start/Middle/End;
- реальная duration;
- ссылка на item manifest;
- текст ошибки, если preview не прошёл.

Landscape/adaptive items не растягивать до portrait. Показывать их в
letterboxed viewport согласно declared dimensions.

## 10. Детерминированный builder

`build-live-gallery.mjs` обязан:

1. читать ровно 161 item из `inventory/items.json`;
2. валидировать уникальность ID;
3. резолвить implementation только через `source_ref`;
4. выбирать harness по `source + kind`, а не по случайным эвристикам;
5. создавать отдельный preview directory для каждого item;
6. копировать только нужные локальные dependencies;
7. записывать provenance каждого файла;
8. собирать главную страницу и manifest;
9. быть идемпотентным;
10. не изменять source inventory и frozen upstream snapshot.

При повторном запуске на тех же входах output должен быть одинаковым, кроме
вынесенных отдельно audit timestamps.

## 11. Thumbnail и выбор времени

Thumbnail должен быть снят из runnable HTML preview, а не скопирован из
`preview.poster_local`.

Для animated item захвати минимум три точки:

```text
15% duration
50% duration
85% duration
```

Выбери thumbnail как наиболее информативную небелую/нечёрную точку. Запиши
выбранное время в item manifest.

Для transition захвати:

```text
до перехода
середина перехода
после перехода
```

Для static item достаточно midpoint.

## 12. Валидация

`validate-live-gallery.mjs` должен fail с ненулевым exit code, если нарушено
хотя бы одно условие:

- количество карточек не 161;
- отсутствует хотя бы один ID из inventory;
- появился неизвестный ID;
- для item нет preview directory или item manifest;
- thumbnail отсутствует, пустой или равен placeholder;
- preview использует remote network dependency;
- implementation provenance отсутствует;
- runnable page имеет console/page/runtime error;
- asset возвращает 404;
- кадр полностью чёрный, белый, прозрачный или пустой;
- source implementation подменена самодельной имитацией;
- размеры/aspect ratio не соответствуют item manifest;
- approved/local item не использует доказанный source_ref;
- component host не отделён от component implementation в manifest.

Дополнительно проверить:

- `113 + 25 + 8 + 10 + 5 = 161`;
- все 161 thumbnails имеют собственную запись с hash;
- одинаковые hashes перечислены и объяснены, а не молча приняты;
- фильтры возвращают правильное количество;
- modal загружает и выгружает iframe;
- клавиатурой можно закрыть modal через Escape;
- browser не делает network requests за пределы localhost.

## 13. Визуальный аудит

Сделай contact sheets из всех 161 thumbnail, не более 20 элементов на лист.
На каждом thumbnail подпиши короткий ID и status.

Обязательно физически открой все contact sheets и проверь:

- нет placeholders;
- нет повторяющегося общего approved contact sheet вместо конкретных layouts;
- нет blank/black previews;
- заголовки/лица/главные объекты не обрезаны harness viewport;
- landscape items показаны как landscape;
- portrait items показаны как portrait;
- forbidden item присутствует и заметно маркирован;
- component effect действительно виден на target fixture;
- transition midpoint действительно показывает переход.

Запиши результат по каждому листу в `live-gallery-audit.md`.

## 14. Как запускать и показывать пользователю

Галерея должна запускаться одной командой без внешнего network:

```text
node live-gallery\scripts\serve-live-gallery.mjs
```

Server должен слушать только:

```text
http://127.0.0.1:4173/
```

В `live-gallery/README.md` укажи точную команду из repository root и URL.
Не требуй от пользователя вручную устанавливать глобальный package.

После сборки исполнитель должен запустить server, открыть главную страницу в
браузере и вручную проверить минимум:

- один upstream block;
- один upstream component;
- один local block;
- один approved layout с avatar video;
- один approved transition;
- поиск и каждый filter;
- открытие, проигрывание и закрытие modal.

## 15. Граница между просмотром и production

Живая галерея показывает настоящее визуальное поведение, но не меняет
production readiness:

- `ready` остаётся ready;
- `adapt` остаётся adapt;
- `reference_only` остаётся reference_only;
- `forbidden` остаётся forbidden.

Успешный preview не означает, что item автоматически безопасен для монтажного
compiler. Не исправляй status в рамках этого этапа.

## 16. Что вернуть пользователю

Не писать `COMPLETE`, пока validator не прошёл и не существует 161 карточка.

В финальном сообщении вернуть кликабельные абсолютные ссылки на:

1. `live-gallery/index.html`;
2. `live-gallery/README.md`;
3. `live-gallery/reports/live-gallery-audit.md`;
4. `live-gallery/reports/live-gallery-manifest.json`;
5. первый contact sheet;

и указать URL локального server:

```text
http://127.0.0.1:4173/
```

Обязательно сообщить:

- cards total;
- PASS/FAIL previews;
- counts по source/kind;
- сколько remote dependencies было локализовано;
- сколько harness fixtures создано;
- какие items не удалось запустить и точную причину каждого;
- команды build/validate/serve;
- результаты ручной browser-проверки.

Если хотя бы один item не запускается, не скрывать его и не заменять
placeholder. Оставить карточку с `FAIL`, точной ошибкой и source provenance, а
общий этап назвать `PARTIAL`, не `COMPLETE`.
