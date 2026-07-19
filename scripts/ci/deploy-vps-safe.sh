#!/usr/bin/env bash
set -euo pipefail
repo="$1"; remote="$2"; branch="$3"; cd "$repo"
old_head="$(git rev-parse HEAD)"; stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$repo/.deploy-backups/$stamp"; stage="$(mktemp -d "$repo/.deploy-stage.XXXXXX")"
mkdir -p "$backup"; cp -a site/dist "$backup/site-dist"; cp -a data/api "$backup/api"
restore() { git reset --hard "$old_head"; rm -rf site/dist data/api; mv "$backup/site-dist" site/dist; mv "$backup/api" data/api; }
trap 'restore' ERR
git fetch "$remote" "$branch"; git reset --hard FETCH_HEAD; git clean -fd -e .env -e .deploy-backups
set -a; . ./.env; set +a; : "${DATABASE_URL:=${LOCAL_DATABASE_URL:-}}"; test -n "$DATABASE_URL"; export DATABASE_URL
py=python3; test -x venv/bin/python && py=venv/bin/python
"$py" scripts/dump.py --out-root "$stage/data"
"$py" - "$stage/data/api/v1.7.0/index.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1])); rows=p.get('data',p).get('protocols',[])
assert rows and len(rows)>0, 'empty API index'
PY
. scripts/ci/use-node-22.sh; (cd site; export npm_config_cache="$repo/.npm-cache"; npm ci --prefer-offline; npm run build -- --outDir "$stage/site-dist")
test -f "$stage/site-dist/index.html"; test -f "$stage/data/api/v1.7.0/index.json"
mv data/api "$backup/api-live"; mv "$stage/data/api" data/api; mv site/dist "$backup/site-dist-live"; mv "$stage/site-dist" site/dist
trap - ERR
echo "SAFE_DEPLOY_HEAD=$(git rev-parse HEAD) BACKUP=$backup"
