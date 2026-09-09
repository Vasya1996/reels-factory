---
paths:
  - "plugins/reels-factory/.claude-plugin/plugin.json"
  - ".claude-plugin/marketplace.json"
  - "plugins/reels-factory/engine/pyproject.toml"
---

# Version

- Bump when cutting a release.
- Three files carry it: `plugins/reels-factory/.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`, `plugins/reels-factory/engine/pyproject.toml`.
- They drift apart in practice. Realign them with the next release, not as a change
  of their own.
