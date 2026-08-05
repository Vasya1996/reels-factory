# ТЗ Stage 03 — собрать тестовый ролик из `edit_plan` через HyperFrames

## 0. Роль исполнителя

Ты — технический исполнитель. Творческий монтажный план уже принят как вход.
Не придумывай новый сценарий, новую раскадровку, новые catalog IDs или другую
архитектуру. Твоя задача — детерминированно собрать и отрендерить один черновой
MP4 по существующему `edit_plan`.

Пользователь заранее разрешил **один локальный draft render** для проверки.
Публикация, production deploy и high-quality final render не разрешены.

## 1. Рабочее место и границы

Репозиторий:

```text
C:\Users\Asus\Documents\personal_ai\projects\content_factory\reels-factory-hyperframes-workflow-poc
```

Ветка:

```text
codex/hyperframes-workflow-poc
```

Работай в этой ветке. Не создавай и не переключай ветки. Не делай commit, push,
PR, deploy или публикацию.

Не изменяй Stage 01 и Stage 02. Новый результат складывай только в:

```text
experiments\hyperframes-workflow-poc\stage-03-render\
```

Существующие untracked-файлы принадлежат пользователю. Не удаляй и не
перезаписывай их.

## 2. Обязательное чтение до изменений

Сначала полностью прочитай:

1. `AGENTS.md` в корне репозитория;
2. `docs/HYPERFRAMES-WORKFLOW-POC-HANDOFF.md`;
3. это ТЗ;
4. обязательный skill `hyperframes`;
5. затем `general-video`, `hyperframes-core`, `hyperframes-animation`,
   `hyperframes-keyframes`, `hyperframes-registry`, `hyperframes-cli`,
   `hyperframes-creative` и `media-use` — только с нужными references для
   композиции, локальных media, seek-safe GSAP, check/snapshot/render.

Не пересказывай skills пользователю. Примени их технические требования.

## 3. Запрещено

- Никаких дополнительных LLM/API-вызовов.
- Не вызывать ElevenLabs, HeyGen, image generation, B-roll providers или
  платные/внешние media API.
- Не менять текст, word ranges, длительность 42,32 секунды или порядок 13 сцен.
- Не заменять локальные avatar clips статичным фото.
- Не использовать avatar-видео из других роликов.
- Не использовать `adapt_required` элементы напрямую.
- Не писать случайный декоративный HTML вместо catalog contracts.
- Никаких runtime network fetches, CDN fonts/assets, часов, autoplay timers,
  бесконечных repeat или unseeded randomness.
- Не оставлять пользователю только код/preview. Обязательный результат — MP4.

## 4. Входы

### 4.1. Утверждённый монтажный план

```text
experiments\hyperframes-workflow-poc\stage-02-edit-plan\edit_plan.draft.json
experiments\hyperframes-workflow-poc\stage-02-edit-plan\edit_plan.timed.json
experiments\hyperframes-workflow-poc\stage-02-edit-plan\reports\human-review.md
experiments\hyperframes-workflow-poc\stage-02-edit-plan\reports\plan-validation.json
experiments\hyperframes-workflow-poc\stage-02-edit-plan\inputs\word-timings.json
experiments\hyperframes-workflow-poc\stage-02-edit-plan\inputs\project-constraints.json
```

Перед сборкой запусти существующий валидатор:

```powershell
node scripts\validate-and-present.mjs
```

Рабочая директория команды:

```text
experiments\hyperframes-workflow-poc\stage-02-edit-plan
```

Ожидается `PASS`, 13 сцен, 100/100 слов, без ошибок и предупреждений.

### 4.2. Master audio

Используй только этот WAV как единственную финальную голосовую дорожку:

```text
C:\Users\Asus\Documents\personal_ai\projects\content_factory\work\diagnostics\ivc-v3-scenario-20260726T182834Z\eleven\voice_master.wav
```

Ожидаемая длительность: `42.320` секунды.

Сценарий и alignment:

```text
experiments\hyperframes-workflow-poc\stage-02-edit-plan\inputs\audio\scenario.json
experiments\hyperframes-workflow-poc\stage-02-edit-plan\inputs\audio\alignment.json
```

Не генерируй и не ретаймь master audio.

### 4.3. Четыре исходных avatar island

Порядок хронологический и задан именами:

```text
C:\Users\Asus\Downloads\Продажи\1.mp4
C:\Users\Asus\Downloads\Продажи\2.mp4
C:\Users\Asus\Downloads\Продажи\3.mp4
C:\Users\Asus\Downloads\Продажи\4.mp4
```

Проверенные характеристики:

| Файл | Длительность | Видео | Аудио | SHA-256 |
|---|---:|---|---|---|
| `1.mp4` | 11,720 с | H.264, 1080×1920, 25 fps | AAC, 48 kHz stereo | `7BCEEE4F0DA73792FF7AFD70AF9BF4A8D5E4C5D24FD81476615E8A40A86D57E9` |
| `2.mp4` | 10,920 с | H.264, 1080×1920, 25 fps | AAC, 48 kHz stereo | `A61D9B531F9F0BC40F752CA5B5D176CC3E4009EFF1558BF6702172DA246316FE` |
| `3.mp4` | 11,480 с | H.264, 1080×1920, 25 fps | AAC, 48 kHz stereo | `C2683128DC6CFE16698D6D70B43BE544C5B5DC7B3C5E38D9F16A2078AAE98EAB` |
| `4.mp4` | 6,888 с | H.264, 1080×1920, 25 fps | AAC, 48 kHz stereo | `769B0624E46415778759BE44BD46D098E34F67279B8B200B7C5F72D3EDA4A220` |

Сумма исходников: `41,008` секунды. Master timeline: `42,320` секунды.

Это один и тот же аватар в одном помещении и образе. Не менять порядок файлов.

### 4.4. Каталог и реализации

```text
experiments\hyperframes-workflow-poc\stage-01-catalog\inventory\items.json
experiments\hyperframes-workflow-poc\stage-01-catalog\inventory\techniques.json
experiments\hyperframes-workflow-poc\stage-01-catalog\shortlist\auto-shortlist.json
```

Для каждого выбранного ID сначала найди запись в `items.json`, затем используй
её `source_ref`, implementation files, parameters, runtime и evidence lines.

Источники, которые уже можно переиспользовать:

```text
plugins\reels-factory\engine\src\reels_factory\hyperframes_blocks.py
plugins\reels-factory\engine\hyperframes\
C:\Users\Asus\Documents\personal_ai\projects\content_factory\plan-previews\two-reel-catalog-proxy-20260729\assets\catalog.js
C:\Users\Asus\Documents\personal_ai\projects\content_factory\plan-previews\two-reel-catalog-proxy-20260729\assets\catalog.css
```

Локальные шрифты:

```text
plugins\reels-factory\engine\hyperframes\_fonts\unbounded-600-cyrillic.woff2
plugins\reels-factory\engine\hyperframes\_fonts\unbounded-700-cyrillic.woff2
plugins\reels-factory\engine\hyperframes\_fonts\unbounded-800-cyrillic.woff2
```

## 5. Требуемая структура Stage 03

Создай минимум:

```text
stage-03-render/
  README.md
  BRIEF.md
  STORYBOARD.md
  input/
    edit_plan.timed.json
    word-timings.json
    source-assets.json
  project/
    hyperframes.json
    package.json
    index.html
    assets/
      media/
        avatar-island-01.mp4
        avatar-island-02.mp4
        avatar-island-03.mp4
        avatar-island-04.mp4
        avatar-base-silent.mp4
        voice_master.wav
        sfx/
      fonts/
    compositions/
      s01.html ... s13.html
  scripts/
    prepare-assets.mjs
    compile-edit-plan.mjs
    verify-render.mjs
  reports/
    input-audit.json
    compiler-report.json
    check.json
    render-audit.md
    contact-sheet.jpg
  renders/
    sales-three-questions-draft.mp4
```

Допустима эквивалентная структура, если HyperFrames scaffold создаёт свои
обязательные файлы. Но все перечисленные отчёты и финальный MP4 должны быть.

## 6. Подготовка avatar base

### 6.1. Копирование и аудит

Скопируй четыре MP4 и master WAV внутрь `project/assets/media/`. Не работай с
оригиналами напрямую после этого.

В `source-assets.json` запиши:

- абсолютный source path;
- локальный adopted path;
- SHA-256;
- codec, resolution, fps, audio streams;
- duration;
- порядок island;
- master audio duration/hash.

Если любой SHA или duration не совпал с таблицей выше — остановись и сообщи
конкретное расхождение.

### 6.2. Синхронизация четырёх кусков

Собери `1 → 2 → 3 → 4` в одну непрерывную видеодорожку. Встроенное аудио
avatar-клипов используй только для проверки порядка/lip-sync; в финальном
ролике оно должно быть полностью muted.

Базовый воспроизводимый вариант:

1. конкатенировать четыре video streams в указанном порядке;
2. равномерно увеличить video duration с `41,008` до `42,320` секунды;
3. коэффициент `setpts`: `1.03199375731565`;
4. эквивалентный playback rate: `0.968998109640832`;
5. привести выход к 1080×1920, square pixels и 30 fps;
6. результат — silent `avatar-base-silent.mp4` ровно 42,32 секунды.

Ориентировочные границы после равномерного ретайма:

| Island | Target start | Target end |
|---|---:|---:|
| 1 | 0,000000 | 12,094967 |
| 2 | 12,094967 | 23,364339 |
| 3 | 23,364339 | 35,211627 |
| 4 | 35,211627 | 42,320000 |

После сборки обязательно визуально проверить lip-sync минимум в точках:
`2.0`, `13.0`, `24.0`, `36.0`, `41.0` секунды.

Если рассинхрон заметен:

- не менять master audio;
- не менять порядок island;
- разрешено корректировать только per-island trim и playback rate;
- seams лучше прятать под сценами, где аватар скрыт смысловой графикой;
- сохранить фактические границы/rates в `source-assets.json` и
  `render-audit.md`;
- не замедлять отдельный island более чем на 6% без явного предупреждения.

Не пытайся решить рассинхрон заменой видео или новой генерацией HeyGen.

## 7. HyperFrames project

Инициализируй отдельный blank project с workflow `general-video`. Каталог Stage
01 извлекался из HyperFrames `0.7.87`; сохрани pin scaffold. Перед первой
render-affecting командой выполни обязательный read-only upgrade check из skill.
Если CLI требует обновление, следуй HyperFrames skill и зафиксируй старую/новую
версию в отчёте.

Canvas:

```text
1080 × 1920
30 fps
duration 42.32
language ru
```

Master audio — один framework-owned `<audio>` на полном timeline. Avatar base —
один framework-owned `<video>` на полном timeline. Не запускай media playback
через ручные timers.

Для 13 сцен используй sub-compositions. У каждого файла:

- root внутри `<template>`;
- host ID, inner `data-composition-id` и ключ `window.__timelines[id]`
  совпадают;
- style/script находятся внутри template;
- ровно один paused seek-safe timeline, зарегистрированный синхронно;
- все IDs уникальны в собранной странице и имеют scene prefix;
- полноэкранный фон находится на full-bleed child, не на root;
- элементы времени имеют `class="clip"` и валидные `data-*` attributes.

## 8. Точный timeline сцен

Не менять границы:

| Scene | Время | Ведущая | Основной визуал |
|---|---|---|---|
| `s01` | 0.000–3.000 | object overlay | Avatar Object Overlay + Stat Number, «ВСЕ ПРОДАЖИ = 3 ВОПРОСА» |
| `s02` | 3.000–5.333 | editorial bubble | Sequence Flow, «ПОРЯДОК РЕШАЕТ ВСЁ» |
| `s03` | 5.333–8.740 | hidden | Progressive Text Card + Complexity Cloud |
| `s04` | 8.740–11.520 | hidden | Checklist Strike + Task List |
| `s05` | 11.520–13.600 | editorial bubble | Concept Nodes, «В ОСНОВЕ — 3 ВОПРОСА» |
| `s06` | 13.600–18.580 | split | Persona Card, «1. КОМУ ПРОДАЁМ?» |
| `s07` | 18.580–22.740 | hidden | Value Layers, «2. ЧТО ПРОДАЁМ?» |
| `s08` | 22.740–25.960 | object overlay | Sequence Flow, «3. КАК ПРОДАЁМ?» |
| `s09` | 25.960–28.880 | split | Concept Nodes, «СЛОВА + ФОРМАТ» |
| `s10` | 28.880–31.560 | hidden | Concept Nodes, «ОСТАЛЬНОЕ — НАДСТРОЙКА» |
| `s11` | 31.560–34.440 | fullscreen | Avatar Fullscreen, «САМОЕ ВАЖНОЕ — ПОРЯДОК» |
| `s12` | 34.440–37.960 | hidden | Sequence Flow, `КТО → ЧТО → КАК` |
| `s13` | 37.960–42.320 | fullscreen | Social Outro + Task List + `@julia.agents` |

Avatar base продолжает проигрываться под скрывающими его fullscreen visuals,
чтобы при возврате лица не было временного скачка.

## 9. Catalog items и fallbacks

Используй только `render_ready` items, записанные в плане.

Три `adaptation_requests` на первом render **не реализовывать**:

- Kinetic Slam → использовать `local:block:stat_number`;
- Highlight → использовать `local:block:complexity_cloud`;
- Morph Text → использовать `local:block:sequence_flow`.

В `compiler-report.json` для каждой сцены запиши:

- requested layout/block/techniques;
- фактически подключённый source implementation;
- variables;
- fallback, если был;
- start/end/duration;
- итоговый composition path.

Если готовая реализация не подключается, сначала исправь wiring/variables. Не
рисуй новый неподтверждённый вариант под тем же catalog ID.

## 10. Motion, transitions и captions

### Motion

- Использовать существующую хореографию блока.
- Один смысловой focal action на сцену.
- Entrance обычно 0,35–0,70 с, затем читаемый hold.
- Не анимировать `.clip` visibility вручную.
- Никаких overlapping tweens, пишущих один transform без явной причины.

### Transitions

- Hard Cut — основной, без отдельной exit-анимации.
- Editorial Push — короткий акцент около 0,28 с на `s05`, `s10`, `s13`.
- White Flash — около 0,12 с перед `s12`.
- Переходы не меняют scene/audio timing.

### Captions

- Источник — `word-timings.json`, не повторная транскрибация.
- Стиль `accumulate`, положение `bottom` согласно approved layout safe zone.
- Unbounded, кириллица; прошлые слова белые, текущее ключевое слово
  `#FFE500`.
- Не больше 5–7 читаемых слов в одной caption-группе.
- В `s12` captions скрыты.
- Не дублировать крупный headline вторым таким же caption поверх него.
- Watermark `@julia.agents` появляется с 2,0 с и остаётся до конца.

## 11. SFX

Не искать SFX в интернете. Сначала проверить локальные файлы:

```text
C:\Users\Asus\Documents\personal_ai\projects\content_factory\work\archives\reels-factory-e2e-20260727-d2aa4090\job\revideo\public\whoosh.wav
C:\Users\Asus\Documents\personal_ai\projects\content_factory\work\archives\reels-factory-e2e-20260727-d2aa4090\job\revideo\public\type.wav
C:\Users\Asus\Documents\personal_ai\projects\content_factory\work\archives\reels-factory-e2e-20260727-d2aa4090\job\revideo\public\pop.wav
C:\Users\Asus\Documents\personal_ai\projects\content_factory\work\archives\reels-factory-e2e-20260727-d2aa4090\job\revideo\public\ding.wav
```

Допускается пропустить необязательный SFX, если он семантически не подходит.
Обязательный payoff: три тихих click/pop на стартах слов:

```text
34.980 — КТО
35.940 — ЧТО
37.460 — КАК
```

CTA confirmation допускается на `41.915` («сегодня»). SFX должен быть заметно
тише голоса и не ухудшать разборчивость. BGM не добавлять.

## 12. Детерминированный compiler

`compile-edit-plan.mjs` обязан:

1. читать `edit_plan.timed.json`, word timings и catalog inventory;
2. повторно валидировать непрерывность/длительности/IDs;
3. резолвить каждый ID только через catalog/source map;
4. подставлять content/labels/emphasis в доказанные parameter contracts;
5. создавать 13 sub-compositions и master `index.html`;
6. добавлять avatar base, master audio, captions, transitions и локальные SFX;
7. быть идемпотентным: повторный запуск на тех же входах даёт те же файлы;
8. не содержать творческих эвристик или новых LLM-вызовов.

Повторный запуск compiler должен завершиться без diff либо только с
детерминированно обновляемыми audit timestamps, если они вынесены отдельно.

## 13. Проверки перед render

После первого HTML pass запусти `lint`. Для финального gate запусти `check` —
не запускай redundant lint непосредственно перед ним.

Обязательно:

1. JSON/schema/edit-plan validation — PASS;
2. HyperFrames check — PASS без runtime, layout, motion, missing asset и
   contrast errors;
3. midpoint snapshot каждой из 13 сцен;
4. отдельные snapshots в `0`, `2`, `5.333`, `11.520`, `18.580`, `22.740`,
   `31.560`, `34.440`, `37.960`, `42.286`;
5. animation map / keyframes diagnostics для реальных animated subjects;
6. визуально открыть contact sheet и проверить:
   - нет чёрных/пустых кадров;
   - лицо не перекрыто текстом;
   - русский текст не обрезан;
   - avatar hidden/visible соответствует таблице;
   - переходы не дают вспышек вне указанных сцен;
   - финальный CTA читаем;
7. проверить lip-sync на пяти точках из § 6.2;
8. проверить единственность master voice: нет эха/двойного аудио.

Если check или визуальная проверка не прошли — исправить и повторить. Не
рендерить заведомо сломанный проект.

## 14. Render

Пользователь уже запросил тестовое видео, поэтому после PASS разрешён один
локальный draft render:

```text
renders\sales-three-questions-draft.mp4
```

Требования:

- 1080×1920;
- 30 fps;
- H.264 + AAC;
- длительность `42.320 ± 0.034` секунды;
- master voice слышен один раз;
- без runtime/network assets;
- файл существует и имеет ненулевой размер.

После render выполнить ffprobe и записать результат в `render-audit.md`.
Сделать contact sheet минимум из 13 midpoint frames.

## 15. Что вернуть пользователю

Не писать `COMPLETE`, пока фактически не существует проверенный MP4.

В финальном сообщении дать кликабельные абсолютные ссылки на:

1. `sales-three-questions-draft.mp4`;
2. `contact-sheet.jpg`;
3. `render-audit.md`;
4. `compiler-report.json`;
5. HyperFrames project root.

Кратко указать:

- итоговую duration/resolution/fps;
- status валидатора и HyperFrames check;
- как были синхронизированы четыре avatar island;
- какие три adaptation requests заменены fallbacks;
- какие SFX реально использованы/пропущены;
- любые визуальные отклонения от `edit_plan`.

Если MP4 невозможно получить, сообщить один конкретный технический blocker,
команду, полный текст ошибки и уже выполненные проверки. Не выдавать preview,
HTML или план за готовый render.

