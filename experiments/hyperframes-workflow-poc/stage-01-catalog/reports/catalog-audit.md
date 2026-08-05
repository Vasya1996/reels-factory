# Catalog audit

## Preflight

- Branch: `codex/hyperframes-workflow-poc`
- Node: `v24.13.1`
- Baseline items: 161
- Baseline techniques: 157

## Sources

- Upstream snapshot: `C:\Users\Asus\Documents\personal_ai\projects\content_factory\reference-audit\hyperframes-main-20260801-complete\hyperframes-main`
- Upstream ZIP: `C:\Users\Asus\Documents\personal_ai\projects\content_factory\reference-audit\hyperframes-main-20260801.zip`
- Local blocks: `C:\Users\Asus\Documents\personal_ai\projects\content_factory\reels-factory-hyperframes-workflow-poc\plugins\reels-factory\engine\src\reels_factory\hyperframes_blocks.py`
- Approved catalog: `C:\Users\Asus\Documents\personal_ai\projects\content_factory\plan-previews\two-reel-catalog-proxy-20260729`

## Versions and SHA-256

- ZIP SHA-256: `CCA9B08B39A4A5FA29E55D9260F49020B1B6D455C68A674B42D4C3661D185BE3`
- packages: cli 0.7.87, core 0.7.87, producer 0.7.87, sdk 0.7.87
- Network registry update: no

## Counts

- upstream_blocks: 113
- upstream_components: 25
- local_blocks: 8
- approved_layouts: 10
- approved_transitions: 5
- total_items: 161
- upstream_examples_reported_not_cards: 8
- techniques: 157

## Parameterization

- approved_js_contract: 15
- declarative: 2
- generated_python: 8
- none: 136

## Orientation

- adaptive: 25
- landscape: 109
- portrait: 27

## Review status

- adapt: 129
- forbidden: 1
- ready: 23
- reference_only: 8

## Runtime dependencies

- dependency entries: 201
- unique URLs: 18

## Missing/broken previews

See `reports/preview-downloads.json`.

## Top-30 auto-shortlist

1. `local:block:before_after` — score 11: Локальный generated_python block с проверенным builder-контрактом.
2. `local:block:sequence_flow` — score 11: Локальный generated_python block с проверенным builder-контрактом.
3. `local:block:stat_number` — score 11: Локальный generated_python block с проверенным builder-контрактом.
4. `local:block:task_list` — score 11: Локальный generated_python block с проверенным builder-контрактом.
5. `approved:layout:avatar_broll_split` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
6. `approved:layout:avatar_editorial_bubble` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
7. `approved:layout:avatar_fullscreen` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
8. `approved:layout:avatar_object_overlay` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
9. `approved:layout:broll_archival_collage` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
10. `approved:layout:broll_fullscreen` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
11. `approved:layout:checklist_strike` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
12. `approved:layout:progressive_text_card` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
13. `approved:layout:social_outro` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
14. `approved:transition:hard_cut` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
15. `approved:transition:transition_blur` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
16. `approved:transition:transition_push_editorial` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
17. `approved:transition:transition_white_flash` — score 10: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
18. `approved:transition:transition_chromatic` — score 8: Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.
19. `local:block:complexity_cloud` — score 8: Локальный generated_python block с проверенным builder-контрактом.
20. `local:block:concept_nodes` — score 8: Локальный generated_python block с проверенным builder-контрактом.
21. `local:block:persona_card` — score 8: Локальный generated_python block с проверенным builder-контрактом.
22. `local:block:value_layers` — score 8: Локальный generated_python block с проверенным builder-контрактом.
23. `upstream:component:caption-texture` — score 6: Upstream item имеет подходящую роль, совместимую orientation и доказанные declarative variables; runtime ждёт human approval.
24. `upstream:component:grid-pixelate-wipe` — score 6: Подходит по роли, но требует адаптации canvas, content variables или runtime contracts.
25. `upstream:component:parallax-unzoom` — score 6: Подходит по роли, но требует адаптации canvas, content variables или runtime contracts.
26. `upstream:component:parallax-zoom` — score 6: Подходит по роли, но требует адаптации canvas, content variables или runtime contracts.
27. `upstream:component:caption-blend-difference` — score 5: Подходит по роли, но требует адаптации canvas, content variables или runtime contracts.
28. `upstream:block:instagram-follow` — score 4: Подходит по роли, но требует адаптации canvas, content variables или runtime contracts.
29. `upstream:block:spotify-card` — score 4: Подходит по роли, но требует адаптации canvas, content variables или runtime contracts.
30. `upstream:block:tiktok-follow` — score 4: Подходит по роли, но требует адаптации canvas, content variables или runtime contracts.

## Local blocks

- `local:block:before_after`: after_label, after_value, before_label, before_value
- `local:block:complexity_cloud`: items, resolution, title
- `local:block:concept_nodes`: items, title
- `local:block:persona_card`: items, title
- `local:block:sequence_flow`: items, title
- `local:block:stat_number`: label_bottom, label_top, prefix, suffix, value
- `local:block:task_list`: items, title
- `local:block:value_layers`: actual, offer, title

## Approved patterns

- `approved:layout:avatar_broll_split`: approved_js_contract; fields baseVideo, brollVideo, start
- `approved:layout:avatar_cutout_overlay`: approved_js_contract; fields cutoutImage, emphasis
- `approved:layout:avatar_editorial_bubble`: approved_js_contract; fields baseVideo, purpose, text
- `approved:layout:avatar_fullscreen`: approved_js_contract; fields emphasis, id, role, start
- `approved:layout:avatar_object_overlay`: approved_js_contract; fields baseVideo, hits
- `approved:layout:broll_archival_collage`: approved_js_contract; fields brollVideo, purpose, text
- `approved:layout:broll_fullscreen`: approved_js_contract; fields brollVideo, start
- `approved:layout:checklist_strike`: approved_js_contract; fields 
- `approved:layout:progressive_text_card`: approved_js_contract; fields emphasis, hits, purpose
- `approved:layout:social_outro`: approved_js_contract; fields id
- `approved:transition:hard_cut`: approved_js_contract; fields id, start, transition
- `approved:transition:transition_blur`: approved_js_contract; fields id, start, transition
- `approved:transition:transition_chromatic`: approved_js_contract; fields id, start, transition
- `approved:transition:transition_push_editorial`: approved_js_contract; fields id, start, transition
- `approved:transition:transition_white_flash`: approved_js_contract; fields id, start, transition

## Forbidden confirmation

`approved:layout:avatar_cutout_overlay` remains `forbidden` and `runtime_allowed: false`.

## Not done

- No edit_plan, render, Stage 02, LLM, ElevenLabs, HeyGen or provider calls.

## Commands

```powershell
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/extract-catalog.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/download-posters.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/build-gallery.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/validate-catalog.mjs
```
