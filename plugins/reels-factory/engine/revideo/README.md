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

## Стык с Python-движком (следующий шаг wiring)

Их `editplan.py` и наш `tz.json` — одна и та же сущность (план монтажа). Нужен
тонкий адаптер `editplan (dict) → tz.json`, дальше `node render.mjs`, дальше
`verify.py` (QA-гейты остаются). Апстрим-модули (авто-раскладка из сценария и
семантический подбор b-roll) описаны в `docs/TZ_pipeline_v6.md`.

```
scenario → words.json → editplan(dict)
        → [adapter] → tz.json → node render.mjs → reel.mp4 → verify.py
```

Движок рендера самодостаточен: его можно гонять отдельно от Python-пайплайна на
готовых `tz.json` + `words.json` + `base.mp4`.
