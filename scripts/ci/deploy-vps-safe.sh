#!/usr/bin/env bash
set -euo pipefail

repo="$1"; remote="$2"; branch="$3"; cd "$repo"
state_root="${XDG_STATE_HOME:-$repo/.local/state}/riskdashboard/deploy"
old_head="$(git rev-parse HEAD)"; stamp="$(date -u +%Y%m%dT%H%M%SZ)"; run="$state_root/$stamp"
mkdir -p -m 700 "$state_root"; test -O "$state_root"; test -w "$state_root" -a -x "$state_root"
for path in "$state_root" "$repo/data" "$repo/site"; do test "$(stat -c %d "$path")" = "$(stat -c %d "$state_root")" || { echo "cross-device deploy state refused: $path"; exit 1; }; done
mkdir -m 700 "$run"; stage="$run/staging"; backup="$run/backup"; mkdir -m 700 "$stage" "$backup"
manifest="$run/manifest.json"; umask 077

tree_digest() { (cd "$1" && find . -type f -print0 | sort -z | xargs -0 -r sha256sum) | sha256sum | awk '{print $1}'; }
api_before="$(tree_digest data/api)"; dist_before="$(tree_digest site/dist)"
write_manifest() {
  MANIFEST="$manifest" STATE="$1" OLD_HEAD="$old_head" TARGET_HEAD="${target_head:-}" API_BEFORE="$api_before" DIST_BEFORE="$dist_before" API_AFTER="${api_after:-}" DIST_AFTER="${dist_after:-}" BACKUP="$backup" STAGE="$stage" python3 - <<'PY'
import json, os, tempfile
path=os.environ['MANIFEST']; payload={
  'state':os.environ['STATE'], 'old_head':os.environ['OLD_HEAD'], 'target_head':os.environ['TARGET_HEAD'],
  'api_before_sha256':os.environ['API_BEFORE'], 'site_dist_before_sha256':os.environ['DIST_BEFORE'],
  'api_after_sha256':os.environ['API_AFTER'], 'site_dist_after_sha256':os.environ['DIST_AFTER'],
  'backup':os.environ['BACKUP'], 'staging':os.environ['STAGE'], 'updated_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
}
fd,tmp=tempfile.mkstemp(prefix='.manifest.',dir=os.path.dirname(path)); os.fchmod(fd,0o600)
with os.fdopen(fd,'w') as f: json.dump(payload,f,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.replace(tmp,path); os.chmod(path,0o600)
PY
}
rolling_back=0
backups_ready=0
rollback() {
  code="${1:-1}"; if [ "$rolling_back" = 1 ]; then exit "$code"; fi; rolling_back=1; trap - ERR HUP INT TERM
  set +e
  if [ "$backups_ready" != 1 ]; then write_manifest rollback_failed || true; exit "$code"; fi
  write_manifest promoting || true
  git reset --hard "$old_head"
  rm -rf data/api site/dist
  mv "$backup/original-api" data/api
  mv "$backup/original-site-dist" site/dist
  restored=0
  test "$(git rev-parse HEAD)" = "$old_head" && test "$(tree_digest data/api)" = "$api_before" && test "$(tree_digest site/dist)" = "$dist_before" && curl -fsS https://defirisk.co/ >/dev/null && restored=1
  if [ "$restored" = 1 ]; then write_manifest rolled_back; else write_manifest rollback_failed; fi
  exit "$code"
}
cleanup() { rm -rf "$stage"; }
prune_verified_successes() {
  "$py" - "$state_root" "$run" <<'PY'
import json, pathlib, shutil, sys, time
root, current = map(pathlib.Path, sys.argv[1:])
cutoff = time.time() - 14 * 24 * 60 * 60
for candidate in root.iterdir():
    try:
        if candidate == current or not candidate.is_dir() or candidate.stat().st_mtime >= cutoff:
            continue
        with (candidate / "manifest.json").open(encoding="utf-8") as manifest:
            if json.load(manifest).get("state") != "succeeded":
                continue
        shutil.rmtree(candidate)
    except Exception:
        print("retention warning; preserved deployment state", file=sys.stderr)
PY
}
trap cleanup EXIT
trap 'rollback $?' ERR
trap 'rollback 128' HUP INT TERM
write_manifest staging
cp -a data/api "$backup/original-api"; cp -a site/dist "$backup/original-site-dist"
test "$(tree_digest "$backup/original-api")" = "$api_before"; test "$(tree_digest "$backup/original-site-dist")" = "$dist_before"; backups_ready=1

bash scripts/ci/sync-vps-checkout.sh "$repo" "$remote" "$branch"; target_head="$(git rev-parse HEAD)"
set -a; . ./.env; set +a; : "${DATABASE_URL:=${LOCAL_DATABASE_URL:-}}"; test -n "$DATABASE_URL"; export DATABASE_URL
py=python3; test -x venv/bin/python && py=venv/bin/python
dump_log="$run/dump.log"; "$py" scripts/dump.py --out-root "$stage/data" | tee "$dump_log"
policy="scripts/ci/deploy-publication-policy.json"
"$py" scripts/ci/validate-staged-published-api.py --api-root "$stage/data/api/v1.7.0" --policy "$policy"
"$py" scripts/ci/verify-deployment-publication-state.py --policy "$policy" --dump-log "$dump_log"
. scripts/ci/use-node-22.sh; (cd site; export npm_config_cache="$repo/.npm-cache" DEFIRISK_API_ROOT="$stage/data/api/v1.7.0" DEFIRISK_DIST_ROOT="$stage/site-dist"; npm ci --prefer-offline; npm run build -- --outDir "$stage/site-dist")
test -f "$stage/site-dist/index.html"; test -f "$stage/site-dist/api/v1.7.0/index.json"
"$py" scripts/ci/smoke-staged-deploy.py --dist-root "$stage/site-dist" --api-root "$stage/data/api/v1.7.0"
test "$(tree_digest data/api)" = "$api_before"; test "$(tree_digest site/dist)" = "$dist_before"
write_manifest promoting
mv data/api "$backup/pre-promotion-api"; test "${SAFE_DEPLOY_FAIL_AT:-}" != after_api_rename
mv "$stage/data/api" data/api; test "${SAFE_DEPLOY_FAIL_AT:-}" != after_api_promote
mv site/dist "$backup/pre-promotion-site-dist"; test "${SAFE_DEPLOY_FAIL_AT:-}" != after_dist_rename
mv "$stage/site-dist" site/dist; test "${SAFE_DEPLOY_FAIL_AT:-}" != after_dist_promote
api_after="$(tree_digest data/api)"; dist_after="$(tree_digest site/dist)"; curl -fsS https://defirisk.co/ >/dev/null; test "${SAFE_DEPLOY_FAIL_AT:-}" != after_smoke
write_manifest succeeded
trap - ERR HUP INT TERM
set +e
rm -rf "$backup/original-api" "$backup/original-site-dist" || printf '%s\n' 'cleanup warning; retained successful deployment state' >&2
prune_verified_successes || printf '%s\n' 'retention warning; retained successful deployment state' >&2
echo "SAFE_DEPLOY_MANIFEST=$manifest"
