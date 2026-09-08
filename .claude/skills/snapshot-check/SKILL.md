---
name: snapshot-check
description: Verify a composition change by looking at rendered frames instead of rebuilding a reel — swap the changed file into a scratch copy of a real prod job and snapshot it in minutes. Use whenever a change touches captions, schemas, positions, contrast, layout, or anything else that only shows up on a rendered frame; this is the proof step `/razbor` requires before merging a composition change, and it costs nothing (no HeyGen, no ElevenLabs, no new job).
---

# Snapshot-check

A composition change is not proven by a green gate. `hf_gates.py` catches what it was
written to catch; a frame shows what actually happened. This skill gets you a frame
in minutes, on material that is already paid for, without touching the job it came
from or spending anything new.

## What this is not

- Not a rebuild. `/prod-rebuild` re-runs a job through the bot's queue and produces a
  finished `reel.mp4`; this produces a handful of PNG frames from a scratch copy.
  Reach for this first — it is faster and the default level of proof for a
  composition change. Reach for `/prod-rebuild` only when the change needs to be seen
  end to end (pacing, audio, a full contact sheet) or when the fixed thing can't be
  isolated to a few frames.
- Not a live check. Nothing here enqueues a job or restarts the bot service.

## Steps

1. **Pick a real job.** Any finished or in-progress job under
   `/root/reels-workspace/work/jobs/<job>/public` on prod has real composed HTML,
   real clips, and a real `plan.json` — exactly what a from-scratch fixture would take
   effort to fake convincingly.

2. **Copy it out, read-only against the original.** Either pull it to this machine or
   stage it in `/tmp` on the server itself:
   ```
   scp -r root@134.209.80.75:/root/reels-workspace/work/jobs/<job>/public /tmp/<name>/public
   ```
   or, staying on the server:
   ```
   ssh root@134.209.80.75 'cp -r /root/reels-workspace/work/jobs/<job>/public /tmp/<name>/public'
   ```
   Never write into `/root/reels-workspace/work/jobs/<job>` itself — that folder is a
   live job the bot or a user may still be waiting on.

3. **Swap in the changed file(s).** Copy your locally-edited file over its counterpart
   under `/tmp/<name>/public/...`, matching the path the composition actually loads.

   **Caveat paid for on 2026-09-07:** a file under `public/compositions/components/`
   is not necessarily what executes. The caption component is a case that looks like
   a normal paste-component but isn't: `install()` (`hf_captions.py:169`) fetches it
   into `.hf-captions/` and `stage()` (`hf_captions.py:206`) copies it to
   `public/compositions/components/caption-highlight.html` (`COMPONENT_REL`,
   `hf_captions.py:77`); then `caption_snippet` (`hf_captions.py:226`) lifts its
   script out into a **separate file**, `public/captions.js` (`CAPTION_SCRIPT`,
   `hf_captions.py:223`), and pastes its markup and style straight into `index.html` — because the framework's own
   linter counts physical lines of `index.html` and flags anything over 300
   (`composition_file_too_large`), and the component's script body alone is 608 lines.
   Swapping the file under `compositions/components/` changes nothing that renders;
   for a caption change, swap `public/captions.js` and the pasted block inside
   `public/index.html` instead. Any other paste-position component in the catalog can
   have the same trap — check where `paste_fragment` (`hf_compose.py`) actually put
   the result before assuming the source file under `compositions/components/` is live.

4. **Snapshot at the frames that matter.** From `/tmp/<name>` (or wherever `public`
   sits):
   ```
   npx --yes hyperframes@0.8.27 snapshot public --output snaps --at <t1>,<t2> --no-end
   ```
   `--no-end` skips the automatic end-of-timeline frame so only the times you name get
   captured. Pick times around the seam or state you changed, not just the midpoint —
   a caption fix shows on the frame where the words are on screen, not on an empty
   beat.

5. **Fetch and compare.** Individual frames land as
   `snaps/frame-NN-at-<time>.png`; if you want everything at once, the same run also
   writes a `contact-sheet*.jpg`. Pull whichever you need back to this machine, crop
   the region you care about with ffmpeg if the full frame is too small to judge:
   ```
   ffmpeg -y -i snaps/frame-00-at-12.3.png -vf "crop=iw:300:0:ih-620" crop-after.png
   ```
   (crop coordinates depend on what you're checking — e.g. the caption zone sits
   620px from the bottom at 1080p, see `hf_captions.py:264` for why).
   Compare the before frame (unmodified job) against after (swapped file) side by
   side, or `Read` both images directly — a frame either shows the fix or it doesn't.

## Rules

- **Never modify the job folder itself.** Everything happens in the `/tmp` copy.
- **Never enqueue a job or restart `reels-bot`.** This is inspection, not a rebuild.
- **No paid calls.** No HeyGen render, no ElevenLabs call — the clips and audio in the
  copied job are already rendered; snapshotting composes HTML into a frame locally,
  it doesn't re-order anything.
