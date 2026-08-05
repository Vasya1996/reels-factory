# HyperFrames Workflow POC — краткий handoff для Васи и его AI

Дата состояния: 2 августа 2026 года.

## 1. Что мы проверяем

Нужно улучшить автоматический монтаж вертикальных роликов с аватаром, озвучкой,
субтитрами, смысловой графикой, переходами и SFX.

Главная гипотеза POC: **для каждого ролика не нужна дорогая многоагентная
система**. Достаточно:

1. один раз вызвать сильную LLM как визуального режиссёра;
2. получить строгий JSON `edit_plan`;
3. дальше выполнить план детерминированными скриптами и HyperFrames;
4. показать человеку черновой MP4, внести правки в план и перерендерить без
   нового творческого LLM-вызова.

Skills и workflow из HyperFrames используются как источник правил, вкуса и
технических контрактов. Их не нужно заново исполнять агентами при каждом
монтаже: стабильную часть мы переносим в схему, каталог, валидатор и компилятор.

## 2. Где ведётся работа

- Репозиторий: `reels-factory-hyperframes-workflow-poc`
- Ветка: `codex/hyperframes-workflow-poc`
- POC: `experiments/hyperframes-workflow-poc/`
- Stage 01: `experiments/hyperframes-workflow-poc/stage-01-catalog/`
- Stage 02: `experiments/hyperframes-workflow-poc/stage-02-edit-plan/`

Изменения Stage 01/02 пока находятся в рабочем дереве и не должны быть
случайно удалены или перезаписаны.

## 3. Согласованная архитектура

```text
сценарий + master audio + word alignment + avatar/media inventory
                              ↓
              проверенный компактный каталог приёмов
                              ↓
              ОДИН вызов LLM Visual Director
                              ↓
                    строгий edit_plan.json
                              ↓
      schema validation + бизнес-правила + перевод слов в секунды
                              ↓
      детерминированный edit_plan → HyperFrames compiler/adapter
                              ↓
       локальные assets + seek-safe HTML/GSAP compositions
                              ↓
       HyperFrames lint/check/snapshots → draft render MP4
                              ↓
          human review → правка JSON → повторный render
```

Важно: HyperFrames уже содержит renderer/compiler для **готовой HTML-композиции**.
Но он не компилирует нашу прикладную схему `edit_plan` автоматически. Нам нужен
свой тонкий детерминированный слой `edit_plan → composition`, который использует
нативные контракты HyperFrames, а не заменяет их.

LLM решает только творческие вопросы: что показать, когда оставить/скрыть лицо,
какой смысловой блок, layout, transition и SFX intent выбрать. LLM не пишет
HTML/CSS/JS, не считает секунды и не рендерит.

## 4. Что уже сделано

### Stage 01 — каталог

Собран и провалидирован каталог из 161 элемента:

- 113 upstream blocks;
- 25 upstream components;
- 8 локальных semantic blocks;
- 10 approved layouts;
- 5 approved transitions.

Выделено 165 монтажных приёмов. Статусы элементов:

- `render_ready`: 22;
- `adapt_required`: 133;
- `reference_only`: 9;
- `forbidden`: 1.

Для текущего POC сформирован shortlist из 49 элементов:

- 22 можно использовать непосредственно;
- 27 можно только запросить на адаптацию, обязательно указав готовый fallback.

Готовы inventory, JSON Schema, gallery, постеры, аудит, справочник приёмов и
скрипты повторной сборки/валидации. 14 upstream-постеров не скачались, но это не
блокирует runtime. Визуальная ручная проверка всей gallery ещё не завершена.

Главные файлы:

- `stage-01-catalog/inventory/items.json`
- `stage-01-catalog/inventory/techniques.json`
- `stage-01-catalog/shortlist/auto-shortlist.json`
- `stage-01-catalog/reports/techniques-catalog.md`
- `stage-01-catalog/reports/catalog-audit.md`

### Stage 02 — один режиссёрский план

Подготовлены:

- точный сценарий и ElevenLabs alignment;
- 100 пословных таймингов;
- компактный каталог из 49 кандидатов;
- системный prompt Visual Director;
- строгая JSON Schema;
- скрипты подготовки запроса и валидации ответа;
- человекочитаемый монтажный таймлайн.

Создан `edit_plan` на 13 сцен для ролика «Три вопроса в продажах».

Результат валидации:

- `PASS`, ошибок и предупреждений нет;
- длительность: 42,32 секунды;
- покрытие: 100/100 слов без пропусков и пересечений;
- максимум без ведущей: 6,187 секунды при лимите 8 секунд;
- основной переход используется в 66,7% смен.

Главные файлы:

- `stage-02-edit-plan/edit_plan.draft.json`
- `stage-02-edit-plan/edit_plan.timed.json`
- `stage-02-edit-plan/reports/human-review.md`
- `stage-02-edit-plan/reports/plan-validation.json`
- `stage-02-edit-plan/schemas/edit-plan.schema.json`
- `stage-02-edit-plan/scripts/validate-and-present.mjs`

Попытка вызвать Claude Sonnet завершилась до инференса с `401 OAuth token
revoked`: стоимость $0, input/output tokens 0. Поэтому текущий draft сформирован
в активной Codex/OpenAI-сессии по тому же контракту. Его нельзя приписывать
Claude или модели с точным названием GPT-5.5.

## 5. Как выглядит утверждаемый монтажный план

```text
00:00–00:03  лицо + крупная цифра 3: «Все продажи = 3 вопроса»
00:03–00:05  лицо в editorial bubble + КТО / ЧТО / КАК
00:05–00:09  без лица: Complexity Cloud, «усложняем продажи»
00:09–00:12  без лица: скрипты и волшебные фразы зачёркиваются
00:12–00:14  лицо возвращается, шум собирается в три вопроса
00:14–00:19  лицо + Persona Card: кому продаём, контекст и боль
00:19–00:23  Value Layers: продукт → реальная ценность
00:23–00:26  лицо + третий вопрос: где встречаемся
00:26–00:29  лицо + слова и формат предложения
00:29–00:32  Concept Nodes: остальное — надстройка
00:32–00:34  лицо крупно: «Самое важное — порядок»
00:34–00:38  payoff без лица: КТО → ЧТО → КАК
00:38–00:42  лицо + Social Outro + @julia.agents
```

## 6. Какие приёмы уже выбраны в текущем edit_plan

### Layouts

- `avatar_object_overlay` — ведущая и смысловой объект/графика;
- `avatar_editorial_bubble` — ведущая в крупном editorial bubble;
- `avatar_broll_split` — ведущая и смысловой контент в split;
- `avatar_fullscreen_anchor` — крупный план для eye contact;
- `progressive_text_card` — крупная поэтапно собирающаяся типографика;
- `checklist_strike_routine` — появление и зачёркивание лишних действий;
- `social_outro_lockup` — финальный CTA и handle.

### Смысловые блоки

- `animated_stat_countup` / `stat_number` — крупная цифра 3 в hook;
- `complexity_to_resolution` / `complexity_cloud` — визуальный шум
  схлопывается в простую основу;
- `task_checklist_reveal` / `task_list` — последовательный список;
- `concept_node_map` / `concept_nodes` — связанные опорные понятия;
- `persona_context_card` / `persona_card` — человек, контекст и боль;
- `value_layer_swap` / `value_layers` — формальный продукт меняется на
  реальную ценность;
- `sequence_step_flow` / `sequence_flow` — обязательный порядок
  `КТО → ЧТО → КАК`.

### Типографика и captions

В плане как visible craft используются:

- `caption_kinetic_slam`;
- `caption_editorial_emphasis`;
- `caption_highlight`;
- `caption_clip_wipe`;
- `caption_weight_shift`;
- `caption_gradient_fill`;
- `caption_pill_karaoke`.

Caption-режим по умолчанию — `bottom` с accumulate-поведением. В payoff
`КТО → ЧТО → КАК` captions скрыты, потому что полноэкранная графика повторяет
эту фразу. Шрифт — Unbounded, keyword color — `#FFE500`, watermark —
`@julia.agents` после 2-й секунды.

### Переходы

- основной: `hard_cut_transition` — 8 из 12 смен, 66,7%;
- смысловой акцент: `editorial_push_transition`;
- кульминационный акцент: `white_flash_transition`.

Разные эффектные переходы не чередуются случайно: один основной переход
создаёт язык ролика, акценты используются только на смысловых поворотах.

### SFX intents

Запланированы: numeric impact на цифре 3, бумажные тики для нарастающей
сложности, два звука зачёркивания, собранный whoosh при переходе к трём
вопросам, мягкий card flip, звук складывающихся слоёв, три чистых щелчка для
`КТО/ЧТО/КАК` и тихий confirmation click в CTA.

Все SFX, кроме трёх payoff-щелчков, необязательны. Конкретные локальные файлы
ещё не разрешены; в плане записаны только semantic intents.

### Приёмы, которые пока нельзя использовать напрямую

Три `adaptation_requests`:

1. `Kinetic Slam` для слова «ТРЁМ» → fallback `Stat Number`;
2. `Highlight` для сцены об усложнении → fallback `Complexity Cloud`;
3. `Morph Text` для `КТО → ЧТО → КАК` → fallback `Sequence Flow`.

Для первого render безопаснее использовать fallbacks. Адаптации можно сделать
отдельно: русские content variables, 1080×1920, word-index triggers, уникальные
IDs, локальные зависимости и один paused seek-safe GSAP timeline.

## 7. Что можно переиспользовать при реализации

- Upstream HyperFrames snapshot:
  `reference-audit/hyperframes-main-20260801-complete/hyperframes-main/`
- Зафиксированная в аудите версия HyperFrames: `0.7.87`.
- Локальные block generators:
  `plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py`
- Локальные реализации блоков:
  `plugins/reels-factory/engine/hyperframes/`
- Approved layout/transition reference implementation:
  `plan-previews/two-reel-catalog-proxy-20260729/assets/catalog.js`
  и `assets/catalog.css`.
- Для каждого элемента в `items.json` записаны `source_ref`, evidence lines,
  параметры, runtime, зависимости и риски. Реализацию нужно брать оттуда, а не
  восстанавливать по названию.
- В production-коде уже есть canonical `edit_plan` lifecycle, semantic blocks,
  Avatar Islands и Revideo fallbacks. Полезные документы:
  `docs/EDIT-PLAN.md` и `docs/VISUAL-DIRECTOR.md`.

## 8. Проверенные исходники тестового ролика

Канонический текст и alignment:

- `/root/reels-workspace/factory/diagnostics/ivc-v3-scenario-20260726T182834Z/input/scenario.json`
- `/root/reels-workspace/factory/diagnostics/ivc-v3-scenario-20260726T182834Z/eleven/alignment.json`

Master audio:

- `/root/reels-workspace/factory/diagnostics/ivc-v3-scenario-20260726T182834Z/eleven/voice_master.wav`
- `/root/reels-workspace/factory/diagnostics/ivc-v3-scenario-20260726T182834Z/eleven/voice_master.mp3`
- длительность: 42,32 секунды;
- MP3 SHA-256: `f42c584d9a966f8fec66d2c4e6602e526a7a4b8391df090caacf20ecc40432bc`;
- text SHA-256: `d5f1deeb1f636eb5ec2dcab93c5de7e1cca19fc17282d8d342972ee3fe5f7748`.

Фото аватара из нужной bot-сессии:

- `/root/reels-workspace/work/bot/823757031/input/file_67.jpg`
- HeyGen photo asset ID из `session.json`:
  `a492ac87e6d642bb99c0a820b6a8c8fc`.

### Avatar MP4 найден

Пользователь предоставил четыре последовательных avatar island:

- `C:\Users\Asus\Downloads\Продажи\1.mp4` — 11,720 с;
- `C:\Users\Asus\Downloads\Продажи\2.mp4` — 10,920 с;
- `C:\Users\Asus\Downloads\Продажи\3.mp4` — 11,480 с;
- `C:\Users\Asus\Downloads\Продажи\4.mp4` — 6,888 с.

Все четыре: H.264, 1080×1920, 25 fps, AAC 48 kHz stereo; визуально это один и
тот же аватар в одном образе и помещении. Порядок файлов хронологический.

Их суммарная длительность — 41,008 секунды, master audio — 42,320 секунды.
Stage 03 должен собрать их в непрерывный silent avatar base, синхронизировать с
master timeline и использовать master WAV как единственную финальную голосовую
дорожку. Новая платная генерация ElevenLabs/HeyGen не требуется и запрещена.

Полный технический контракт: `docs/HYPERFRAMES-WORKFLOW-POC-STAGE-03-RENDER.md`.

## 9. Следующий этап — Stage 03 test render

Цель: показать один черновой MP4 по уже существующему `edit_plan`, а не менять
архитектуру production.

Порядок:

1. Принять четыре найденных avatar island, проверить SHA/duration и собрать
   синхронизированный silent avatar base длиной 42,32 секунды.
2. Создать изолированный
   `experiments/hyperframes-workflow-poc/stage-03-render/`; Stage 01/02 не
   изменять.
3. Скопировать/принять локально master audio, avatar video и alignment. Записать
   provenance, SHA и ffprobe в asset manifest.
4. Реализовать детерминированный compiler/adapter, который читает
   `edit_plan.timed.json`, approved contracts и local blocks.
5. Для первого render использовать только 22 `render_ready` элемента и
   fallbacks для трёх adaptation requests.
6. Построить 13 seek-safe сцен/sub-compositions, единый master audio, captions,
   approved transitions и доступные локальные SFX.
7. Запустить HyperFrames `lint`, затем `check`; проверить midpoint snapshots,
   первый/последний кадр, safe zones, отсутствие чёрных/пустых сцен и animation
   map.
8. Сделать локальный draft render 1080×1920, 30 fps, 42,32 секунды. Проверить
   MP4 через ffprobe и подготовить contact sheet.
9. Отдать пользователю MP4 и таблицу фактических отличий от `edit_plan`. После
   правок менять JSON/параметры и перерендеривать без нового LLM-вызова.

## 10. Критерий успеха гипотезы

POC успешен, если после одного режиссёрского JSON-решения скрипты способны
воспроизводимо собрать ролик, а пользователь может изменить сцену, layout,
приём, переход или SFX через правку плана и получить новый render без участия
агентской системы.

Если для каждого render снова потребуется агент читать все skills, вручную
писать сцены и чинить их по одной, гипотеза «один вызов + workflow» не
подтверждена. Тогда нужно не добавлять агентов, а расширять каталог
параметризованных контрактов и compiler/adapter до нужного уровня.

## 11. Обновлённая архитектура: один LLM-вызов и детерминированный placement

Единственный творческий вызов модели должен возвращать семантический
`edit_plan`. Модель выбирает границы сцен, avatar coverage, catalog IDs,
текст/labels/emphasis, caption mode, transition IDs, SFX/media intents и
разрешённые fallbacks. Она не пишет HTML и не выбирает пиксельные координаты.

После человеческого подтверждения вся дальнейшая работа выполняется скриптами:

```text
ElevenLabs master audio + word timestamps
  -> компактный prompt с каталогом и constraints
  -> один LLM edit_plan
  -> schema/policy validation
  -> человеческая правка JSON без второго LLM
  -> детерминированный Avatar Island plan
  -> cached Photo Avatar IV generation
  -> catalog/source_ref resolver
  -> caption и layout placement
  -> animation/transition/SFX binding
  -> HyperFrames compiler
  -> collision/check/snapshot gates
  -> render и ffprobe audit
```

Avatar Islands вычисляются только после фиксации edit plan. Соседние фразы с
`coverage=avatar|mixed` образуют island; `coverage=full_broll|hyperframes`
разрывает его. Детерминированный planner делит island на performance shots;
HeyGen generation — provider step, а не новый монтажный LLM-вызов.

### Обновлённая ответственность forbidden zones

Для стабильного avatar/look/framing первый island анализируется один раз. Face
envelope сохраняется в координатах исходного видео, а каждый layout применяет к
нему тот же crop/scale/position transform, что и к avatar video.

Зоны используются в пяти местах:

1. до LLM — для фильтрации несовместимых layout IDs;
2. при размещении captions, после чего их реальные bounds становятся новой
   hard forbidden zone;
3. при выборе overlay slots внутри утверждённого layout;
4. при проверке полного swept envelope анимации;
5. при финальной покадровой DOM collision validation до render.

LLM не получает и не выдаёт координаты. Если слот не подходит, скрипты могут
попробовать другой slot, документированное минимальное уменьшение или
разрешённый в плане fallback. Иначе сборка завершается с ошибкой. Compiler не
может молча менять творческий layout.

Hard forbidden zones: platform UI, лицо и измеренные captions. Торс/руки могут
быть soft zones там, где layout осознанно допускает overlap. Информационные
элементы не пересекают hard zones. Full-frame transition требует явной exception
маркировки.

Эта цепочка пока не реализована. Текущий POC использует fixed approved CSS,
HyperFrames checks и ручной contact-sheet review. Будущие артефакты:
`avatar-profile.json`, `layout-slots.json`, `forbidden-zones.json` и покадровый
`collision-report.json`.

## 12. Откуда фактически взялись анимации Stage 03

Важная поправка после проверки самого compiler-кода: текущий Stage 03 не
подключил исходные реализации напрямую. В
`stage-03-render/scripts/compile-edit-plan.mjs` нет import/call к
`hyperframes_blocks.py`, `catalog.js` или `catalog.css`. Вместо этого модель
написала собственные `blockMarkup`, `layoutChrome`, `sceneCss` и `sceneScript`
с hard-coded HTML/CSS/GSAP. Пути к Python generators и approved catalog в
`compiler-report.json` являются строками атрибуции, но не доказывают runtime
reuse.

То есть модель не изобрела общий визуальный язык с нуля: она опиралась на
edit plan, перечисленные catalog IDs и стили прошлых роликов. Но конкретный
render является её одноразовой упрощённой реализацией/адаптацией этих приёмов,
а не сборкой неизменённых готовых шаблонов из каталога.

Три запрошенных upstream components не адаптировались в первом render:

- `caption-kinetic-slam` -> `local:block:stat_number`;
- `caption-highlight` -> `local:block:complexity_cloud`;
- `morph-text` -> `local:block:sequence_flow`.

Даже fallback local IDs в этом render были заново описаны внутри JS compiler,
а не созданы вызовом исходных Python builders. Поэтому текущий результат ещё
не подтверждает главную гипотезу о полноценном catalog-driven workflow. Для
следующего прогона нужен настоящий resolver: ID -> проверенный adapter/source
implementation -> declared parameters -> composition. Provenance должна
проверяться механически, а не только записываться в отчёт. Stage 03 использовал
HyperFrames `0.7.88` после upgrade с зафиксированной в Stage 01 версии `0.7.87`;
эту разницу сохранять в audit.

### Исполняемые формы каталога и параметризация

161 catalog item не равны 161 готовым взаимозаменяемым шаблонам:

- 113 upstream blocks — standalone HTML compositions;
- 25 upstream components — HTML/CSS/JS snippets, которым нужен host;
- 8 local blocks — Python-generated HTML с function arguments;
- 10 approved layouts и 5 approved transitions — JS/CSS contracts;
- 165 techniques — описания визуальных приёмов, связанные с реализациями, а не
  самостоятельные executable objects.

Stage 01.1 parameterization audit:

- declarative: 2;
- generated Python: 8;
- approved JS contract: 15;
- без доказанного parameter contract: 136.

Для declarative/Python/approved contracts скрипты подставляют только
документированные поля: text, labels, numbers, colors, media paths, timing и
другие объявленные variables. Остальные реализации можно показать как есть,
но подстановка production content требует отдельного adapter. LLM может
запросить адаптацию и desired values, но не должна считать adapter уже
существующим.
