# reels_factory — движок фабрики рилсов

Generic-порт движка `reels-saas` без игровой/Vael-специфики. Собирает вертикальный
рилс 1080×1920@30 из голоса ведущего (ElevenLabs) и видеоряда пользователя:
сценарий → одна master narration → alignment → визуальный HeyGen →
Revideo → QA-gate.

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

Необязательные поля аватара: `avatar.motion_prompt` (движения и жесты словами;
задан — перебивает ролевые промпты), `avatar.engine` (по умолчанию `avatar_iv`
для фото и `avatar_v` для двойника; есть `avatar_iii`), `avatar.resolution`
(`1080p` по умолчанию, можно `4k`), `avatar.expressiveness` (шлётся только с
`avatar_iv`).

### Master audio и Eleven v3

Новый путь включается `master_audio.enabled: true` либо
`RF_MASTER_AUDIO_ENABLED=1`. До отдельного production rollout default —
`false`; legacy-путь остаётся rollback-вариантом.

```yaml
master_audio:
  enabled: false
tts:
  model_id: eleven_v3
  stability: 0.5              # Natural; 0=Creative, 1=Robust
  # seed: 42                  # best-effort, не гарантия идентичного результата
  apply_text_normalization: auto
  output_format: mp3_44100_128
  pronunciation_dictionary_locators: []
```

Master path делает один `POST /v1/text-to-speech/{voice_id}/with-timestamps`,
сохраняет provider MP3, PCM WAV, original character alignment, нормализованные
word timings и manifest. Whisper остаётся для входящих пользовательских медиа и
legacy/fallback, но не подменяет утверждённый текст после TTS.

Для Eleven v3 намеренно передаётся только `stability`. Параметры `speed`,
`similarity_boost` и `use_speaker_boost` этой моделью не поддерживаются;
style exaggeration не передаётся, чтобы не снижать стабильность. Эмоции, темп и
паузы управляются пунктуацией и audio tags (`[curious]`, `[excited]`,
`[whispers]`, `[laughs]`, `[sighs]`) внутри текста, который видит и утверждает
пользователь. SSML `<break>` v3 не поддерживает.

Лимит v3 — 5000 символов. Движок проверяет его до HTTP и не начинает частично
оплаченную генерацию. Наш сценарный лимит значительно ниже; request stitching
для v3 не поддерживается, поэтому narration генерируется одним запросом.

### Пластика по ролям

Без своего `motion_prompt` движок берёт промпт под роль блока
(`MOTION_PROMPT_BY_ROLE`): хук — энергичное открытие с наклоном к камере,
development — объясняющие жесты, payoff — спокойный вывод, cta — прямое
обращение с открытой ладонью. Один промпт на весь ролик давал ровную
«дикторскую» подачу.

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
python -m reels_factory make   --workdir demo1 --broll <url|file> --offset 30
python -m reels_factory make   --workdir demo1 --broll <url|file> --broll-plan plan.json
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

- **split** — аватар-ведущий от HeyGen сверху (1080×672) + видеоряд снизу
  (1080×1248); в master-path HeyGen — беззвучный визуальный слой.
- **fullscreen** — видеоряд на весь кадр, голос ведущего за кадром (только TTS,
  HeyGen не рендерится — вдвое дешевле).
- **avatar** — аватар-ведущий от HeyGen на весь кадр (1080×1920);
  в master-path речь идёт только из `voice_master.wav`;
  видеоряд опционален — вставки поверх аватара (`broll_plan` сегменты с
  `"insert": true`), либо вовсе без видеоряда.

## Telegram: очередь и изоляция jobs

Кнопка «Создать ролик» больше не запускает сборку внутри callback. Бот:

1. создаёт UUID `job_id`;
2. атомарно пишет утверждённый сценарий, `job.input.json` и immutable
   `build-config.yaml` в `work/jobs/<job_id>/`;
3. добавляет job в `work/jobs.sqlite3`;
4. один FIFO-worker забирает её транзакционным claim;
5. доставляет видео только при `qa_pass=true`.

Команда `/status` показывает durable-статус последней job. Повторное нажатие
«Создать ролик», пока у чата есть `queued`/`running` job, не создаёт вторую
платную сборку.

Все изменяемые данные Revideo находятся внутри job:

```text
work/jobs/<job_id>/
├── scenario.json
├── job.input.json
├── build-config.yaml
├── script.canonical.json
├── voice_master.mp3
├── voice_master.wav
├── alignment.characters.json
├── alignment.words.json
├── audio_manifest.json
├── voice_*.wav
├── avatar_*.mp4
├── reel.mp4
└── revideo/
    ├── src/tz.json
    ├── src/words.json
    ├── public/base.mp4
    ├── public/voice_master.wav
    ├── public/<broll>.mp4
    └── output/reel.mp4
```

Общими и read-only остаются код Revideo и `node_modules`. При старте queued
jobs продолжают выполняться. Job, которая имела статус `running` во время
рестарта, переводится в `interrupted` и **не повторяется автоматически**:
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
