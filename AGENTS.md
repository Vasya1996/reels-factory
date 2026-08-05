# Reels Factory — persistent project context

This file contains stable decisions that future coding sessions must preserve.
Re-check live state before acting; do not treat commit IDs or deployment status
as permanently current.

## Production voice/TTS decision — 2026-07-28

The top voice-quality priority is speaker identity: the clone must remain as
close as possible to the source voice while sounding alive rather than robotic
or monotone.

- Production provider: ElevenLabs.
- Production model: `eleven_multilingual_v2`.
- Approved settings:
  - `speed: 1.1`
  - `stability: 0.2`
  - `similarity_boost: 0.55`
  - `style: 0.5`
  - `use_speaker_boost: false`
  - `apply_text_normalization: auto`
  - `output_format: mp3_44100_128`
- Multilingual v2 detects Russian from the text; do not send
  `language_code` to the provider for this model.
- Keep the production path as one master narration request through
  `/with-timestamps`, followed by local alignment/timeline processing.
- All TTS settings, the model, voice hash, and input hash must remain part of
  the deterministic `cache_key` and `audio_manifest.json`.

## Per-language TTS model — 2026-07-30

The model is chosen by the reel language, not fixed globally:

- `ru` → `eleven_multilingual_v2` (production decision above; best clone
  identity for Russian).
- `kk` → `eleven_v3`. This is a **deliberate exception** to the "reject v3"
  note below: multilingual v2 does **not** support Kazakh at all, so there is
  no v2 option for `kk`. v3 is the only model that speaks Kazakh.
- Implementation: `tts.tts_model_for_language(language)`; the bot writes
  `tts.model_id` into the immutable job snapshot (`enqueue_build`,
  `save_client_profile`), so the model stays part of `cache_key` /
  `audio_manifest.json`.
- v3 requires a discrete `stability` (0.0/0.5/1.0); the master-audio path
  defaults it to `0.5` for v3 (`DEFAULT_STABILITY_V3`) instead of the v2 `0.2`.
- Verified 2026-07-30 with one paid probe (`scripts/probe_v3_timestamps.py`):
  `eleven_v3` returns valid per-character alignment via `/with-timestamps`
  for Kazakh with `language_code="kk"` (no `kaz` mapping needed). So the full
  montage path (which needs alignment) works for `kk`, same as `ru`.

## Montage toggle — 2026-07-30

Each reel can be built **with montage** (full edit_plan / B-roll / captions /
Revideo) or **without** (a single HeyGen pass over the approved master audio,
no captions, no QA gates — raw talking head). Chosen on the READY screen
(`build:montage` / `build:plain`), persisted as `config.montage` in the job
snapshot, and branched in `pipeline.run_make` → `_run_plain_avatar`. The audio
step (master-audio synthesis + user approval) is identical for both modes.

### Rejected approaches

- Do not switch back to Eleven v3 for production **Russian**: tests found that
  it loses the cloned speaker identity. (Kazakh is the documented exception
  above — v2 has no Kazakh, so `kk` uses v3.)
- Eleven v2.5 was ruled out for this solution.
- Do not add Eleven v3 audio tags such as `[sighs]`, `[excited]`,
  `[whispers]`, or similar tags to scenario text.
- Do not add SSML or a pause-preprocessing layer unless the user explicitly
  starts a new experiment. That work was consciously excluded from the V2
  rollout.
- Fish/Starfish was tested and could sound natural, but the final production
  decision is ElevenLabs Multilingual v2 with the settings above.

### Acceptance baseline

- The Russian acceptance voice used for the controlled smoke test was
  `0yJ7C5ScAKOutyYIVwdR`. Do not hardcode it into generic production code;
  production voice IDs still come from the client profile.
- A production-server smoke test succeeded with the approved Russian script:
  449 input characters and about 30.42 seconds of generated audio.
- Baseline implementation was merged in PR #16; merge commit `0cc3e50`.

### Safe verification order

1. Run offline/unit tests and a server-side non-provider smoke first.
2. With explicit permission for provider spend, run one TTS-only request and
   let the user listen to the MP3.
3. Only after voice approval, run one full TTS → HeyGen → render E2E job.

Do not trigger paid ElevenLabs or HeyGen requests merely to inspect or diagnose
the code. Never print, persist, or return API keys; read them from the existing
server environment.

## One-LLM HyperFrames workflow decision — 2026-08-02

The intended production architecture is one constrained visual-director LLM
call followed by deterministic scripts. Do not replace it with a free-running
agent loop for every render.

Starting from approved ElevenLabs master audio plus word timestamps:

1. Build one compact prompt from transcript/timings, catalog shortlist, brand
   constraints and montage rules.
2. Make one LLM call that returns semantic `edit_plan.json`: scene timing,
   coverage, layout/block/component/transition IDs, text payloads, caption mode,
   SFX/media intents, adaptation requests and pre-approved fallbacks. The LLM
   must not emit pixel coordinates or author composition HTML.
3. Validate and present the plan for human review. Human JSON edits do not
   require another LLM call. Freeze the approved plan before paid avatar work.
4. Derive Avatar Islands deterministically from the final plan: adjacent
   `coverage=avatar|mixed` phrase windows form an island;
   `full_broll|hyperframes` terminates it. Partition islands into cached Photo
   Avatar IV performance shots using the rules in `docs/AVATAR-ISLANDS.md`.
5. Resolve catalog IDs to proven implementations via `source_ref`; instantiate
   declared parameter contracts only. `adapt` items may not run directly unless
   an adapter is separately implemented and approved; otherwise use the
   plan-declared `ready` fallback.
6. Compile layouts, blocks, captions, animation presets, transitions, SFX,
   silent avatar media and the single master voice into HyperFrames HTML.
7. Validate, snapshot, render and audit deterministically. Technical rerenders
   and human parameter edits must not invoke an LLM.

Catalog semantics that future sessions must preserve:

- A technique is descriptive metadata, not necessarily executable code.
- An upstream block is a standalone HTML sub-composition.
- An upstream component is an HTML/CSS/JS snippet that needs a host target.
- A local block is produced by an existing Python HTML generator.
- Approved layouts/transitions are proven JS/CSS contracts from the local
  approved catalog.
- Template-owned markup, style and motion stay unchanged unless the catalog
  exposes an explicit parameter/adapter contract.
- The LLM chooses semantic IDs/content/timing. Compiler scripts resolve code,
  bind values, choose slots, generate captions, synchronize animation triggers
  and assemble the final page.

### Safe-zone and placement architecture

For one stable avatar/look/framing, analyze only the first generated island and
cache a source-coordinate avatar profile. Recompute only when the avatar, look,
camera/framing or crop source changes. Transform its face envelope with each
layout's actual media transform.

Forbidden-zone control has five deterministic layers:

1. Before the LLM, filter out layout IDs incompatible with the cached avatar
   profile; pass compatibility metadata, not raw coordinates, to the model.
2. Caption placement uses transformed face, platform UI and frame zones, then
   publishes the measured caption bounds as another hard forbidden zone.
3. The layout placement compiler chooses only catalog-declared slots that do
   not intersect face, caption or UI zones. It may not switch semantic layouts
   except through an explicit `fallback_layout_id` in the approved plan.
4. Animation validation checks the complete swept envelope, including entrance,
   overshoot, scale, rotation and exit; animated content should remain inside a
   safe clipped slot whenever possible.
5. A final per-output-frame DOM collision validator gates render. Any
   informational-element intersection with face/captions/UI is a hard failure.

Hard priority is platform UI → face → captions → informational overlays →
decoratives. Full-frame transitions or other intentional exceptions must be
explicitly tagged and narrowly scoped. Human contact-sheet review remains an
aesthetic check, not the collision guarantee.

As of 2026-08-02 this automated safe-zone chain is an approved design, not an
implemented feature. The POC currently relies on approved fixed CSS layouts,
HyperFrames checks, snapshots/contact sheets and manual visual review. Do not
claim that `avatar-profile.json`, `layout-slots.json`,
`forbidden-zones.json` or per-frame `collision-report.json` already exist.

### Stage 03 implementation audit correction — 2026-08-02

Do not treat the current Stage 03 render as proof that the catalog resolver or
the original local/approved implementations were reused. Inspection of
`stage-03-render/scripts/compile-edit-plan.mjs` shows that it does not import or
execute `hyperframes_blocks.py`, `catalog.js`, or `catalog.css`. It contains its
own `blockMarkup`, `layoutChrome`, `sceneCss`, and `sceneScript` functions with
hard-coded HTML/CSS/GSAP. The source paths recorded in `compiler-report.json`
are attribution strings, not evidence of runtime reuse.

Therefore the current video is a one-off visual approximation authored by the
render model from the plan and prior patterns. Three requested upstream adapt
items still fell back to local IDs, but even those local IDs were reimplemented
inside the JavaScript compiler rather than instantiated through their proven
Python generators. Before the workflow hypothesis is considered validated,
replace this with a real ID-to-adapter resolver that imports/calls the approved
implementation (or a reviewed faithful adapter), binds only its declared
parameters, and emits provenance that can be mechanically verified.
