---
name: judge-reel
description: Judge a built reel by looking at its actual frames, not by trusting a green gates.json. Use whenever a job has just finished (from `/prod-rebuild` or a real user build) and needs acceptance — "a reel was built, judge it by frames, not gates", "check this build", "is this reel good".
---

# Judge-reel

A gate is a check someone wrote for a defect someone already saw once. It says
nothing about the defect nobody wrote a check for yet — and every defect class below
was first found by looking, not by a gate. Judging a reel means looking at it.

## 1. Fetch the artefacts

```
scp root@134.209.80.75:/root/reels-workspace/work/jobs/<job>/plan.json .
scp root@134.209.80.75:/root/reels-workspace/work/jobs/<job>/gates.json .
scp root@134.209.80.75:/root/reels-workspace/work/jobs/<job>/snapshots/contact-sheet-*.jpg .
scp root@134.209.80.75:/root/reels-workspace/work/jobs/<job>/reel.mp4 .
```

## 2. Print the plan summary

For each scene in `plan.json`, read: `id` (e.g. `s-01`), `presenter` (one of
`PRESENTER_POSITIONS`, `hf_layout.py:65`: `full` / `punch` / `pip-tr` / `pip-tl` / `pip-br` /
`pip-bl` / `stack` / `none`), `elements`, `schema.form` if present,
`insert.kind` if present, and `frame.holder` if present. This is the fastest way to
see the shape of the whole reel before looking at a single pixel — a plan that is all
one `presenter` value or all one `schema.form` is worth a second look before you even
render.

## 3. List gates that are not PASS

`gates.json` is `{"D##_name": "PASS" | "FAIL: reason"}`. Print only the entries that
aren't `PASS` — a gate failure is a real defect and the fastest one to find, but it is
the floor, not the ceiling, of what to check.

## 4. Look at the contact sheets

The contact sheet already samples the midpoint of every scene plus a couple of frames
around each cut (`_snapshot_times`, `hf_render.py:840`) — that's the first look, not
the whole one.

## 5. Cut a frame strip around anything suspicious

For a specific second range that looks off on the contact sheet or in the plan
summary, pull a denser strip:
```
ffmpeg -y -ss <start> -to <end> -i reel.mp4 -vf "fps=2.5,scale=270:480,tile=8x1" strip.jpg
```
Adjust `fps` for how fast the suspicious thing moves — a clipped word needs a denser
sample than a static schema.

## 6. Defect classes seen this week — check for each, don't wait to stumble on them

- An element (schema, icon, insert) drawn over the presenter's face.
- An empty frame — a holder that never got filled.
- Unreadable text — contrast, size, or a caption crossing a busy background.
- A wrong number surfacing in an on-screen figure.
- A clipped word — a caption or title cut at a frame boundary.
- A static schema where the plan called for motion (or vice versa).
- An icon placeholder that was never replaced with real content.
- Monotony — one `schema.form`, one `presenter` value, or one background repeated
  across most scenes when the plan summary from step 2 already made this visible.

A build that passes every gate and matches none of these is not yet "good" — it's
"not caught". The judgment is still the frames.
