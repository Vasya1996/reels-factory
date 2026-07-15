---
name: setup
description: Мастер первичной настройки фабрики рилсов — проверяет python3.11+/ffmpeg, ставит движок в venv рабочей папки, запрашивает ключи HeyGen и ElevenLabs, загружает фото аватара в HeyGen и выбирает голос ElevenLabs, интервьюирует про тему/нишу/формат/продукт, собирает factory/config.yaml и шаблоны продуктового цикла, прогоняет смоук-тест. Use when the user runs `/reels-factory:setup` — это ПЕРВЫЙ запуск фабрики после установки плагина (до этого research/script/make/review работать не будут — нет конфига).
---

# Setup — мастер первого запуска

Всё, что ниже, — инструкции ДЛЯ ТЕБЯ (Claude), не для человека: ты сам
выполняешь команды и спрашиваешь у пользователя только то, что не можешь
узнать сам (ключи, фото, тему, продукт). Не показывай пользователю голый
список команд вместо действия — выполняй шаги по порядку. У каждого шага
есть критерий «шаг пройден»; не переходи к следующему, пока критерий не
выполнен. При провале шага — объясни пользователю понятную причину и
конкретное действие для починки, а не сырой трейсбек.

Важная техническая особенность инструмента команд: КАЖДЫЙ вызов
shell-команды (Bash/PowerShell) — это НОВЫЙ процесс, переменные окружения
(`$env:...`), заданные в одном вызове, НЕ переживают до следующего вызова.
Поэтому там, где ниже нужен ключ API, задавай его В ТОМ ЖЕ вызове, что и
саму команду (одна команда через `;`), не полагайся на ранее выставленный
`$env:`.

## Шаг 1. Python ≥3.11 и ffmpeg

```powershell
python --version
ffmpeg -version
```

- Python: версия должна быть ≥3.11. Если команда не найдена или версия
  ниже — попроси пользователя выполнить `winget install Python.Python.3.12`
  и сообщить, когда готово; после установки открой новый вызов (PATH
  подтянется в новом процессе) и проверь снова.
- ffmpeg: если `ffmpeg -version` не печатает `ffmpeg version ...` —
  попроси пользователя выполнить `winget install Gyan.FFmpeg`. Даже если
  PATH в текущей сессии не обновится сразу, это не блокер: движок сам
  находит ffmpeg по фолбэку на путь winget-установки (см.
  `engine/src/reels_factory/config.py::_resolve` — сначала PATH, потом
  глоб по `Gyan.FFmpeg*/**/ffmpeg.exe`). Реальную проверку с фолбэком
  сделаешь на шаге 9.

Критерий: `python --version` печатает ≥3.11.x. Если ffmpeg не нашёлся в
PATH — зафиксируй и перепроверь на шаге 9 через сам движок, не блокируй
установку из-за одного PATH.

## Шаг 2. Рабочая папка = ТЕКУЩАЯ папка пользователя

ВАЖНО (см. `engine/src/reels_factory/config.py`): движок вычисляет
`WORK_ROOT` и `FACTORY_DIR` как `Path.cwd() / "work"` и
`Path.cwd() / "factory"` — то есть **привязан к текущей рабочей директории
процесса**. Значит:

- Отдельную папку для проекта создавать не нужно — рабочая папка это ТЕКУЩАЯ
  папка, в которой пользователь открыл Claude Code для этого проекта (cwd
  сессии).
- **Все** команды движка (`python -m reels_factory ...`, а также venv и
  `pip install`) ниже и во всех последующих скиллах (research/script/
  make/review) нужно запускать ИЗ КОРНЯ этой рабочей папки — не из папки
  плагина, не из случайной поддиректории. Если ты когда-либо делаешь `cd`
  куда-то ещё в рамках этой сессии — обязательно вернись в корень рабочей
  папки перед следующей командой движка.

Критерий: ты знаешь абсолютный путь рабочей папки (текущий cwd) и явно
используешь его как рабочую директорию для всех команд ниже.

## Шаг 3. venv + установка движка

```powershell
python -m venv .venv
.venv\Scripts\pip install -e "${CLAUDE_PLUGIN_ROOT}/engine"
```

`${CLAUDE_PLUGIN_ROOT}` подставляется средой Claude Code автоматически в
любом месте текста скилла — писать его буквально, не пытаться развернуть
через `$env:`.

Критерий: команда завершилась без ошибок, и

```powershell
.venv\Scripts\python.exe -c "import reels_factory; print(reels_factory.__version__)"
```

печатает версию пакета (например `0.1.0`).

## Шаг 4. Ключи HeyGen и ElevenLabs

Спроси у пользователя в чате два ключа:
- `HEYGEN_API_KEY` (HeyGen → Settings → API)
- `ELEVENLABS_API_KEY` (ElevenLabs → Profile → API Keys)

Не проси прислать их в файл и не сохраняй ключи никуда, кроме переменных
окружения — они не должны попасть ни в `factory/config.yaml`, ни в git.

Сохрани оба ключа персистентно (для будущих сессий) И одновременно
подставляй их явно во все последующие команды этого же запуска setup
(см. заметку про «новый процесс на каждый вызов» в начале файла):

```powershell
[System.Environment]::SetEnvironmentVariable("HEYGEN_API_KEY", "<ключ>", "User")
[System.Environment]::SetEnvironmentVariable("ELEVENLABS_API_KEY", "<ключ>", "User")
```

Критерий: обе команды `SetEnvironmentVariable` выполнены без ошибок; в
шагах 5/6/9 ключ передаётся В ТОЙ ЖЕ команде, где он нужен (например
`$env:HEYGEN_API_KEY="<ключ>"; .venv\Scripts\python.exe -c "..."`).

## Шаг 5. Аватар: фото → HeyGen v3 asset

Спроси у пользователя путь(и) к фото для аватара-блогерши.

Правило кадра (важно для формата `split` — верхняя часть экрана 1080×672):
- соотношение сторон фото близкое к 1080×672 НЕ обязательно — движок сам
  кадрирует под нужный размер (`scale=...:force_original_aspect_ratio=increase,
  crop=...`, см. `compose.py`), HeyGen генерирует видео под исходный размер
  фото (`avatar.py`: `_generate_v3`), а финальный кроп уже делает ffmpeg;
- лицо держи **по центру кадра** — при кропе под 1080×672 края могут
  срезаться, особенно если фото сильно шире или уже целевого соотношения;
- взгляд — **«в монитор»** (прямо в камеру), т.к. в split-формате аватар
  занимает верх экрана и должен визуально обращаться к зрителю.

Загрузи фото в HeyGen `/v3/assets` (тот же endpoint, что использует
`avatar.py` для аудио — генерический аплоад ассетов, поддерживает
png/jpeg) и получи `asset_id`:

```powershell
$env:HEYGEN_API_KEY="<ключ>"; .venv\Scripts\python.exe -c "import os,sys,requests; from reels_factory.avatar import UPLOAD_URL; p=r'<путь к фото>'; k=os.environ['HEYGEN_API_KEY']; r=requests.post(UPLOAD_URL, headers={'X-Api-Key':k}, files={'file':(os.path.basename(p), open(p,'rb').read())}, timeout=60); r.raise_for_status(); print(r.json()['data']['asset_id'])"
```

Если пользователь дал несколько фото — сделай так на каждое и спроси,
какое использовать по умолчанию (можно оставить остальные в памяти как
запасные, но в `config.yaml` идёт только один `heygen_asset_id`).

Критерий: команда напечатала непустую строку `asset_id` (без трейсбека
requests — при 401/403 сообщи пользователю, что ключ неверный, и вернись
к шагу 4).

## Шаг 6. Голос: список русских голосов ElevenLabs

```powershell
$env:ELEVENLABS_API_KEY="<ключ>"; .venv\Scripts\python.exe -c "import os,requests; k=os.environ['ELEVENLABS_API_KEY']; r=requests.get('https://api.elevenlabs.io/v2/voices', headers={'xi-api-key':k}, params={'page_size':100}, timeout=60); r.raise_for_status(); vs=r.json()['voices']; ru=[v for v in vs if any((l.get('language')=='ru') for l in (v.get('verified_languages') or []))]; pick=ru or vs; [print(v['voice_id'], '-', v['name']) for v in pick[:15]]"
```

Из напечатанного списка выбери 3-5 голосов и предложи пользователю в чате
в формате «имя — voice_id» (если явно русских голосов (`ru` в
`verified_languages`) не нашлось — предупреди, что показываешь
мультиязычные голоса ElevenLabs, они всё равно озвучивают русский текст
через модель `eleven_v3`, но акцент стоит проверить на слух — тестовый
прогон будет на шаге 9). Запиши выбранный `voice_id`.

Критерий: у тебя есть конкретный `voice_id`, подтверждённый пользователем.

## Шаг 7. Интервью: тема, ниша, формат, продукт

Спроси у пользователя (по одному вопросу за раз, не вываливай всё списком):

1. **Тема** рилсов (`theme`) — про что ролики.
2. Как тема **звучит в речи** (`theme_spoken`), если отличается от
   написания (склонения/сокращения) — можно пропустить, тогда равно theme.
3. **Ниша/ключевики** (`niche_keywords`) — по чему искать виральные ролики
   на этапе research (несколько фраз).
4. **Формат** — `split` (аватар сверху + видеоряд снизу, дороже) или
   `fullscreen` (видеоряд на весь кадр, голос за кадром, вдвое дешевле —
   без рендера HeyGen).
5. **Продукт**: имя (`product.name`), легенда (`product.legend` — контекст
   для сценария, не пересказывается зрителю в лоб), CTA-фраза
   (`product.cta_phrase` — ДОСЛОВНО, она войдёт в реплику один в один),
   варианты написания бренда/терминов для субтитров
   (`product.brand_captions` — что мог услышать Whisper вместо каждого
   термина; формат — объект `отображение: [варианты]`, НЕ список).

Критерий: собраны все обязательные поля (theme, format, product.name,
product.cta_phrase — как в `load_config`), плюс из шагов 5/6
`avatar.heygen_asset_id` (обязателен для `format: split`) и `voice_id`.

## Шаг 8. Собрать factory/config.yaml + скопировать шаблоны

```powershell
New-Item -ItemType Directory -Force factory | Out-Null
```

Прочитай `${CLAUDE_PLUGIN_ROOT}/templates/config.example.yaml`, подставь
собранные на шагах 4-7 значения (ключи API в файл НЕ пиши — они только в
env) и запиши результат в `factory/config.yaml` рабочей папки.

Скопируй шаблоны продуктового цикла в `factory/`, подставив тему в
заголовок:
- `${CLAUDE_PLUGIN_ROOT}/templates/hypotheses-template.md` →
  `factory/hypotheses.md`
- `${CLAUDE_PLUGIN_ROOT}/templates/playbook-template.md` →
  `factory/playbook.md`
- `${CLAUDE_PLUGIN_ROOT}/templates/analysis-template.md` →
  `factory/analysis-<тема-слагом>.md` (тема в нижнем регистре, пробелы →
  дефисы; например тема «кофе дома» → `factory/analysis-kofe-doma.md` или
  транслит на твоё усмотрение — главное, стабильно и без пробелов)

Критерий: `factory/config.yaml` существует и проходит валидацию:

```powershell
.venv\Scripts\python.exe -c "from reels_factory.config import load_config; print(load_config()['theme'])"
```

печатает тему без ошибки `ConfigError`; в `factory/` лежат `hypotheses.md`,
`playbook.md` и `analysis-<тема>.md`.

## Шаг 9. Смоук-тест

Проверь, что CLI движка вообще запускается:

```powershell
.venv\Scripts\python.exe -m reels_factory verify --help
```

Критерий: печатается argparse-справка (`usage: reels_factory verify ...`),
без трейсбека.

Проверь, что ключ ElevenLabs реально рабочий — короткий TTS на 3 слова
(это стоит копейки):

```powershell
New-Item -ItemType Directory -Force work | Out-Null
$env:ELEVENLABS_API_KEY="<ключ>"; .venv\Scripts\python.exe -c "from reels_factory.tts import synth_voice; synth_voice('привет, это тест', 'work/_smoke.wav', voice_id='<voice_id>'); print('ok')"
```

Критерий: команда напечатала `ok` без исключения, и файл
`work/_smoke.wav` существует и весит больше 0 байт:

```powershell
(Get-Item work/_smoke.wav).Length
```

Если 401/403 — ключ неверный, вернись к шагу 4. Удали `work/_smoke.wav`
после проверки (это тестовый мусор, не часть продукта).

HeyGen на этом шаге отдельно не гоняем — `asset_id` уже подтверждён
успешным ответом на шаге 5 (реальная генерация видео произойдёт на первом
`/reels-factory:make`).

## Шаг 10. Финал

Покажи пользователю сводку собранного конфига (без ключей API — только
факт «ключи сохранены»): тема, формат, продукт, voice_id, heygen_asset_id,
пути к шаблонам в `factory/`.

Сообщи следующий шаг: `/reels-factory:research` — разведка темы и подбор
гипотез перед первым сценарием.
