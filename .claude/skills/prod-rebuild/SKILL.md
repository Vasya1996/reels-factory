---
name: prod-rebuild
description: Rebuild a finished job through the real bot queue, for free, on a frozen avatar order — a copy of a job re-runs the whole montage pipeline without buying the presenter again. Only trigger this by explicit name (/prod-rebuild); it is not for "just check if this works", which is `/snapshot-check`.
disable-model-invocation: true
---

# Prod-rebuild

The avatar order is the expensive, irreversible part of a job — HeyGen has already
been paid and the clips downloaded. Everything after that (montage, gates, contact
sheet, render, loudness) runs on our own machine from material already on disk. This
skill re-runs exactly that part, through the bot's real queue, on a copy of a
finished job, so a fix gets seen end to end without a second HeyGen bill.

Prefer `/snapshot-check` when the change can be judged from a handful of frames —
it's faster and free of the one paid step below. Reach for this skill when the change
needs to be seen through a full render (pacing, audio, every seam), or when it can't
be isolated to a few frames.

## Cost

- No HeyGen render, no ElevenLabs call — the avatar clips and voice are already on
  disk and stay frozen.
- One `claude -p` agent session per rebuild — the pipeline still calls the planning
  agent when it re-derives the montage. This is the one real cost; budget for it.

## Steps

All of this runs over SSH on `root@134.209.80.75`, working directory
`/root/reels-workspace`.

1. **Pick a source job.** Any job under `work/jobs/<src>` that finished (or at least
   got through `prepare` and `plan`) has a frozen avatar order — clips, plan, and the
   files that guard against re-ordering the presenter
   (`avatar_render_plan.json`, `avatar_render_manifest.json`, `edit_plan.json`).

2. **Copy it to a new job id.**
   ```
   cp -a work/jobs/<src> work/jobs/<new>
   cd work/jobs/<new>
   ```

3. **Reset every stage marker except the one that freezes the avatar order.** Markers
   are files named `.hf-<step>.done` (`_marker` in `hf_render.py:110`). Remove all of
   them **except** `.hf-plan-early.done` — including `.hf-prepare.done`, so the
   composition's pasted components get reinstalled fresh rather than reused stale:
   ```
   find . -maxdepth 1 -name '.hf-*.done' ! -name '.hf-plan-early.done' -delete
   rm -f retry_reason.txt reel.mp4 reel.raw.mp4
   ```
   `.hf-plan-early.done` is what tells the pipeline "the plan in `plan.json` is the
   one HeyGen was already paid to render" (`EARLY_PLAN_STEP`, `hf_render.py:96`) —
   removing it would make the pipeline re-ask the planning agent for a fresh plan
   that no longer matches the ordered clips, and there is no way to get that money
   back. Leave it alone.

4. **Rewrite `job.input.json`** so the copy has its own identity instead of the
   source job's:
   ```python
   import json
   p = "job.input.json"
   d = json.load(open(p, encoding="utf-8"))
   d["job_id"] = "<new>"
   d["user_id"] = 823757031  # default test chat; ask Vasya before using another
   json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
   ```

5. **Enqueue it through the real `JobStore`**, using the engine's own venv so the
   installed package versions match what the running bot uses:
   ```
   plugins/reels-factory/engine/.venv/bin/python -c "
   from reels_factory.jobs import JobStore
   store = JobStore('work/jobs.sqlite3', 'work/jobs')
   store.enqueue_prepared(
       823757031,
       job_id='<new>',
       workdir='work/jobs/<new>',
       initial_status='queued',
       initial_stage='rebuild',
   )
   "
   ```

6. **Restart the bot only if nothing else is active.** The worker picks up queued
   jobs on its own poll loop, but if it's stuck or you need it to notice immediately:
   check first —
   ```
   sqlite3 work/jobs.sqlite3 "select job_id, status from build_jobs where status in ('audio_queued','audio_running','awaiting_audio_approval','awaiting_user_audio','user_audio_processing','queued','running');"
   ```
   Restart only when the only active row is the one you just enqueued (or the table
   is otherwise idle) — restarting mid-job on someone else's build orphans it.
   ```
   systemctl restart reels-bot
   ```

7. **Wait, by polling, not by sleeping blind.** Poll `jobs.sqlite3` for the row's
   `status` to leave the active set (`select status from build_jobs where job_id =
   '<new>'`), rather than guessing a fixed wait — montage time varies with scene
   count.

8. **Fetch the result.**
   ```
   scp root@134.209.80.75:/root/reels-workspace/work/jobs/<new>/snapshots/contact-sheet-*.jpg .
   scp root@134.209.80.75:/root/reels-workspace/work/jobs/<new>/reel.mp4 .
   scp root@134.209.80.75:/root/reels-workspace/work/jobs/<new>/plan.json .
   scp root@134.209.80.75:/root/reels-workspace/work/jobs/<new>/gates.json .
   ```
   Then judge it — see `/judge-reel` for what to look at in the plan, the gates, and
   the frames rather than trusting a green gate file alone.
