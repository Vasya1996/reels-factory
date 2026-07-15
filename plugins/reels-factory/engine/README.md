# reels_factory — движок фабрики рилсов

Generic-порт движка `reels-saas` без игровой/Vael-специфики. Собирает вертикальный
рилс 1080×1920@30 из голоса блогерши (ElevenLabs) и видеоряда пользователя:
сценарий → TTS → (split: аватар HeyGen) → сборка → 7 QA-гейтов.

## Установка

```bash
python -m venv .venv
.venv\Scripts\pip install -e .
```

**Системная зависимость:** ffmpeg/ffprobe в PATH (на Windows — фолбэк на winget-
сборку Gyan.FFmpeg). Проверка: `ffmpeg -version`.

## Конфиг

Читается из `factory/config.yaml` рабочей папки проекта (см. `load_config`).
Обязательные поля: `theme`, `format` (`split`|`fullscreen`), `voice_id`,
`product.name`, `product.cta_phrase`; для `split` — ещё `avatar.heygen_asset_id`.

## CLI

```bash
python -m reels_factory script --workdir demo1            # сценарий -> scenario.json
python -m reels_factory make   --workdir demo1 --broll <url|file> --offset 30
python -m reels_factory make   --workdir demo1 --broll <url|file> --broll-plan plan.json
python -m reels_factory verify --workdir demo1            # перепроверить 7 гейтов
```

Весь вывод — JSON (`ensure_ascii=False`). Exit-код `2` = провал QA-гейта.

## Форматы

- **split** — аватар-блогерша от HeyGen сверху (1080×672) + видеоряд снизу
  (1080×1248), голос вшит в аватар.
- **fullscreen** — видеоряд на весь кадр, голос блогерши за кадром (только TTS,
  HeyGen не рендерится — вдвое дешевле).

## Тесты

```bash
.venv\Scripts\python -m pytest -m "not slow"   # быстрые, без сети/ffmpeg/модели
.venv\Scripts\python -m pytest -m slow         # интеграционные (ffmpeg)
```

Ключи (env, для реальных прогонов): `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`,
`HEYGEN_API_KEY`, `HEYGEN_AVATAR_ID`.
