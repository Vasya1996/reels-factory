# Revideo-рендер — апгрейд монтажного слоя

Code-first рендерер вертикальных рилсов на **Revideo** (форк Motion Canvas, Node/TS).
Заменяет ffmpeg/ASS-сборку (`compose.py` + `captions/stickers/zoom/transitions`)
богатым программируемым монтажом уровня монтажёра. GPU не нужен, рендер в
headless-Chromium + ffmpeg.

## Зачем (что умеет сверх текущего ffmpeg-слоя)

**Эффекты:**
- Субтитры-набор по словам (accumulate), шрифт Unbounded, позиция 40% от низа,
  полупрозрачные с тенью — «дорогой» вид.
- 4 стиля b-roll: картинка-в-картинке, сплит-скрин, фуллскрин, фон + летящие
  Fluent 3D иконки (частицы).
- Аватар в кружке/квадрате (вебка) с **автоцентровкой по лицу** (OpenCV,
  `detect_face.py`) и точным **липсинком** (плейхед привязан к времени сцены).
- Инфографика-бары (`chart_bars`) на тёмной подложке-бэкплейте.
- Fluent 3D эмодзи, чат-стикеры, CTA-эндкард.
- 7 типов зумов, whip / zoom-blur переходы, прогресс-бар, вотермарк, SFX.

**Правила монтажа (зашиты в движок, работают автоматически):**
- **Нет флеш-кадров:** между двумя полноэкранными оверлеями аватар не мелькает —
  держится общая подложка (порог `MIN_SHOT` = 1.2с).
- **Границы сегментов:** чанк субтитров не пересекает границу сегмента.
- **Зум-раз:** каждый тип зума не больше раза за ролик.
- **Бэкплейт:** любой полноэкранный оверлей поверх лица получает подложку.
- **Липсинк:** второй экземпляр видео (пузырь) стартует от текущего времени сцены.
- **Драматургия:** поля `beat`/`intensity` в плане (кривая насыщенности, а не ровный слой).

## Вход (контракт)

| Файл | Что это |
|------|---------|
| `src/tz.json` | План монтажа: сегменты по фразам с эффектами (аналог `editplan.py`) |
| `src/words.json` | Слова с таймкодами (из `transcribe.py` / Whisper / ElevenLabs) |
| `public/base.mp4` | Аватар с озвучкой (из `avatar.py` HeyGen) — **кладётся в runtime** |
| `public/broll_*.mp4` | Видеоряд (из `broll.py`) — **кладётся в runtime** |
| `public/emoji/*.png` | Fluent 3D иконки (в комплекте) |
| `public/*.wav` | SFX (в комплекте) |

Медиа (`*.mp4`) в git не коммитятся (см. `.gitignore`), их подаёт пайплайн.

## Запуск

```bash
cd revideo
npm install
# положить public/base.mp4 (+ public/broll_1.mp4 ...) и src/words.json, src/tz.json
node render.mjs        # -> output/reel_*.mp4  (1080x1920, 30fps, со звуком)
```

Требования: Node 20+, ffmpeg в PATH, интернет для шрифтов (Google Fonts `@import`
в `src/global.css`; для оффлайна — положить woff2 локально и заменить `@import`).

## Схема плана `tz.json`

Смотри `examples/tz_reels_v6.json` (полная раскладка с `broll_query`,
обоснованием и правилами) и `examples/tz_reels5_v4.json`. Формат каждого сегмента:

```json
{
  "id": 4, "start": 8.16, "end": 10.88, "phrase": "...",
  "beat": "explanation", "intensity": 2,
  "camera": { "type": "ken_burns" },
  "transition_in": "none",
  "effect": { "type": "broll", "style": "pip", "broll_query": "...", "src": null },
  "caption": "top"
}
```

## Стык с Python-движком (ВСТРОЕНО)

Revideo — единственный рендер-слой. Пайплайн (`pipeline.py`) вызывает его вместо
ffmpeg-сборки:

```
scenario → voice(ElevenLabs) → avatar(HeyGen) → [assemble_revideo] → reel.mp4 → verify.py
```

Реализовано:
- `reels_factory/revideo_adapter.py` — `plan_to_tz(timed, broll_segments, config)`:
  ретаймленные блоки (роли hook/development/payoff/cta) → сегменты tz с эффектами
  и ротацией зумов.
- `reels_factory/revideo_render.py` — `assemble_revideo(...)`: drop-in замена
  `compose.assemble` с тем же контрактом `{mp4, timed_scenario, words_fixed}`.
  Переиспользует `_concat_avatars` (склейка аватара → `base.mp4`),
  `retime_scenario`, `_default_transcribe`, `apply_caption_fixes`; кладёт
  `tz.json`/`words.json`/`base.mp4` в модуль и зовёт `node render.mjs`.
- `pipeline.py` — `assemble_fn` по умолчанию = `assemble_revideo`. Переключателя нет.
- Выход рендера задаётся из Python через env `RF_OUTFILE`.

Проверено: план пайплайна (ретаймленные блоки) → адаптер → tz → `node render.mjs`
даёт корректный ролик 1080×1920@30 со звуком (лицо на dev-блоках с ротацией
зумов, payoff = фуллскрин-видеоряд + аватар-пузырь, CTA-эндкард, accumulate-
субтитры). Полный E2E с генерацией голоса/аватара требует ключей HeyGen/ElevenLabs.

Апстрим-модули (авто-раскладка из сценария и семантический подбор b-roll) —
`docs/TZ_pipeline_v6.md`.

Движок самодостаточен: гоняется отдельно на готовых `tz.json` + `words.json` +
`public/base.mp4` (`node render.mjs`).
