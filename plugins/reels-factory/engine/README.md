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
`split` и `avatar` — ещё аватар: либо `avatar.heygen_look_id` (Digital Twin,
качество выше), либо `avatar.heygen_asset_id` (фото-аватар).

Необязательные поля аватара: `avatar.motion_prompt` (движения и жесты словами),
`avatar.engine` (`avatar_v` по умолчанию для двойника, `avatar_iv`, `avatar_iii`),
`avatar.resolution` (`1080p` по умолчанию), `avatar.expressiveness` (только для
`avatar_iv`).

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

## CLI

```bash
python -m reels_factory script --workdir demo1            # сценарий -> scenario.json
python -m reels_factory make   --workdir demo1 --broll <url|file> --offset 30
python -m reels_factory make   --workdir demo1 --broll <url|file> --broll-plan plan.json
python -m reels_factory verify --workdir demo1            # перепроверить 7 гейтов
```

Весь вывод — JSON (`ensure_ascii=False`). Exit-код `2` = провал QA-гейта.

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
`HEYGEN_API_KEY`, `HEYGEN_LOOK_ID` (двойник) или `HEYGEN_AVATAR_ID` (фото).
