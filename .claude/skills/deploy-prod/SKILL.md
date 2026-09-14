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

The eleven names the `/hyperframes` route depends on (from `skills/hyperframes/SKILL.md`
in the clone, not memory): `hyperframes`, `hyperframes-animation`, `hyperframes-audio`,
`hyperframes-cli`, `hyperframes-core`, `hyperframes-creative`, `hyperframes-keyframes`,
`hyperframes-registry`, `media-use`, `embedded-captions`, `talking-head-recut`.

**0a. Find every agent skill store on the box — don't assume there are two.** Measured
13.09.2026 on the dev machine: three agent skill stores were live at once
(`~/.claude`, `~/.agents`, `~/.copilot`). Which one of several populated stores the
installer actually treats as "already current" wasn't isolated — only that with
stores populated, nothing lands in the service profile (see 0c), and clearing all of
them is what got skills to land. Check the box itself, every time, rather than
assuming which stores exist:
```
ssh root@134.209.80.75 'for d in /root/.claude/skills /root/.agents/skills /root/.copilot/skills /root/.codex/skills /root/.vibe/skills; do [ -d "$d" ] && echo "$d"; done'
```
Checked on prod 13.09.2026: only `/root/.claude/skills` (70 names) and
`/root/.agents/skills` (25 names) exist; `.copilot`, `.codex`, `.vibe` don't. That can
change — always look, never paste "the usual two" from memory.

**0b. Copy the tracked settings** (destructive-command denials only — no path rules; a
path rule from a neighboring project is exactly what took prod down on 22.08, see
`test_llm.py:16-49`):
```
scp plugins/reels-factory/agent-profile/settings.json root@134.209.80.75:/root/.reels-factory/claude/settings.json
```

**0c. Pull the eleven names out of every store `0a` found — into a dated reserve, not
gone.** Clear all of them, not because each one's guilt is individually established —
it isn't. Measured 13.09.2026, twice: with stores still populated, the install prints
"already up to date" and lists every requested name as "Ready" while placing nothing
in the service profile. Measured once: after every found store was cleared, the next
install placed skills immediately. Which store (or combination) the installer was
actually reading as "current" in each run was never isolated — the runs also differed
in whether a store was emptied entirely or just had these eleven names pulled out of
it, so the two observations don't pin the mechanism down, only the outcome. `checkSkills`
/ `discoverSkillRoots` in `skillsManifest.ts` do confirm, from the source, that this
scan runs over `$HOME`'s agent directories and never enters `CLAUDE_CONFIG_DIR` — which
is why the service profile can never win that comparison on its own — but treat that as
background for *why a scan like this exists*, not as a proven account of any one run
above. Clearing every found store is the reliable move because isolating "the" culprit
wasn't achieved and 0e's factual check is the real backstop regardless. Removing the
competing copies isn't destructive here — reserve them so a bad outcome is a `mv` away
from undone:
```
ssh root@134.209.80.75 'RESERVE=/root/.reels-factory/skills-reserve/$(date +%Y%m%d-%H%M%S)
mkdir -p "$RESERVE"
NAMES="hyperframes hyperframes-animation hyperframes-audio hyperframes-cli hyperframes-core hyperframes-creative hyperframes-keyframes hyperframes-registry media-use embedded-captions talking-head-recut"
for store in /root/.claude/skills /root/.agents/skills /root/.copilot/skills /root/.codex/skills /root/.vibe/skills; do
  [ -d "$store" ] || continue
  dest="$RESERVE/$(basename "$(dirname "$store")")"
  mkdir -p "$dest"
  for name in $NAMES; do [ -e "$store/$name" ] && mv "$store/$name" "$dest/"; done
done
echo "reserved under $RESERVE"'
```

**0d. Install into the service profile** — `CLAUDE_CONFIG_DIR` is what routes the
installer there instead of `/root/.claude` (the CLI itself resolves `claudeHome` from
it, `skillsMirror.ts:165` in the clone), so it must be set on this exact command:
```
ssh root@134.209.80.75 'CLAUDE_CONFIG_DIR=/root/.reels-factory/claude npx --yes hyperframes@<pin from hyperframes_blocks.py _HF_VERSION> skills update hyperframes hyperframes-animation hyperframes-audio hyperframes-cli hyperframes-core hyperframes-creative hyperframes-keyframes hyperframes-registry media-use embedded-captions talking-head-recut'
```

**0e. Trust the file listing, never the installer's own words.** Measured 13.09.2026:
with a competing store still in play, this same command printed "Installed skills are
already up to date" and listed all eleven requested names under "Ready" — while
placing nothing at all in the service profile. "Ready" names a request, not a
delivery. The only trustworthy check is looking at the target directory itself:
```
ssh root@134.209.80.75 'comm -23 <(printf "%s\n" hyperframes hyperframes-animation hyperframes-audio hyperframes-cli hyperframes-core hyperframes-creative hyperframes-keyframes hyperframes-registry media-use embedded-captions talking-head-recut | sort) <(ls /root/.reels-factory/claude/skills | sort)'
```
Empty output → all eleven are present. It checks presence only, not content — a stale
copy would pass this the same as a fresh one; that's a pre-existing limit of this
check, not a new one, worth knowing before you trust a green result.

**0f. One pass rarely finishes it — repeat, don't improvise.** Measured 13.09.2026:
naming all eleven in one command reliably delivered only the nine the installer treats
as core (the `hyperframes-*` names plus `media-use`) — `embedded-captions` and
`talking-head-recut` needed a second, separate run naming just the still-missing
names before they landed. Which names arrive on which pass isn't something to predict
or design around: re-run `0d` with whatever `0e` still shows missing, re-check, and
repeat until `0e` prints nothing.

**0g. If it never converges, stop — don't deploy code on a partial skill set.** Restore
the reserve from `0c` (`mv` each name back from `$RESERVE/<store-basename>/` to its
original store) and treat this as a real installer problem to investigate, not
something to route around with a fresh trick. Nothing past this point runs until `0e`
is clean.

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
job was running. Check before restarting. `sqlite3` is not installed on the box
(measured 14.09.2026: `bash: sqlite3: command not found`) — go through `python3`'s
stdlib module instead:
```
ssh root@134.209.80.75 "python3 -c \"import sqlite3; print(sqlite3.connect('/srv/reels-workspace/work/jobs.sqlite3').execute(\\\"select job_id, status from build_jobs where status in ('audio_queued','audio_running','awaiting_audio_approval','awaiting_user_audio','user_audio_processing','queued','running')\\\").fetchall())\""
```
Empty result → restart:
```
ssh root@134.209.80.75 'systemctl restart reels-bot && sleep 3 && systemctl is-active reels-bot'
```
Non-empty result → wait and re-check rather than restarting under an active job; there
is no queue-drain flag to force this, so this is a judgment call, not automatable.

## Leave alone

Nothing under `/root/.reels-factory/bot.env` (the HeyGen/ElevenLabs keys, service-
owned) or `/srv/reels-workspace/work/{billing,jobs,events}.sqlite3` (user balances,
no backup) is in git and none of it should be touched by a deploy.

The workspace moved from `/root/reels-workspace` to `/srv/reels-workspace` on
14.09.2026; the service's `WorkingDirectory` follows the new path. The compatibility
symlink at the old place was removed the same day — `/root/reels-workspace` no longer
exists, so any command still carrying that prefix simply fails.
