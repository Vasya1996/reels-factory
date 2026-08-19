# reels_factory — движок фабрики рилсов

Generic-порт движка `reels-saas` без игровой/Vael-специфики. Собирает вертикальный
рилс 1080×1920@30 из голоса ведущего (ElevenLabs) и видеоряда пользователя:
сценарий → одна master narration → alignment → визуальный HeyGen →
HyperFrames → QA-gate.

## Установка

```bash
python -m venv .venv
.venv\Scripts\pip install -e .
```

**Системная зависимость:** ffmpeg/ffprobe в PATH (на Windows — фолбэк на winget-
сборку Gyan.FFmpeg). Проверка: `ffmpeg -version`.

## Конфиг

Читается из `factory/config.yaml` рабочей папки проекта (см. `load_config`).
Обязательные поля: `theme`, `format` (`split`|`fullscreen`|`avatar`),
`voice_id`, `persona.description`, `product.name`, `product.cta_phrase`; для
`split` и `avatar` — ещё аватар: либо `avatar.heygen_look_id` (Digital Twin,
качество выше), либо `avatar.heygen_asset_id` (фото-аватар).

Необязательные поля аватара: `avatar.motion_prompt`, `avatar.engine` (по
умолчанию `avatar_iv` для фото и `avatar_v` для двойника),
`avatar.resolution` (`1080p` по умолчанию, можно `4k`) и
`avatar.expressiveness`. По актуальной API-схеме HeyGen `motion_prompt` и
`expressiveness` относятся к Photo Avatar / Avatar IV и не отправляются в
Avatar V request.

### Master audio и Eleven Multilingual v2

Новый путь включается `master_audio.enabled: true` либо
`RF_MASTER_AUDIO_ENABLED=1`. До отдельного production rollout default —
`false`; legacy-путь остаётся rollback-вариантом.

```yaml
master_audio:
  enabled: false
tts:
  model_id: eleven_multilingual_v2
  speed: 1.1
  stability: 0.2
  similarity_boost: 0.55
  style: 0.5
  use_speaker_boost: false
  # seed: 42                  # best-effort, не гарантия идентичного результата
  apply_text_normalization: auto
  output_format: mp3_44100_128
  pronunciation_dictionary_locators: []
```

Master path делает один `POST /v1/text-to-speech/{voice_id}/with-timestamps`,
сохраняет provider MP3, PCM WAV, original character alignment, нормализованные
word timings и manifest. Whisper остаётся для входящих пользовательских медиа и
legacy/fallback, но не подменяет утверждённый текст после TTS.

Параметры Multilingual v2 зафиксированы по контрольному русскому клону.
Эмоциональные v3 audio tags в текст не добавляются. Лимит модели — 10 000
символов; движок проверяет его до HTTP. Наш сценарный лимит значительно ниже,
поэтому narration генерируется одним запросом.

### Canonical edit plan и пластика по фразам

До TTS и HeyGen движок создаёт единственный versioned `edit_plan.json`.
Документ фиксирует stable phrase IDs и character ranges, `visual_intent`,
`coverage` (`avatar|full_broll|hyperframes|mixed`), выбранный asset с
confidence/duration, estimated timing, fallback и `avatar_performance`.
Детерминированный validator проверяет существование и длину assets, hook/CTA,
не более 10 секунд без лица и безопасность HeyGen skip. После master alignment
меняются только exact timings; если asset стал коротким или окно нарушило
лимит, это записывается как явная revision с fallback на avatar.

Каждая phrase уже содержит `expressiveness: low|medium|high` и короткий
английский `motion_prompt`. Без LLM используются консервативные ролевые
defaults. Опциональный анализ включается так:

```yaml
edit_plan:
  performance_llm:
    enabled: true
    timeout_s: 600
```

Модель обязана вернуть рекомендацию для каждого phrase ID. Явный
`avatar.motion_prompt`/`avatar.expressiveness` имеет приоритет. Motion prompt
описывает одно видимое движение и необязательную эмоцию, максимум двумя
короткими частями; camera/scene/props/walking/background/lighting/timing
validator отклоняет.

При `master_audio.enabled + avatar_islands.enabled` переходный block-by-block
контракт больше не используется. Per-phrase рекомендации становятся
directorial intent для адаптивных performance shots. Совместимые соседние
фразы объединяются, а hook/CTA, `low ↔ high`, B-roll/HyperFrames и максимум
18 секунд создают границу. Это применяет значимые смены подачи, не разрезая
аватар на клип для каждого предложения.
API reference: https://developers.heygen.com/reference/create-video; prompt
guide: https://help.heygen.com/en/articles/12805098-fine-tune-avatar-gestures-and-movements-with-custom-motion-prompts-avatar-iv-v.

### Photo Avatar IV islands

Stage 3 включается только вместе с master audio и до production rollout
остаётся выключенным:

```yaml
master_audio:
  enabled: true
avatar_islands:
  enabled: true
  handle_seconds: 0.2
  min_request_seconds: 3.0
  target_shot_seconds: 10.0
  max_shot_seconds: 18.0
  max_shots_per_30_seconds: 5
  max_parallel: 2
```

Этот путь намеренно поддерживает только Photo Avatar IV по
`avatar.heygen_asset_id`; `heygen_look_id`/Avatar V отклоняется до платных
стадий. Из final edit plan создаются производные `avatar_render_plan.json`
и `avatar_render_manifest.json`. HeyGen получает только видимые islands,
сборщик trim-ит handles на exact master timeline и удаляет provider audio.
Content-addressed cache применяется ко всем shots. Подробный контракт и
офлайн-таймлайны 30/60/90: `docs/AVATAR-ISLANDS.md`.

### Фото-аватар

Качество упирается в исходное фото: вертикальный кадр 9:16, поясной план с
руками, взгляд в объектив, мягкий фронтальный свет и **улыбка с открытыми
зубами** — с закрытым ртом движок рисует чужие зубы. Фон остаётся тот же, что
на фото (`background` закреплён тем же ассетом), сцена не уезжает.

### Digital Twin вместо фото

Фото-аватар не видел рта говорящего — зубы и артикуляцию он домысливает, и это
читается как «дешёвый ИИ». Двойник обучается на видео, где человек говорит:

```python
from reels_factory.twin import TwinClient
look_id = TwinClient().create_from_video("Имя", "training.mp4", "consent.mp4")
```

`look_id` кладём в `avatar.heygen_look_id` (или env `HEYGEN_LOOK_ID`) — дальше
движок сам рендерит на Avatar V. Обучающее видео: от 2 минут, от 720p, одно
чётко видимое лицо, человек говорит вслух и улыбается (иначе зубы снова
угаданные). Consent-видео: человек произносит формулу HeyGen из
`twin.CONSENT_STATEMENT` — без согласия рендер не стартует.

## Монтажный слой (edit)

Всё выключено по умолчанию — включается флагом в `config.yaml`, откатывается им же:

```yaml
edit:
  jump_cuts: true   # вырезать паузы внутри фрагментов (нужен auto-editor)
  grade: true       # единый цвет на аватар и вставки
  grain: true       # микро-зерно: снимает стерильность генерации
```

Джамп-каты применяются к фрагментам ДО сборки, поэтому `retime_scenario`
считает сетку уже по подрезанным длительностям, и субтитры со вставками встают
на новые времена сами. Резать умеет `auto-editor` (`pip install auto-editor`).

Проверить шаги на своём ролике, без конфига и без HeyGen:

```bash
python -m reels_factory edit --input мой.mp4 --output out.mp4 --jump-cuts --grade --grain
```

## CLI

```bash
python -m reels_factory script --workdir demo1            # сценарий -> scenario.json
python -m reels_factory make   --workdir demo1            # только format: avatar
python -m reels_factory verify --workdir demo1            # перепроверить 7 гейтов
```

Весь вывод — JSON (`ensure_ascii=False`). Exit-код `2` = провал QA-гейта.

## CLI: пути сценария

- `script-text --workdir W (--text-file F | --audio F)` — путь «дословно»:
  текст пользователя без правок (только фонетика для озвучки) -> scenario.json.
- `ideas --workdir W (--source-file F | --audio F)` — 2-3 виральные идеи из
  сырья -> ideas.json.
- `script-idea --workdir W --idea-file F` — генерация по выбранной идее +
  хуманизация + LLM-судья (exit 2 = судья не принял, см. verdict.issues).
- `script ...` — классический research-цикл (без изменений).

В Telegram язык выбирается **для каждого нового ролика**. После `/start` и
`/new` бот сначала предлагает `ru` или `kk`, затем спрашивает: готовый сценарий
или создать новый. Выбранный язык применяется к идеям, генерации,
хуманизации, судье, расшифровке, master audio и субтитрам.

Голос не считается мультиязычным. В профиле пользователя хранится карта
`voices` с отдельным `voice_id` для каждого языка. Если русский голос уже
есть, а для нового ролика выбран казахский и `voices.kk` отсутствует, бот
просит записать казахский голос. Русский клон при этом сохраняется. При
возврате к русскому ролику бот снова предлагает прежний русский голос.

Готовый текст не переключает язык автоматически. Консервативный локальный
детектор только блокирует уверенное несовпадение с языком текущего ролика;
неоднозначный текст обрабатывается на выбранном пользователем языке.

## Форматы

- **split** и **fullscreen** — оставлены в схеме конфига и в опроснике
  установки, но команда `make` для них честно отказывает: источника
  непрерывного видеоряда под ними больше нет (см. `docs/archive/console-broll-workflow.md`
  в ветке `archive/console-broll-workflow`).
- **avatar** — единственный рабочий формат. Аватар-ведущий от HeyGen на весь
  кадр (1080×1920); в master-path речь идёт только из `voice_master.wav`;
  видеоряд опционален — вставки поверх аватара подбираются автоматически из
  локальной библиотеки клипов, либо вовсе без видеоряда. Ручной консольный
  план (`--broll-plan`) убран вместе с `--broll` — см. `docs/archive/console-broll-workflow.md`
  в ветке `archive/console-broll-workflow`.

## Telegram: очередь и изоляция jobs

Кнопка «Создать ролик» больше не запускает сборку внутри callback. Бот:

1. создаёт UUID `job_id`;
2. атомарно пишет утверждённый сценарий, `job.input.json` и immutable
   `build-config.yaml` в `work/jobs/<job_id>/`;
3. добавляет job в `work/jobs.sqlite3` на стадию `audio_queued`;
4. один FIFO-worker создаёт только ElevenLabs master audio и присылает MP3;
5. подтверждение переводит ту же job в render queue без повторного TTS;
6. при отказе бот принимает один Telegram voice со всем сценарием и использует
   его только для текущего ролика, не заменяя voice clone профиля;
7. видео доставляется только при `qa_pass=true`.

Команда `/status` показывает durable-статус последней job. Повторное нажатие
«Создать ролик», пока job создаёт/проверяет аудио, ждёт пользовательскую запись
или рендерится, не создаёт вторую платную сборку.

Все изменяемые данные сборки находятся внутри job:

```text
work/jobs/<job_id>/
├── scenario.json
├── job.input.json
├── build-config.yaml
├── audio.approved.json
├── audio/
│   ├── tts/
│   │   ├── script.canonical.json
│   │   ├── voice_master.mp3
│   │   ├── voice_master.wav
│   │   ├── alignment.characters.json
│   │   ├── alignment.words.json
│   │   └── audio_manifest.json
│   └── user/
│       ├── user_voice_source.ogg
│       ├── voice_master.wav
│       ├── alignment.words.json
│       └── audio_manifest.json
├── edit_plan.json
├── avatar_*.mp4
├── plan.json
├── storyboard.json
├── public/
├── reel.raw.mp4
└── reel.mp4
```

`audio.approved.json` хранит source, artifact directory и SHA-256 канонического
WAV. Render stage повторно проверяет hash и сценарий; без этого маркера bot-job
не может вызвать HeyGen.

Общими и read-only остаются код сборщика и `node_modules`. При старте queued
jobs продолжают выполняться. Job, которая имела статус `audio_running` или
`running` во время рестарта, переводится в `interrupted` и **не повторяется автоматически**:
до внедрения provider idempotency/job-id такой повтор мог бы дважды списать
деньги HeyGen или ElevenLabs.

Worker запускает `make --config <job>/build-config.yaml`, а не перечитывает
изменяемый профиль клиента. Поэтому queued job сохраняет исходные language и
voice_id, даже если пользователь уже начал следующий ролик на другом языке.

## Тесты

```bash
.venv\Scripts\python -m pytest -m "not slow"   # быстрые, без сети/ffmpeg/модели
.venv\Scripts\python -m pytest -m slow         # интеграционные (ffmpeg)
```

Ключи (env, для реальных прогонов): `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`,
`HEYGEN_API_KEY`, `HEYGEN_LOOK_ID` (двойник) или `HEYGEN_AVATAR_ID` (фото).
