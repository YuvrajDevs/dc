#!/usr/bin/env bash
# Boots the API (on a throwaway copy of the demo database) and the dashboard, runs the
# browser acceptance suite, then shuts everything down. Usage: scripts/uat.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-python3}
for port in 3000 8000; do
  if curl -s -o /dev/null "localhost:$port"; then echo "Port $port is already in use. Stop whatever is using it first."; exit 2; fi
done
TMP=$(mktemp -d)
trap 'for f in "$TMP"/*.pid; do kill -- -"$(cat "$f")" 2>/dev/null || true; done; rm -rf "$TMP"' EXIT
DB=${DB:-data/ui/serve.duckdb}
[ -f "$DB" ] || { echo "No demo database at $DB. Run: make demo-ui"; exit 2; }
cp "$DB" "$TMP/serve.duckdb"; [ -f "$DB.wal" ] && cp "$DB.wal" "$TMP/serve.duckdb.wal" || true
setsid $PY -m trueup serve --db "$TMP/serve.duckdb" --port 8000 >"$TMP/api.log" 2>&1 & echo $! >"$TMP/api.pid"
(cd dashboard && [ -d .next ] || npm run build >/dev/null; setsid npx next start -p 3000 >"$TMP/web.log" 2>&1 & echo $! >"$TMP/web.pid")
for i in $(seq 1 60); do curl -sf localhost:8000/api/health >/dev/null && curl -sf localhost:3000 >/dev/null && break; sleep 1; done
node dashboard/e2e/uat.mjs
