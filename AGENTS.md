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

### Rejected approaches

- Do not switch back to Eleven v3 for production: tests found that it loses
  the cloned speaker identity.
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
