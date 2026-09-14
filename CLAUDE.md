# reels-factory

A multi-user Telegram bot that makes vertical reels. The main build route is driven by
the HyperFrames framework — its route and skills, its engine, SDK and block registry;
our code writes the brief and does the arithmetic: seconds, geometry, file picking,
captions, composing the composition. The second route is the fast one, no montage: a
single HeyGen pass. Our own skills cover the text side: the script and its review. The
HeyGen and ElevenLabs keys are the service's, one set in `/root/.reels-factory/bot.env`.

Nothing is installed from a marketplace — this clone is the only working copy, and
plugin skills load from its source.

## Where an answer comes from

Two stores answer everything here: this repo for our behaviour, the clone
C:\Users\123\projects\hyperframes-ref for HyperFrames. One of them, never recall,
says how the service behaves; a plan and a change both start there. A summary
without a file and a line is not an opened file.
Write to memory: decisions with their reason, working rules, measurements and
traps paid for with real runs, what was rejected and why, and addresses of
outside sources. Anything derivable from the code stays in the code.

## Commands

- Engine tests: `python -m pytest -m "not slow"` from `plugins/reels-factory/engine`,
  **from Windows, never from WSL**. `slow` means network, ffmpeg or a model download;
  one of those tests also needs the `claude` CLI.
- Run the plugin from source: `claude --plugin-dir plugins/reels-factory`
- Pick up skill edits without restarting: `/reload-plugins`

## Git

- Work in `feat/vasya-<task>`; `main` moves only through a merged PR.
- A change of engine behaviour lands with its test in the same commit.
- Tests green → commit to the branch, describe the diff in plain words, wait for "ok".
  Push and open the PR once "ok" comes.
- **IMPORTANT: run git from Windows.** Under WSL `git status` reports two dozen changed
  files, and that is line endings, not edits.
- A worktree lives in `.worktrees/<branch-slug>` (`feat/vasya-x` → `.worktrees/feat-vasya-x`),
  or in `.claude/worktrees/<name>` for an agent started with `isolation: "worktree"` — both
  inside this clone, never beside it in `projects/`: a sibling folder reads as a separate
  project from the outside.
- Several `fixer` agents at once take different files and different branches; the second and
  later ones are started with `isolation: "worktree"` on the call.
- After a PR is merged, whoever merged it runs `git worktree remove` on its worktree and
  `git branch -d` on its branch — otherwise worktrees pile up.
- An engine/bot change reaches `fixer` as a brief with a `## Razbor` section. Reviews go to
  the `reviewer` subagent. For a composition change the fixer takes the `/snapshot-check`
  frame in its own context and cites it in the PR; the reviewer judges the frame. Rebuild
  through the service only with `/prod-rebuild`.
- `.claude/skills/*` are procedures for the main session and its agents;
  `plugins/reels-factory/skills/*` are what the engine hands to its own build agents.

## HyperFrames — the external framework

Single source: the clone `C:\Users\123\projects\hyperframes-ref`, from
`github.com/heygen-com/hyperframes`. The site renders the same `docs/`; the clone adds
their skills, the SDK and engine sources, and the block registry. The `heygen` CLI
install page is the one thing that lives outside it (https://developers.heygen.com/cli).

- Work with the state of the clone that is checked out. When an answer would need a
  newer one, say so and let Vasya decide when it moves.
- Look in three places before designing: `skills/*/SKILL.md` for what the framework
  already does end to end, `docs/developers/` with `packages/sdk/src` for what the SDK
  exposes, `registry/` for blocks and components already built. Found it — use it
  as is; extend theirs where it falls short. Write our own only when all three come up
  empty, and leave a line beside it saying what was looked for and why it didn't fit.
- Green gates are not a good frame. Judge the result from rendered frames.

<!-- Maintainer note: keep their mechanics out of this file — link to the clone instead.
     This file holds what their files don't: our decisions and traps paid for with
     rendered frames. Content that only matters for some files belongs in
     .claude/rules/*.md with a paths: header — those load when a matching file is
     read, so this file must not point at them. -->

## Local runs

- `hyperframes` runs on Windows through `npx` (`_cli` in `hf_render.py`).
- The `heygen` CLI has no Windows build, so media search runs under `wsl -d Ubuntu`.
  The code just calls `heygen` (`search_assets` in `hf_media.py`) — supplying the WSL
  layer is the caller's job. `resolve` is not that CLI: it runs `node resolve.mjs`
  (`hf_media.py`) and works from Windows. Logging that CLI in is Vasya's to run — hand
  him the command, never enter the key.
- Call WSL through the PowerShell tool.
- Put variables, loops and quoting into a `.sh` file and run that: in a WSL command
  string the layer before bash eats `$VAR` substitution.
- faster-whisper fails on cuda (missing cublas) and falls back to cpu — expected
  behaviour, leave it as it is.

## Money and results

- **IMPORTANT: test hypotheses by re-cutting the clips already downloaded into
  `C:\Users\123\Videos\Reels\work\*\public\avatar_*.mp4`.** Every HeyGen render costs money, so
  a new one is worth asking about first.
- Finished reels go to `C:\Users\123\Videos\Reels` under a descriptive name; everything
  under `work/` is scratch.
- The workspace is internal: end users go through the Telegram bot, and the bot must
  deliver the finished reel into the chat as the final result.

## Deployment

Prod is `root@134.209.80.75`, deployed by hand over SSH — no CI, no cron, no webhook.
The procedure lives in one place: `/deploy-prod`.

Leave alone what is not in git: `/root/.reels-factory/bot.env` and
`/srv/reels-workspace/work/{billing,jobs,events}.sqlite3` — the databases hold user
balances and have no backup.
