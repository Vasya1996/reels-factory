# Живой тест HyperFrames polish — 2026-07-29

## Контекст

- Ветка: `codex/hyperframes-polish`
- Проверяемый commit: `ea45ea687b6cfe371818f0db0f4b01e1837cc659`
- HyperFrames в коде: `0.7.70`
- Последняя доступная версия unscoped npm-пакета на момент теста: `0.7.81`
- Архив материала: `reels-factory-e2e-20260727-d2aa4090`
- Production checkout и `reels-bot.service` не менялись. Тест выполнялся в
  отдельной detached worktree и отдельном job-каталоге.

## Гарантия по платным провайдерам

Во время теста **не вызывались ElevenLabs и HeyGen API**.

Повторно использованы:

- `job/voice_master.wav`;
- `job/alignment.words.json`;
- пять готовых клипов
  `provider-assets/heygen-clips/avatar-shot-000..004.mp4`;
- архивные visual/performance recommendations из `job/edit_plan.json`.

Одноразовый runner до запуска compose сравнил число шотов и нормализованный
текст каждого нового `avatar_render_plan.shots[]` с архивным планом. При любом
расхождении он должен был остановиться, а не заказывать новые клипы. Проверка
прошла: 5 из 5 шотов совпали.

Платными были только две headless Claude compose-сессии.

## Preflight

| Проверка | Результат |
|---|---|
| Новый edit plan | valid, без warnings |
| Готовые avatar shots | 5, все совпали по тексту |
| Длительность master WAV | 33.280 с |
| Длительность после `trim_master_pauses` | 33.280 с |
| Найденные pause cuts | `[]` |
| Назначенные stock/site/route materials | `[]` |
| Строки `ритм-материал` в plan log | `[]` |

Архивный master WAV уже не содержит пауз длиннее текущего порога. В этом
сценарии material resolver не запустился: два длинных смысловых участка уже
закрыты HyperFrames-сценами, а оставшиеся avatar windows по отдельности короче
трёх секунд.

## Хронология compose

### Попытка 1

- Стоимость: `$3.54838815`
- Получены `public/index.html`, `storyboard.json`, `agent.log`.
- Отклонена гейтом:

```text
D9_frame_grid: FAIL:
card-problem startSec=9.62 вне сетки кадров;
card-accent-output endSec=25.06 вне сетки кадров;
card-features startSec=25.06 вне сетки кадров
```

Runner добавил причину в `BRIEF.md`, сбросил compose/gates/check/render markers
и штатно запустил вторую попытку.

### Попытка 2

- Стоимость: `$2.07929010`
- D9 исправлен: времена квантованы до `9.633`, `17.167`, `25.067`,
  `28.933`, `31.133`, `33.267`.
- Отклонена гейтом:

```text
D13_rhythm: FAIL:
нет визуального события 4.000–9.633;
нет визуального события 17.167–25.067
```

Фактическая суммарная стоимость двух попыток: **`$5.62767825`**.

## Ручное восстановление теста без третьей compose-сессии

Чтобы проверить остальную цепочку, результат второй попытки был точечно
исправлен в изолированном job-каталоге.

### D13

Добавлены две реальные overlay-сцены в безопасной верхней полосе кадра и те же
cards в storyboard:

- `card-avatar-reveal`: `6.267–9.633`;
- `card-inputs`: `20.000–25.067`.

Первые четыре секунды остались чистыми. Face box архивного клипа:
`cx=540, cy=806, h=269`; оба новых `contentRect` находятся на `top=180`,
`height=240` и лицо не перекрывают.

После правки:

```json
{
  "D8_face": "PASS",
  "D9_frame_grid": "PASS",
  "D10_zone": "PASS",
  "D11_shape": "PASS",
  "D12_faceless_cover": "PASS",
  "D13_rhythm": "PASS"
}
```

### Ошибки `hyperframes check`, сгенерированные compose

После прохождения D8–D13 композиция не прошла технический check:

1. На root отсутствовали `data-width="1080"` и `data-height="1920"`.
2. На root отсутствовал `data-start="0"`.
3. 54 слова субтитров были объявлены вложенными `class="clip"` на одном
   `data-track-index="3"`. Их интервалы намеренно перекрываются до конца
   caption group, поэтому lint вернул 54
   `overlapping_clips_same_track`.
4. Runtime запрашивал отсутствующий `caption-overrides.json`, что дало:

```text
http_error: 404 loading caption-overrides.json
request_failed: Failed to load caption-overrides.json: net::ERR_ABORTED
```

5. Backup `index.compose-original.html`, временно оставленный внутри `public/`,
   был корректно распознан check как вторая root composition. После диагностики
   backup перенесён за пределы `public/`.

Для продолжения теста:

- root получил `data-start`, `data-width`, `data-height`;
- word spans стали обычными `.word-slot` с `data-word-start`, а их opacity
  по-прежнему управляется единой GSAP timeline;
- добавлен пустой `public/caption-overrides.json`;
- backup перенесён за пределы renderable project.

Итог перед render:

| Раздел check | Errors | Warnings |
|---|---:|---:|
| lint | 0 | 13 |
| runtime | 0 | 0 |
| layout | 0 | 0 |
| motion | 0 | 0 |
| contrast | 0 | 0 |

13 lint warnings — отсутствующие editable `id` у caption groups. В обычном
`check` они не блокируют render, но compose следует научить добавлять стабильные
ID.

## Итог render

Standard render завершён успешно.

| Параметр | Значение |
|---|---|
| Размер | 1080×1920 |
| FPS | 30 |
| Video frames | 999 |
| Длительность контейнера | 33.400 с |
| Размер файла | 17,129,531 bytes |
| SHA-256 | `2f3c07b7dbdb6ecfbd487c7eaaee887a420ba863ed5dba94d1bef95eb04cdb20` |
| Video stream | есть |
| Audio stream | есть |
| D8–D13 | все PASS |
| `hyperframes check` | PASS |

Production после теста:

- сервис остался `active`;
- production checkout остался на
  `0d74102b70c1bba1f6d9b2c93051229fda8f9d87`.

### Визуальная проверка контактного листа с шагом 3 секунды

PASS:

- первые четыре секунды — ведущая без вставок;
- новые верхние overlays не перекрывают лицо;
- кириллица отображается корректно;
- чёрных провалов между avatar clips и fullscreen cards нет;
- CTA сохраняет ведущую в кадре.

Не принято как финальное качество:

- fullscreen card `card-problem` длится `9.633–17.167` и после короткого
  entrance почти статична; на контактном листе несколько соседних кадров с
  шагом 3 секунды визуально одинаковы;
- похожая, но более короткая статичность есть у `card-features`.

Таким образом, техническая сборка успешна, но визуальный критерий «нет мёртвого
экрана дольше 3 секунд» фактически не выполнен, несмотря на `D13_rhythm=PASS`.

## Проблемы, которые нужно исправить в коде/промпте

### P0 — стоимость не тарифицируется при провале gates

`pipeline.run_make` вызывает `meter.claude(...)` только после успешного возврата
`assemble_hyperframes`. Если обе compose-попытки потратили деньги, но D8–D13
после второй попытки упали, `assemble_hyperframes` бросает исключение и `$5.63`
не попадают в billing.

Рекомендуемое направление: тарифицировать приращение
`agent_runner.total_cost_usd` после каждого `runner.run`, в `finally` либо через
callback/meter внутри `HeyGenAgentRunner`, а не только после успешной assembly.

### P0 — BRIEF и D13 противоречат друг другу

BRIEF говорит для avatar windows «вставки нет: показывай ведущую, карточку не
рисуй». D13 при этом считает ритм только по spans из `storyboard.cards` и
требует, чтобы после 4.0 с не было промежутка больше 3 секунд.

Рекомендуемое направление:

- до compose явно вычислять rhythm-event windows;
- перечислять их в BRIEF с квантованными границами;
- разрешать безопасный micro-overlay/camera event после hook guard;
- либо расширить D13 так, чтобы он учитывал не только cards, но и
  задекларированные camera/caption/motion events.

### P0 — D13 даёт false PASS на длинной статичной карточке

Текущая реализация D13 двигает `cursor` сразу к `card.endSec`. Поэтому одна
карточка длиной 7.5 секунды считается непрерывным ритмическим покрытием, даже
если вся анимация закончилась в первые 0.7 секунды и дальше кадр статичен.
Контактный лист этого прогона подтвердил false positive.

Рекомендуемое направление:

- storyboard должен перечислять события/фазы внутри длинной карточки, а не
  только её общий span;
- D13 должен проверять расстояние между event timestamps либо использовать
  `*.motion.json`/`keepsMoving`;
- длинные fullscreen cards нужно дробить на 2–3 cards или давать им реальные
  stagger/phase changes не реже чем раз в 3 секунды.

### P1 — compose prompt не закрепляет минимальный root/runtime contract

Нужно явно требовать:

- root: `data-composition-id`, `data-start="0"`, `data-duration`,
  `data-width="1080"`, `data-height="1920"`;
- ровно одну root composition в renderable directory;
- вложенные слова субтитров не являются `.clip`;
- стабильные `id` у timeline-visible caption groups;
- наличие `caption-overrides.json` либо запрет runtime-запроса к нему.

### P1 — D9 должен получать уже квантованные времена

Первая платная попытка была потрачена только на перевод `9.62/25.06` в сетку
30 fps. Все времена, которые BRIEF предлагает агенту, следует квантовать до
compose и показывать в BRIEF уже в финальном виде.

### P1 — диагностика `_cli` обрезана

`hf_render._cli` включает в исключение только первые 500 символов stderr/stdout.
При 56 lint errors или browser findings это скрывает блокирующую причину.

Рекомендуемое направление: писать полный stdout/stderr каждого шага в
`hyperframes-check.log` / `hyperframes-render.log`, а в исключении указывать
путь и краткую JSON-сводку.

### P1 — `agent_cost_usd` теряется при resume

После ручного исправления и resume compose marker был уже готов, поэтому новый
`HeyGenAgentRunner` вернул `agent_cost_usd=0.0`, хотя `agent.log` двух попыток
показывает фактические `$5.62767825`. Стоимость нельзя выводить только из
in-memory runner текущего процесса. Нужен durable cost artifact с накоплением
по попыткам и resume.

### P2 — setup dependency обнаруживается слишком поздно

На сервере не было
`~/.claude/skills/talking-head-recut/assets/vendor/gsap.min.js`; первый запуск
остановился на prepare до compose. Команда из ошибки:

```text
npx hyperframes@0.7.70 skills update talking-head-recut
```

фактически обновила/установила все 9 HyperFrames skills, а не только один.
Стоит добавить отдельный preflight/doctor и более точное описание side effects.

### P2 — имя npm-пакета в version probe

`npm view @heygen/hyperframes version` вернул 404. Фактически используемый
пакет — `hyperframes`; для него latest был `0.7.81`.

## Что не проверено этим архивом

- Реальный `trim_master_pauses` cut: WAV уже был чистым, `pause_cuts=[]`.
- Реальный `media-use resolve`: material list оказался пустым.
- Billing ledger: прогон был ручным и изолированным; `job.input.json` не
  переносился, чтобы не списывать тест с пользователя.
