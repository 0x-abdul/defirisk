#!/usr/bin/env bash
set -euo pipefail

repo="$1"; remote="$2"; branch="$3"; cd "$repo"
state_root="${XDG_STATE_HOME:-$repo/.local/state}/riskdashboard/deploy"
old_head="$(git rev-parse HEAD)"; stamp="$(date -u +%Y%m%dT%H%M%SZ)"; run="$state_root/$stamp"
mkdir -p -m 700 "$state_root" >/dev/null 2>&1 || { printf '%s\n' 'ERROR: deployment state unavailable' >&2; exit 1; }
test -O "$state_root"; test -w "$state_root" -a -x "$state_root"
for path in "$state_root" "$repo/data" "$repo/site"; do test "$(stat -c %d "$path" 2>/dev/null)" = "$(stat -c %d "$state_root" 2>/dev/null)" || { printf '%s\n' 'ERROR: cross-device deploy state refused' >&2; exit 1; }; done
mkdir -m 700 "$run" >/dev/null 2>&1 || { printf '%s\n' 'ERROR: deployment state unavailable' >&2; exit 1; }
stage="$run/staging"; backup="$run/backup"; mkdir -m 700 "$stage" "$backup" >/dev/null 2>&1 || { printf '%s\n' 'ERROR: deployment state unavailable' >&2; exit 1; }
manifest="$run/manifest.json"; umask 077
stage_worktree="$stage/repo"; stage_worktree_ready=0
runtime_excludes=( ':(exclude)data/api/**' ':(exclude)site/dist/**' )

tree_digest() {
  test -d "$1" || { printf '%s\n' 'ERROR: deployment artifact digest unavailable' >&2; return 1; }
  (cd "$1" && find . -type f -print0 | sort -z | xargs -0 -r sha256sum) 2>/dev/null | sha256sum | awk '{print $1}'
}
remove_added_code_paths() {
  local base="$1" newer="$2" path_list="$run/code-paths"
  git -C "$repo" diff --name-only -z --diff-filter=A "$base" "$newer" -- . "${runtime_excludes[@]}" >"$path_list" 2>/dev/null || return 1
  while IFS= read -r -d '' path; do
    git -C "$repo" rm --cached --ignore-unmatch -- "$path" >/dev/null 2>&1 || return 1
    rm -f -- "$path" >/dev/null 2>&1 || return 1
  done <"$path_list"
}
added_code_paths_absent() {
  local base="$1" newer="$2" path_list="$run/code-paths"
  git -C "$repo" diff --name-only -z --diff-filter=A "$base" "$newer" -- . "${runtime_excludes[@]}" >"$path_list" 2>/dev/null || return 1
  while IFS= read -r -d '' path; do
    test ! -e "$path" && test ! -L "$path" || return 1
  done <"$path_list"
}
fail_invariant() { printf '%s\n' "SAFE_DEPLOY_INVARIANT_FAILED=$1" >&2; return 1; }
require_staged_file() { test -f "$1" || fail_invariant "$2"; }
verify_live_tree_unchanged() { test "$(tree_digest data/api)" = "$api_before" && test "$(tree_digest site/dist)" = "$dist_before" || fail_invariant live_tree_digest; }
api_before="$(tree_digest data/api)"; dist_before="$(tree_digest site/dist)"
write_manifest() {
  MANIFEST="$manifest" STATE="$1" OLD_HEAD="$old_head" TARGET_HEAD="${target_head:-}" API_BEFORE="$api_before" DIST_BEFORE="$dist_before" API_AFTER="${api_after:-}" DIST_AFTER="${dist_after:-}" BACKUP="$backup" STAGE="$stage" python3 - 2>/dev/null <<'PY'
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
api_renamed=0
dist_renamed=0
live_code_replaced=0
live_head_advanced=0
rollback() {
  code="${1:-1}"; if [ "$rolling_back" = 1 ]; then exit "$code"; fi; rolling_back=1; trap - ERR HUP INT TERM
  set +e
  if [ "$backups_ready" != 1 ]; then write_manifest rollback_failed || true; exit "$code"; fi
  write_manifest promoting || true
  if [ "$api_renamed" = 1 ]; then
    rm -rf data/api >/dev/null 2>&1
    mv "$backup/pre-promotion-api" data/api >/dev/null 2>&1
  fi
  if [ "$dist_renamed" = 1 ]; then
    rm -rf site/dist >/dev/null 2>&1
    mv "$backup/pre-promotion-site-dist" site/dist >/dev/null 2>&1
  fi
  if [ "$live_head_advanced" = 1 ]; then
    git -C "$repo" update-ref "refs/heads/$branch" "$old_head" "$target_head" >/dev/null 2>&1 || true
  fi
  restored=0
  code_restored=1
  if [ "$live_code_replaced" = 1 ]; then
    git -C "$repo" checkout "$old_head" -- . "${runtime_excludes[@]}" >/dev/null 2>&1 || code_restored=0
    remove_added_code_paths "$old_head" "$target_head" || code_restored=0
    added_code_paths_absent "$old_head" "$target_head" || code_restored=0
  fi
  test "$code_restored" = 1 && \
    test "$(git rev-parse HEAD 2>/dev/null)" = "$old_head" && \
    git -C "$repo" diff --quiet -- . "${runtime_excludes[@]}" >/dev/null 2>&1 && \
    git -C "$repo" diff --cached --quiet -- . "${runtime_excludes[@]}" >/dev/null 2>&1 && \
    test "$(tree_digest data/api)" = "$api_before" && \
    test "$(tree_digest site/dist)" = "$dist_before" && \
    curl -fsS https://defirisk.co/ >/dev/null 2>&1 && restored=1
  if [ "$restored" = 1 ]; then write_manifest rolled_back; else write_manifest rollback_failed; fi
  exit "$code"
}
terminal_receipt_exists() {
  test -f "$manifest" || return 1
  python3 - "$manifest" 2>/dev/null <<'PY'
import json, sys
try:
    state = json.load(open(sys.argv[1], encoding="utf-8")).get("state")
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if state in {"succeeded", "rolled_back", "rollback_failed"} else 1)
PY
}
cleanup() {
  trap - EXIT
  if ! terminal_receipt_exists; then
    printf '%s\n' 'cleanup warning; retained unsealed deployment staging' >&2
    return
  fi
  if [ "$stage_worktree_ready" = 1 ]; then
    if ! git -C "$repo" worktree remove --force "$stage_worktree" >/dev/null 2>&1; then
      printf '%s\n' 'cleanup warning; retained deployment worktree state' >&2
      return
    fi
  fi
  rm -rf "$stage" >/dev/null 2>&1 || printf '%s\n' 'cleanup warning; retained deployment state' >&2
}
normalize_public_artifact_permissions() {
  for public_root in "$stage/site-dist" "$stage/data/api"; do
    find "$public_root" -type d -exec chmod 0755 {} + >/dev/null 2>&1 || { printf '%s\n' 'ERROR: staged artifact permissions failed' >&2; exit 1; }
    find "$public_root" -type f -exec chmod 0644 {} + >/dev/null 2>&1 || { printf '%s\n' 'ERROR: staged artifact permissions failed' >&2; exit 1; }
  done
}
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
cp -a data/api "$backup/original-api" >/dev/null 2>&1 || { printf '%s\n' 'ERROR: deployment backup unavailable' >&2; exit 1; }
cp -a site/dist "$backup/original-site-dist" >/dev/null 2>&1 || { printf '%s\n' 'ERROR: deployment backup unavailable' >&2; exit 1; }
test "$(tree_digest "$backup/original-api")" = "$api_before"; test "$(tree_digest "$backup/original-site-dist")" = "$dist_before"; backups_ready=1

test "$(git -C "$repo" symbolic-ref --quiet --short HEAD 2>/dev/null)" = "$branch"
git -C "$repo" fetch --no-tags "$remote" "+refs/heads/$branch:refs/remotes/$remote/$branch" >/dev/null 2>&1 || {
  printf '%s\n' 'ERROR: deployment target fetch unavailable' >&2
  exit 1
}
target_head="$(git -C "$repo" rev-parse --verify "refs/remotes/$remote/$branch^{commit}")"
git -C "$repo" worktree add --detach "$stage_worktree" "$target_head" >/dev/null 2>&1 || {
  printf '%s\n' 'ERROR: deployment staging checkout unavailable' >&2
  exit 1
}
stage_worktree_ready=1
test "$(git -C "$stage_worktree" rev-parse HEAD)" = "$target_head"
git -C "$stage_worktree" diff --quiet >/dev/null 2>&1 || { printf '%s\n' 'ERROR: deployment staging checkout unavailable' >&2; exit 1; }
git -C "$stage_worktree" diff --cached --quiet >/dev/null 2>&1 || { printf '%s\n' 'ERROR: deployment staging checkout unavailable' >&2; exit 1; }
test -z "$(git -C "$stage_worktree" ls-files -u 2>/dev/null)" || { printf '%s\n' 'ERROR: deployment staging checkout unavailable' >&2; exit 1; }
test -z "$(git -C "$stage_worktree" status --porcelain --untracked-files=all 2>/dev/null)" || { printf '%s\n' 'ERROR: deployment staging checkout unavailable' >&2; exit 1; }
rm -rf "$stage_worktree/data/api" >/dev/null 2>&1 || {
  printf '%s\n' 'ERROR: deployment staging input unavailable' >&2
  exit 1
}
cp -a data/api "$stage_worktree/data/api" >/dev/null 2>&1 || {
  printf '%s\n' 'ERROR: deployment staging input unavailable' >&2
  exit 1
}
test -z "$(find "$stage_worktree/data/api" -type l -print -quit 2>/dev/null)" || {
  printf '%s\n' 'ERROR: deployment staging input unavailable' >&2
  exit 1
}
write_manifest staging

set -a
if ! . "$repo/.env" >/dev/null 2>&1; then
  set +a
  printf '%s\n' 'ERROR: deployment environment unavailable' >&2
  exit 1
fi
set +a; : "${DATABASE_URL:=${LOCAL_DATABASE_URL:-}}"; test -n "$DATABASE_URL"; export DATABASE_URL
py=python3; test -x "$repo/venv/bin/python" && py="$repo/venv/bin/python"
dump_log="$run/dump.log"; "$py" "$stage_worktree/scripts/dump.py" --out-root "$stage/data" >"$dump_log" 2>&1 || {
  printf '%s\n' 'ERROR: staged API generation failed' >&2
  exit 1
}
policy="$stage_worktree/scripts/ci/deploy-publication-policy.json"
"$py" "$stage_worktree/scripts/ci/validate-staged-published-api.py" --api-root "$stage/data/api/v1.7.0" --policy "$policy" >"$run/validation.log" 2>&1 || {
  printf '%s\n' 'ERROR: staged publication validation failed' >&2
  exit 1
}
"$py" "$stage_worktree/scripts/ci/verify-deployment-publication-state.py" --policy "$policy" --dump-log "$dump_log" >"$run/publication.log" 2>&1 || {
  printf '%s\n' 'ERROR: staged publication validation failed' >&2
  exit 1
}
(
  export DEPLOY_NODE_CACHE="$stage/node-cache"
  . "$stage_worktree/scripts/ci/use-node-22.sh"
  cd "$stage_worktree/site"
  export npm_config_cache="$stage/npm-cache" DEFIRISK_API_ROOT="$stage/data/api/v1.7.0" DEFIRISK_DIST_ROOT="$stage/site-dist"
  npm ci --prefer-offline
  npm run build -- --outDir "$stage/site-dist"
) >"$run/site-build.log" 2>&1 || {
  printf '%s\n' 'ERROR: staged site build failed' >&2
  exit 1
}
normalize_public_artifact_permissions
require_staged_file "$stage/site-dist/index.html" staged_site_index
require_staged_file "$stage/site-dist/api/v1.7.0/index.json" staged_api_index
"$py" "$stage_worktree/scripts/ci/smoke-staged-deploy.py" --dist-root "$stage/site-dist" --api-root "$stage/data/api/v1.7.0" >"$run/smoke.log" 2>&1 || fail_invariant staged_smoke
verify_live_tree_unchanged
test "${SAFE_DEPLOY_FAIL_AT:-}" != before_promotion
write_manifest promoting
mv data/api "$backup/pre-promotion-api" >/dev/null 2>&1 || { printf '%s\n' 'ERROR: artifact promotion failed' >&2; exit 1; }
api_renamed=1; test "${SAFE_DEPLOY_FAIL_AT:-}" != after_api_rename
mv "$stage/data/api" data/api >/dev/null 2>&1 || { printf '%s\n' 'ERROR: artifact promotion failed' >&2; exit 1; }
test "${SAFE_DEPLOY_FAIL_AT:-}" != after_api_promote
mv site/dist "$backup/pre-promotion-site-dist" >/dev/null 2>&1 || { printf '%s\n' 'ERROR: artifact promotion failed' >&2; exit 1; }
dist_renamed=1; test "${SAFE_DEPLOY_FAIL_AT:-}" != after_dist_rename
mv "$stage/site-dist" site/dist >/dev/null 2>&1 || { printf '%s\n' 'ERROR: artifact promotion failed' >&2; exit 1; }
test "${SAFE_DEPLOY_FAIL_AT:-}" != after_dist_promote
live_code_replaced=1
git -C "$repo" checkout "$target_head" -- . "${runtime_excludes[@]}" >/dev/null 2>&1 || {
  printf '%s\n' 'ERROR: deployment code update failed' >&2
  exit 1
}
remove_added_code_paths "$target_head" "$old_head" || {
  printf '%s\n' 'ERROR: deployment code update failed' >&2
  exit 1
}
added_code_paths_absent "$target_head" "$old_head" || {
  printf '%s\n' 'ERROR: deployment code update failed' >&2
  exit 1
}
test "${SAFE_DEPLOY_FAIL_AT:-}" != after_code_checkout
git -C "$repo" update-ref "refs/heads/$branch" "$target_head" "$old_head" >/dev/null 2>&1 || {
  printf '%s\n' 'ERROR: deployment code update failed' >&2
  exit 1
}
live_head_advanced=1
test "$(git -C "$repo" rev-parse HEAD)" = "$target_head"
git -C "$repo" diff --quiet -- . "${runtime_excludes[@]}" >/dev/null 2>&1 || { printf '%s\n' 'ERROR: deployment code update failed' >&2; exit 1; }
git -C "$repo" diff --cached --quiet -- . "${runtime_excludes[@]}" >/dev/null 2>&1 || { printf '%s\n' 'ERROR: deployment code update failed' >&2; exit 1; }
api_after="$(tree_digest data/api)"; dist_after="$(tree_digest site/dist)"; curl -fsS https://defirisk.co/ >/dev/null 2>&1; test "${SAFE_DEPLOY_FAIL_AT:-}" != after_smoke
write_manifest succeeded
trap - ERR HUP INT TERM
set +e
rm -rf "$backup/original-api" "$backup/original-site-dist" >/dev/null 2>&1 || printf '%s\n' 'cleanup warning; retained successful deployment state' >&2
prune_verified_successes || printf '%s\n' 'retention warning; retained successful deployment state' >&2
echo "SAFE_DEPLOY_MANIFEST=sealed"
