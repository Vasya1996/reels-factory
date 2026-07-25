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

HeyGen API reference помечает `expressiveness` и `motion_prompt` как controls
для Photo Avatar / Avatar IV:

- https://developers.heygen.com/reference/create-video
- https://developers.heygen.com/photo-avatar
- https://help.heygen.com/en/articles/12805098-fine-tune-avatar-gestures-and-movements-with-custom-motion-prompts-avatar-iv-v

Текущий runtime генерирует HeyGen по смысловым блокам. Поэтому Stage 2 хранит
per-phrase режиссуру, а Stage 3 (avatar islands) должен применить её на
совместимом IV request либо сначала подтвердить отдельным provider probe новый
API-контракт Avatar V. Дробить блоки на фразы в Stage 2 нельзя: это ухудшит
визуальную непрерывность и вернёт покусковую генерацию.
