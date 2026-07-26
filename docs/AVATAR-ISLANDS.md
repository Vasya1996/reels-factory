# Stage 3 — adaptive Photo Avatar IV islands

## Scope

Stage 3 replaces transitional “one HeyGen request per semantic block” in the
master-audio path. It is intentionally limited to Photo Avatar IV:

- required: `avatar.heygen_asset_id`;
- required engine: `avatar_iv` (the `type:image` request keeps using the
  provider default and does not send the forbidden `engine` field);
- rejected before TTS/HeyGen: `avatar.heygen_look_id` and Avatar V;
- production rollout and paid smoke are not part of this change.

Official request contract:

- <https://developers.heygen.com/reference/create-video>
- <https://developers.heygen.com/photo-avatar>
- <https://help.heygen.com/en/articles/12805098-fine-tune-avatar-gestures-and-movements-with-custom-motion-prompts-avatar-iv-v>

The API accepts one `motion_prompt` and one `expressiveness` value per Photo
Avatar IV request. Therefore exact phrase recommendations remain source
directorial intent, while the render planner chooses a small number of
compatible performance shots.

## Runtime

Feature flags:

```yaml
master_audio:
  enabled: true

avatar_islands:
  enabled: true
  handle_seconds: 0.2
  min_request_seconds: 3.0
  target_shot_seconds: 10.0
  max_shot_seconds: 18.0
  max_shots_per_30_seconds: 5
  max_parallel: 2
```

`RF_AVATAR_ISLANDS_ENABLED` overrides the YAML flag. Enabling islands without
master audio is a pre-provider configuration error.

Flow:

1. `edit_plan.json` is finalized from ElevenLabs alignment.
2. Adjacent phrase windows with `coverage=avatar|mixed` become continuous
   islands. `full_broll|hyperframes` terminates an island.
3. A deterministic dynamic-programming pass partitions each island into
   performance shots.
4. Exact shot audio is cut from `voice_master.wav`, with bounded handles.
5. Shots are rendered with limited concurrency and content-addressed cache.
6. Revideo trims every shot back to its exact visible range, fills technical
   overlay gaps with black, drops provider audio and plays one master voice.

## Adaptive quality rules

The planner does not use fixed templates for 30/60/90 seconds:

- target shot length: 10 seconds;
- hard visible-shot maximum: 18 seconds;
- hook and CTA do not share a shot with another role;
- a direct `low ↔ high` change always creates a shot boundary;
- compatible adjacent recommendations are grouped to avoid a face/identity
  reset on every sentence;
- full B-roll and HyperFrames gaps never generate avatar video;
- five shots per 30 seconds is a quality budget, not a destructive hard cap.
  A justified extra performance change is kept and reported as a warning.

Every generated phrase retains:

- requested `expressiveness`;
- requested `motion_prompt`;
- whether its recommendation is the exact applied shot profile;
- the shot and island IDs;
- the representative phrase whose profile is sent to HeyGen.

This distinction is required because the provider cannot change controls
inside one request. Splitting every phrase would technically apply every value
but usually gives worse identity continuity and substantially more paid
requests.

## Artifacts

`avatar_render_plan.json` is a derived execution plan, not a second creative
edit plan. It contains:

- final edit-plan and master-audio hashes;
- islands and exact phrase membership;
- shots, request/visible timing and trim;
- applied Photo Avatar IV controls and all phrase intents;
- deterministic idempotency identity;
- requested/visible/saved seconds and informational cost estimate;
- validator report.

`avatar_render_manifest.json` is written atomically before generation and after
each completed future. For every shot it records:

- audio hash;
- cache key;
- local idempotency key;
- status (`planned|ready|failed`);
- provider job ID slot (currently `null`, because the existing synchronous
  client does not expose a durable create-job response);
- output path/hash or failure.

The local cache prevents a completed identical shot from being paid twice.
This is not claimed to be provider-side idempotency: provider job persistence,
webhooks and resume checkpoints remain the next broader stage.

## Offline demo

Run:

```powershell
$env:PYTHONPATH = "plugins/reels-factory/engine/src"
python plugins/reels-factory/engine/scripts/demo_avatar_islands.py
```

Outputs are generated under `docs/avatar-islands-demo/{30s,60s,90s}`:

- `scenario.json`;
- final `edit_plan.json`;
- `avatar_render_plan.json`;
- `timeline.svg`.

Scenarios and timeline images are committed as review fixtures. The much larger
`edit_plan.json` and `avatar_render_plan.json` files stay local/ignored and are
reproducible from the script, keeping the Git diff reviewable.

The demo never calls ElevenLabs, HeyGen, deployment or production services.
