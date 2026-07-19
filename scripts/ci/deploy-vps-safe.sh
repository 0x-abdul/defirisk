#!/usr/bin/env bash
set -euo pipefail
repo="$1"; remote="$2"; branch="$3"; cd "$repo"
state_root="${XDG_STATE_HOME:-$repo/.local/state}/riskdashboard/deploy"
old_head="$(git rev-parse HEAD)"; stamp="$(date -u +%Y%m%dT%H%M%SZ)"; run="$state_root/$stamp"
mkdir -p -m 700 "$state_root"; test -O "$state_root"; test -w "$state_root" -a -x "$state_root"
for path in "$state_root" "$repo/data" "$repo/site"; do test "$(stat -c %d "$path")" = "$(stat -c %d "$state_root")" || { echo "cross-device deploy state refused: $path"; exit 1; }; done
mkdir -m 700 "$run"; stage="$run/staging"; backup="$run/backup"; mkdir -m 700 "$stage" "$backup"
manifest="$run/manifest.json"; umask 077
printf '{"old_head":"%s","started_at":"%s","state_root":"%s"}\n' "$old_head" "$(date -u +%FT%TZ)" "$state_root" > "$manifest"; chmod 600 "$manifest"
cp -a site/dist "$backup/site-dist"; cp -a data/api "$backup/api"
rollback() { git reset --hard "$old_head"; rm -rf data/api site/dist; mv "$backup/api" data/api; mv "$backup/site-dist" site/dist; curl -fsS https://defirisk.co/ >/dev/null; }
failed=1; cleanup() { rm -rf "$stage"; if [ "$failed" = 0 ]; then find "$state_root" -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +; fi; }; trap cleanup EXIT
trap 'rollback' ERR
bash scripts/ci/sync-vps-checkout.sh "$repo" "$remote" "$branch"
set -a; . ./.env; set +a; : "${DATABASE_URL:=${LOCAL_DATABASE_URL:-}}"; test -n "$DATABASE_URL"; export DATABASE_URL
py=python3; test -x venv/bin/python && py=venv/bin/python
"$py" scripts/dump.py --out-root "$stage/data"
"$py" - "$stage/data/api/v1.7.0/index.json" <<'PY'
import json,sys
rows=json.load(open(sys.argv[1])).get('data',{}).get('protocols',[])
assert rows, 'empty API index'
PY
. scripts/ci/use-node-22.sh; (cd site; export npm_config_cache="$repo/.npm-cache"; npm ci --prefer-offline; npm run build -- --outDir "$stage/site-dist")
test -f "$stage/site-dist/index.html"; test -f "$stage/data/api/v1.7.0/index.json"
mv data/api "$backup/api-live"; mv "$stage/data/api" data/api; mv site/dist "$backup/site-dist-live"; mv "$stage/site-dist" site/dist
curl -fsS https://defirisk.co/ >/dev/null
printf '{"old_head":"%s","new_head":"%s","completed_at":"%s"}\n' "$old_head" "$(git rev-parse HEAD)" "$(date -u +%FT%TZ)" > "$manifest"; chmod 600 "$manifest"
trap - ERR; failed=0; echo "SAFE_DEPLOY_MANIFEST=$manifest"
