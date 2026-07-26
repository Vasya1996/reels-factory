# Visual Director — offline 30/60/90 demo

Production `build_edit_plan()` был запущен по трём approved-scenario fixtures.
LLM, ElevenLabs, HeyGen, HyperFrames render, deploy и production services не
вызывались.

| Timeline | Windows | Built-in windows | Built-in seconds | Bubble | Max avatar-only |
|---:|---:|---:|---:|---:|---:|
| 30s | 7 | 2 | 14.5s | 1 | 4.0s |
| 60s | 15 | 5 | 30.993s | 1 | 6.596s |
| 90s | 21 | 6 | 41.493s | 1 | 8.507s |

В каждой папке находятся `scenario.json`, `edit_plan.json` и `timeline.svg`.
