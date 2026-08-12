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
