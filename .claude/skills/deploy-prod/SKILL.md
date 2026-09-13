---
name: deploy-prod
description: Deploy the current main to the production bot at root@134.209.80.75 — pull, conditionally reinstall the SDK bridge, run the real test suite, and restart the service without touching an in-flight job. Only trigger this by explicit name (/deploy-prod); a code fix landing on main does not by itself mean it should go out.
disable-model-invocation: true
---

# Deploy-prod

Prod is `root@134.209.80.75`, deployed by hand over SSH — no CI, no cron, no webhook.
Code sits in `/root/reels-factory` on `main`; the engine is an editable install, so a
`git pull` changes running code immediately and nothing needs reinstalling by itself.
This is the one place that procedure lives — do not duplicate these steps elsewhere.

## Before pulling

Record the commit you're leaving, so a bad deploy has something to roll back to:
```
ssh root@134.209.80.75 'cd /root/reels-factory && git rev-parse HEAD'
```

## 0. Skills and settings for the service profile, BEFORE the code that reads them

**Order is not optional here.** `hf_assets.py`, `hf_fonts.py` and `hf_media.py` read
the skill warehouse from `SKILL_PROFILE_DIR/skills` (`llm.py:19`) — the service
profile, not the personal profile of the user on the box. The moment the pulled code
lands, those three reads point at the new path. If the skills aren't there yet, the
build doesn't fail the deploy itself — pytest doesn't exercise the real files any
more than it did before — it breaks the next real job on prod, quietly, hours later.
**Run this step first, verify it, and only then pull.** Skip it only when neither
`plugins/reels-factory/agent-profile/settings.json` nor the skill set changed since
the last deploy.

Copy the tracked settings (destructive-command denials only — no path rules; a path
rule from a neighboring project is exactly what took prod down on 22.08, see
`test_llm.py:16-49`):
```
scp plugins/reels-factory/agent-profile/settings.json root@134.209.80.75:/root/.reels-factory/claude/settings.json
```
Install/update the skill warehouse into the service profile — `CLAUDE_CONFIG_DIR` is
what routes the installer there instead of `/root/.claude` (the CLI itself resolves
`claudeHome` from it, `skillsMirror.ts:165` in the hyperframes-ref clone), so it must
be set on this exact command, not assumed from a previous session:
```
ssh root@134.209.80.75 'CLAUDE_CONFIG_DIR=/root/.reels-factory/claude npx --yes hyperframes@<pin from hyperframes_blocks.py _HF_VERSION> skills update talking-head-recut'
```
One skill name is enough — the installer resolves and copies the whole related set
(`embedded-captions`, `media-use`, the `hyperframes-*` route skills) in one pass, not
just the one named.

Verify before touching code — the three names the engine actually reads from disk:
```
ssh root@134.209.80.75 'ls /root/.reels-factory/claude/skills | grep -E "^(talking-head-recut|embedded-captions|media-use)$"'
```
All three must print. Anything missing → re-run the install above before proceeding;
do not pull code ahead of this.

## 1. Pull

```
ssh root@134.209.80.75 'cd /root/reels-factory && git pull --ff-only'
```
`git pull` sets `ORIG_HEAD` to the commit you just recorded — that's what a rollback
resets to.

## 2. Reinstall the SDK bridge only if its lock file moved

The bridge (`scripts/hf_sdk.mjs`) loads `@hyperframes/sdk` from `node_modules`; a pull
alone leaves the old package installed there. Check whether the pull actually touched
the lock file before paying for `npm ci`:
```
ssh root@134.209.80.75 "cd /root/reels-factory && git diff --name-only \$(git rev-parse ORIG_HEAD) HEAD -- plugins/reels-factory/engine/package-lock.json"
```
Non-empty output → run it:
```
ssh root@134.209.80.75 'cd /root/reels-factory/plugins/reels-factory/engine && npm ci'
```
The CLI itself needs nothing installed: `npx` fetches `hyperframes@<pin>` on first use.

## 3. Run the real test suite, without blocking the SSH session

A test run backgrounded the naive way still ties up the SSH connection (the shell
waits for the child's stdout to close). Detach it fully so the command returns
immediately and you poll separately:
```
ssh root@134.209.80.75 'cd /root/reels-factory/plugins/reels-factory/engine && nohup .venv/bin/python -m pytest -q -m "not slow" > /tmp/deploy-test.out 2>&1 < /dev/null & disown'
```
Then poll rather than sleeping blind:
```
ssh root@134.209.80.75 'for i in $(seq 1 30); do grep -qE "passed|failed" /tmp/deploy-test.out && break; sleep 10; done; tail -5 /tmp/deploy-test.out'
```
**Red means stop here — leave the running service alone.** Roll back the pull:
```
ssh root@134.209.80.75 'cd /root/reels-factory && git reset --hard ORIG_HEAD'
```
and, if step 2 ran, reinstall against the rolled-back lock file before reporting the
failure.

## 4. Restart, only once nothing is mid-job

The bot's databases (`work/{billing,jobs,events}.sqlite3`) are not in git and have no
backup — restarting mid-render doesn't lose the database, but it does orphan whatever
job was running. Check before restarting:
```
ssh root@134.209.80.75 "sqlite3 /root/reels-workspace/work/jobs.sqlite3 \"select job_id, status from build_jobs where status in ('audio_queued','audio_running','awaiting_audio_approval','awaiting_user_audio','user_audio_processing','queued','running');\""
```
Empty result → restart:
```
ssh root@134.209.80.75 'systemctl restart reels-bot && sleep 3 && systemctl is-active reels-bot'
```
Non-empty result → wait and re-check rather than restarting under an active job; there
is no queue-drain flag to force this, so this is a judgment call, not automatable.

## Leave alone

Nothing under `/root/.reels-factory/bot.env` (the HeyGen/ElevenLabs keys, service-
owned) or `/root/reels-workspace/work/{billing,jobs,events}.sqlite3` (user balances,
no backup) is in git and none of it should be touched by a deploy.
