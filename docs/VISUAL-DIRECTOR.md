# Stage 2.1 — canonical Visual Director

Visual Director компенсирует длинные talking-head участки встроенными
смысловыми композициями. Решение принимается до TTS и HeyGen и сохраняется в
единственном `edit_plan.json`; сборщик HyperFrames не перепланирует его.

## Что формируется

| Template | Когда полезен | Что происходит |
|---|---|---|
| `complexity_cloud` | «Мы усложняем… а в основе…» | Несколько шумных карточек появляются каскадом и схлопываются в один тезис |
| `persona_card` | «Кому продаём?» | Карточка аудитории раскрывает человека, контекст и боль |
| `value_layers` | «Что продаём на самом деле?» | Формальный offer уменьшается, реальная ценность занимает кадр |
| `concept_nodes` | «Всё остальное — надстройка…» | Опорные понятия расходятся от центральной основы |
| `sequence_flow` | «Сначала… потом…» | Шаги раскрываются в обязательном порядке |

Отдельно продолжает работать `task_list + Avatar IV bubble`: полноэкранный
список несёт смысл, а лицо остаётся в круглом/квадратном crop. Avatar V в этом
этапе не используется.

## Canonical flow

```text
approved scenario
  -> deterministic Visual Director rules
  -> optional constrained visual LLM
  -> deterministic assetless HyperFrames fallback
  -> optional per-phrase performance LLM
  -> validated edit_plan.json / draft
  -> master audio + alignment
  -> same edit_plan.json / final
  -> HyperFrames render OR equivalent Revideo fallback
  -> Avatar IV islands only where coverage is avatar|mixed
```

LLM не является обязательным для базового результата. Детерминированные
триггеры покрывают известные структурные конструкции, а optional LLM может
добавить максимум три окна только среди ещё не оформленных avatar-only фраз.
После него обязательный assetless fallback проверяет оставшиеся длинные
участки. Если B-roll не найден, он строит локальный `concept_nodes`, а для
сравнения — `value_layers`; платный или внешний media API для этого не нужен.

## Настройки

```yaml
edit_plan:
  visual_director:
    enabled: true
    min_seconds: 3.0
    max_seconds: 9.5
    max_per_30_seconds: 4
    max_llm_windows: 3
    assetless_fallback_after_seconds: 6.0
    llm:
      enabled: false
      timeout_s: 600
```

## Motion design contract

Каждый блок — standalone 1080×1920 HyperFrames composition:

- один paused GSAP timeline, зарегистрированный синхронно;
- `class="clip"` и явные `data-start/data-duration/data-track-index`;
- отдельные full-bleed backdrop и scene tracks;
- только детерминированные transform/opacity animations;
- self-hosted fonts; никакого случайного layout и runtime clocks.

В пяти шаблонах используются четыре согласованных motion pattern:

- waterfall entry для последовательного раскрытия;
- spring-pop entrance для смысловых карточек;
- scale-swap для замены формального слоя реальным;
- center-outward expansion для связанных понятий.

При ошибке HTML render canonical effect остаётся неизменным, а Revideo
исполняет локальный fallback по тем же `title/items/offer/actual/resolution`.

## Quality gates

- Built-in visual длится 3–9,5 секунды.
- Непрерывное отсутствие лица не превышает 10 секунд.
- Лимит 10 секунд считается суммарно по соседним B-roll и HyperFrames окнам,
  а не отдельно для каждого окна.
- Hook и CTA остаются с Photo Avatar IV.
- Adjacent phrase IDs обязательны; пересечение semantic blocks запрещено.
- Уже выбранные B-roll, HyperFrames и bubble окна не перезаписываются.
- Captions внутри semantic visual всегда `hidden`.
- На каждые начатые 30 секунд допускается до четырёх built-in окон.
- Invalid template/variables/coverage отклоняются до платной стадии.
- LLM-рекомендации применяются транзакционно по одной. Ошибка одного окна не
  отменяет уже принятые окна и не останавливает pipeline; accepted/rejected и
  точная причина сохраняются в `visual_director_reviews`.
- Между соседними assetless fullscreen visuals сохраняется хотя бы одно
  `avatar|mixed` окно для возврата eye contact.
- Final alignment не запускает новый creative decision: выход за exact limits
  создаёт явную revision и avatar fallback.

## Сценарий «три вопроса продаж»

Estimated canonical timeline:

| Время | Visual state |
|---:|---|
| 0.000–6.200 | Photo Avatar IV, hook |
| 6.200–14.624 | `complexity_cloud`: приёмы/скрипты/фразы → три вопроса |
| 14.624–16.136 | Avatar punch-in: «Первый» |
| 16.136–19.448 | `persona_card`: человек/контекст/боль |
| 19.448–23.768 | `value_layers`: что продаём → что покупает клиент |
| 23.768–25.208 | Avatar punch-in: «Третий» |
| 25.208–30.176 | `task_list` + Photo Avatar IV bubble |
| 30.176–33.200 | `concept_nodes`: кому/что/как |
| 33.200–35.760 | Photo Avatar IV, payoff setup |
| 35.760–40.000 | `sequence_flow`: кто → что → как |
| 40.000–44.700 | Photo Avatar IV + CTA endcard |

Встроенные visuals занимают 23,32 секунды, bubble — 4,968 секунды.
Максимальный непрерывный участок, где видна только голова без смыслового
visual state change, равен 6,2 секунды.

## Offline 30/60/90 fixtures

Скрипт `plugins/reels-factory/engine/scripts/demo_visual_director.py` строит
три настоящих draft plans через production `build_edit_plan()` и пишет
`scenario.json`, `edit_plan.json` и `timeline.svg` в
`docs/visual-director-demo/{30s,60s,90s}`. Он не вызывает ElevenLabs, HeyGen,
LLM, deploy или production services.
