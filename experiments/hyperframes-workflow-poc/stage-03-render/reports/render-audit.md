# Render Audit

Status: PASS

MP4: C:\Users\Asus\Documents\personal_ai\projects\content_factory\reels-factory-hyperframes-workflow-poc\experiments\hyperframes-workflow-poc\stage-03-render\renders\sales-three-questions-draft.mp4
Contact sheet: C:\Users\Asus\Documents\personal_ai\projects\content_factory\reels-factory-hyperframes-workflow-poc\experiments\hyperframes-workflow-poc\stage-03-render\reports\contact-sheet.jpg

## ffprobe

- duration: 42.333 s
- resolution: 1080x1920
- fps: 30.000
- video codec: h264
- audio streams: 1
- audio codec: aac
- file size: 12394193 bytes

## Gates

- Stage 02 validator: PASS
- HyperFrames check: PASS
- Expected duration tolerance: 42.320 +/- 0.034 s
- Master voice uniqueness: one audio stream in final MP4

## Avatar Sync

The four avatar islands were concatenated in the supplied chronological order and uniformly retimed with setpts=1.03199375731565, equivalent playback rate 0.968998109640832, then converted to 1080x1920, square pixels, 30 fps, silent H.264.

Visual lip-sync review points for the contact/preview pass: 2.0, 13.0, 24.0, 36.0, 41.0 seconds.

## SFX

Used local pop clicks at 34.980, 35.940, 37.460 and 41.915 if pop.wav was available. Used quiet local whoosh at editorial push starts if whoosh.wav was available. No BGM was added.

## Visual Review Notes

Contact sheet was generated from 13 scene midpoint frames and inspected locally.

- No black or empty frames were visible in the contact sheet.
- Avatar hidden/visible intent matches the 13-scene table at midpoint level: hidden scenes are full-screen graphics, mixed/fullscreen scenes keep the avatar visible.
- Final CTA is readable.
- Draft visual deviation: mixed/editorial scenes use the deterministic Stage 03 adapter over the continuous root avatar video, not a new adapted catalog component. At midpoint, s02/s05 have denser editorial overlay behavior than the ideal future catalog adaptation, but they do not block this draft render.
- Optional icon intents were not resolved to new assets; no external icon/media providers were called.
- Animation diagnostics were captured in reports/keyframes.json. The separate animation-map helper was not bootstrapped because it requested additional @hyperframes helper packages; the HyperFrames keyframes CLI path completed locally.
