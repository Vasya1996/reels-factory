# reels_factory — движок фабрики рилсов

Generic-порт движка `reels-saas` без игровой/Vael-специфики. Собирает вертикальный
рилс 1080×1920@30 из голоса ведущего (ElevenLabs) и видеоряда пользователя:
сценарий → TTS → (split/avatar: аватар HeyGen) → сборка → 7 QA-гейтов.

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
`split` и `avatar` — ещё `avatar.heygen_asset_id`.

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

Язык всех шагов — `language` из factory/config.yaml (ru по умолчанию, kk
поддержан насквозь: идеи, генерация, хуманизация, судья, расшифровка).

## Форматы

- **split** — аватар-ведущий от HeyGen сверху (1080×672) + видеоряд снизу
  (1080×1248), голос вшит в аватар.
- **fullscreen** — видеоряд на весь кадр, голос ведущего за кадром (только TTS,
  HeyGen не рендерится — вдвое дешевле).
- **avatar** — аватар-ведущий от HeyGen на весь кадр (1080×1920), голос вшит;
  видеоряд опционален — вставки поверх аватара (`broll_plan` сегменты с
  `"insert": true`), либо вовсе без видеоряда.

## Тесты

```bash
.venv\Scripts\python -m pytest -m "not slow"   # быстрые, без сети/ffmpeg/модели
.venv\Scripts\python -m pytest -m slow         # интеграционные (ffmpeg)
```

Ключи (env, для реальных прогонов): `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`,
`HEYGEN_API_KEY`, `HEYGEN_AVATAR_ID`.
