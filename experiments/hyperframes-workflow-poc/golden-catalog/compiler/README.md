# Компилятор edit_plan → golden-блоки → HyperFrames

## Границы ответственности (важно)

**Рендерер HyperFrames не модифицируется.** Разделение такое:

```
edit_plan.timed.json + word-timings.json     ← творческое решение (1 вызов LLM)
              │
              ▼
   ЭТОТ КОМПИЛЯТОР (compile.mjs + blocks.mjs)  ← наш слой, детерминированный
              │  сцены → golden-блоки, слова → тайминги tweens
              ▼
   build/index.html                            ← валидная standalone-композиция:
     root[data-composition-id][data-duration]     клипы .clip[data-start/duration/track]
     + ОДИН paused GSAP timeline (__timelines)    + локальный gsap, без сети
              │
              ▼
   HyperFrames CLI (lint / check / render)     ← их код, как есть, 0 правок
```

HyperFrames умеет превращать готовую HTML-композицию в MP4, но не знает про
edit_plan. Компилятор — недостающий переходник: «что и когда показать» → «HTML,
который их рендерер понимает».

## Файлы

- `compile.mjs` — читает план и тайминги, маппит сцены на блоки, генерирует
  `build/index.html` (композиция) и `build/preview.html` (аниматик с плеером).
- `blocks.mjs` — шаблоны golden-блоков. Анимации объявляются атрибутами
  `data-anim="word|pop|stamp|card|strike|tick|fade|hl"` + `data-at="<сек>"`;
  таймлайн-строитель в композиции превращает их в tweens. Easing/длительности —
  из design-tokens v2.
- Замены отклонённых свайпом id плана (concept_nodes, persona_card,
  value_layers, avatar_broll_split, social_outro) на принятые блоки — таблица
  `SCENE_MAP` в compile.mjs.

## Запуск

```bash
node compiler/compile.mjs
# затем: http://localhost:4180/golden-catalog/build/preview.html
```

## Что ещё не подключено (следующие шаги)

1. **Аватар**: клипы содержат dashed-плейсхолдеры. Нужен точный avatar.mp4
   (см. handoff §8: не найден, новую генерацию не запускать). Подстановка:
   `<video>` в слот, HyperFrames сам владеет playback.
2. **Master audio**: voice_master.mp3 лежит на сервере reels-factory
   (/root/reels-workspace/...), локально его нет → превью беззвучное.
   В композиции появится как `<audio>` на отдельном треке.
3. **Рендер в MP4**: на машине с установленным HyperFrames CLI:
   `npx hyperframes lint && npx hyperframes check && npx hyperframes render`.
4. **SFX intents** из плана пока игнорируются.
