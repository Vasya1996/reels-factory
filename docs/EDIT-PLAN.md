# Canonical `edit_plan.json`

`edit_plan.json` — единственный job artifact, который отвечает на вопрос
«что и когда показывать». `segment_plan.py` больше не планирует независимо, а
`revideo_adapter.py` только проецирует финальный документ в `tz.json`.

## Lifecycle

1. После утверждения сценария `build_edit_plan()` создаёт `status: draft`.
2. До TTS/HeyGen validator проверяет phrase ranges, coverage, assets,
   confidence/duration, hook/CTA, максимальные 10 секунд без лица и
   `avatar_performance`.
3. Master audio возвращает immutable character/word alignment.
4. `finalize_edit_plan()` добавляет `final_timing`. Coverage и window IDs не
   перепридумываются; небезопасный exact window получает явную revision и
   avatar fallback.
5. Pipeline пропускает HeyGen только для блока с validator-approved
   `safe_to_skip_avatar`.
6. `edit_plan_to_tz()` выполняет чистую Revideo projection.

Draft и final сохраняются по одному пути: новый validated snapshot атомарно
заменяет предыдущую фазу внутри изолированного job workdir. Отдельных
`segment_plan.json`, `edit_plan.draft.json` и `edit_plan.final.json` нет.

## Phrase performance

У каждой phrase есть:

```json
{
  "avatar_performance": {
    "expressiveness": "medium",
    "motion_prompt": "Looks at the camera and nods gently, confident and clear.",
    "prompt_language": "en",
    "source": "role_default",
    "rationale": "...",
    "engine_scope": "photo_avatar_iv"
  }
}
```

Допустимые значения `expressiveness`: `low`, `medium`, `high`; автоматические
defaults используют `low`/`medium`, а `high` оставляют для явно оправданной
фразы. Motion prompt должен быть коротким plain-English описанием одного
видимого жеста/движения и необязательной эмоции. Запрещено управлять камерой,
таймингом, сценой, локацией, реквизитом, ходьбой, фоном и светом.

Опциональный `edit_plan.performance_llm.enabled` запускает отдельный анализ
всех phrase IDs до платной генерации. Ответ считается валидным только если
содержит ровно одну рекомендацию для каждой фразы. Явные avatar settings
пользователя не перезаписываются.

## Avatar bubble

Bubble является canonical visual decision, а не поздним украшением Revideo.
Окно хранится как `coverage: mixed`: полноэкранный B-roll/HyperFrames несёт
смысл, а Photo Avatar IV остаётся поверх него в круглом или квадратном crop.
Поэтому Avatar Islands обязаны сгенерировать соответствующие phrase IDs.

Deterministic fallback распознаёт короткий нумерованный шаг с тремя
поясняющими фразами, например:

```text
Третий: как продаём? Где встречаемся, какими словами говорим,
в каком виде предлагаем.
```

Для такого окна planner создаёт HyperFrames `task_list`, добавляет
`effect.bubble` и скрывает дублирующие нижние captions. Существующий
payoff+B-roll триггер (`настроил`, `один раз`, `больше не`, `готово`) использует
тот же контракт.

Quality gates:

- только `coverage: mixed`, без `safe_to_skip_avatar`;
- supporting visual обязателен: fullscreen B-roll либо HyperFrames;
- hook и CTA запрещены;
- default duration 3–6 секунд;
- default frequency — один bubble на каждые начатые 45 секунд;
- `shape: circle|square`, позиция — один из четырёх углов;
- exact master alignment вне разрешённой длительности даёт явный avatar
  fallback до HeyGen.

Настройки находятся в `edit_plan.bubble`. При успешном HyperFrames render
bubble сохраняется при замене HTML-блока на fullscreen mp4; при сбое остаётся
встроенный `chart_bars` fallback.

На сценарии «три вопроса продаж» offline draft формирует:

- `23.768–25.208` — лицо крупно, punch-in на «Третий: как продаём?»;
- `25.208–30.176` — HyperFrames `task_list`, три пункта появляются
  последовательно, Photo Avatar IV остаётся в `bottom_left` circle bubble.

Это estimated timing. После master alignment границы уточняются без повторного
семантического решения; если exact bubble вышел за 3–6 секунд, применяется
явный avatar fallback.

HeyGen API reference помечает `expressiveness` и `motion_prompt` как controls
для Photo Avatar / Avatar IV:

- https://developers.heygen.com/reference/create-video
- https://developers.heygen.com/photo-avatar
- https://help.heygen.com/en/articles/12805098-fine-tune-avatar-gestures-and-movements-with-custom-motion-prompts-avatar-iv-v

Stage 3 Avatar Islands считает `mixed` видимым coverage и включает все phrase
IDs bubble-окна в Photo Avatar IV shots. Revideo adapter добавляет к
`effect.bubble` face crop/zoom, а HyperFrames resolver сохраняет bubble при
замене блока на MP4. Avatar V остаётся вне scope. Дробить платную генерацию на
каждую фразу нельзя: это ухудшит визуальную непрерывность и вернёт покусковые
seams.
