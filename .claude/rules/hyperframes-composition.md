---
paths:
  - "plugins/reels-factory/engine/src/reels_factory/hf_*.py"
  - "plugins/reels-factory/engine/templates/reel.html"
  - "catalog/**"
---

# Composing a reel

Decisions and traps that the composition code itself doesn't state. The mechanics of
the framework live in the clone — see the HyperFrames section of the root `CLAUDE.md`
for where to read them.

## Who decides what

- The agent plans, the code builds. The agent returns exactly two files:
  `storyboard.json` and `frame.md` — the brief says so in `hf_brief.py`.
- The agent writes no HTML, no timeline and no seconds.
- Scene times, montage arithmetic, media, captions and schema forms belong to the code.
  Asking the agent for something the code can derive from the material buys a
  disagreement, not a plan.
- Face occlusion and presenter movement are measured on the rendered composition
  (`hf_probe.py`) — the storyboard is the agent's own account of itself.

## Traps in our own composition, each paid for with rendered frames

- `class="clip"` stays on the presenter `<video>` and on block hosts even though
  `docs/reference/html-schema.mdx` calls it unnecessary for video and their linter skips
  `video`/`audio` — without it the clip never appears. The full note sits above the
  presenter block in `build_composition` (`hf_compose.py`).
- GSAP's `className` plugin restores inline `visibility:hidden`; `_presenter_move`
  switches the PiP class through `attr` instead (`hf_compose.py`).
- A block is a page of its own: its `html,body{background:…}` paints the whole frame, so
  `#stage` carries its own background in `engine/templates/reel.html`.

## Catalog and the pinned CLI

- Our block catalog lives at `catalog/registry` in their layout (`REELS_CATALOG_DIR`
  overrides the path) and is served from `127.0.0.1` by `hf_catalog.py` — their CLI
  fetches a registry over HTTP only (`fetchJson` in
  `packages/cli/src/registry/remote.ts`).
- The CLI version we run is pinned in `hyperframes_blocks.py`, and the clone can sit
  ahead of it. Read capabilities at that tag —
  `git -C C:/Users/123/projects/hyperframes-ref show v<pin>:<path>` — and treat what
  exists only in a newer version as a question about raising the pin.
