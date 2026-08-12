#!/usr/bin/env bash
# Локальный HTTP-реестр golden-catalog для HyperFrames CLI.
# CLI берёт реестр только по HTTP (packages/cli/src/registry/remote.ts:96 — fetch(baseUrl + "/registry.json")),
# file:// и файловый путь не работают.
#
#   ./serve.sh [порт]        # по умолчанию 8787
#
# В hyperframes.json проекта:
#   { "registry": "http://127.0.0.1:8787" }
set -euo pipefail
PORT="${1:-8787}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "golden-catalog registry → http://127.0.0.1:${PORT}  (dir: ${DIR})"
exec python3 -m http.server "${PORT}" --bind 127.0.0.1 --directory "${DIR}"
