# Stage 02 — one-call LLM input

Эта стадия готовит единственный воспроизводимый запрос к LLM для чернового
`edit_plan`. Она не вызывает LLM, ElevenLabs, HeyGen, media providers или
HyperFrames render.

Входы:

- `inputs/audio/scenario.json` — канонический текст, совпадающий с озвучкой;
- `inputs/audio/alignment.json` — точный ElevenLabs alignment;
- `inputs/audio/provider.json` — длительность и контрольные суммы аудио;
- `../stage-01-catalog/shortlist/auto-shortlist.json` — 49 разрешённых
  кандидатов;
- `../stage-01-catalog/inventory/items.json` — доказанные свойства кандидатов;
- `inputs/project-constraints.json` — монтажные и брендовые ограничения POC.

Сборка пакета:

```powershell
node scripts/prepare-llm-request.mjs
```

Результат:

- `inputs/word-timings.json` — компактные пословные тайминги и диапазоны
  сценарных блоков;
- `inputs/catalog-shortlist.compact.json` — 49 карточек без gallery-мусора;
- `schemas/edit-plan.schema.json` — строгая схема ответа с enum из каталога;
- `prompt/system.md` — системный промпт Visual Director;
- `llm-request.json` — готовый пакет одного вызова;
- `reports/input-audit.md` — проверка соответствия текста, alignment и каталога.

`llm-request.json` намеренно не содержит MP3: для режиссёрского решения нужны
точный текст и временные границы слов. Видео аватара и media assets появятся
после человеческого утверждения плана.

