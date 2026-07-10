#!/usr/bin/env bash
set -euo pipefail

repo_dir=${1:?"usage: sync-vps-checkout.sh REPO_DIR [REMOTE] [BRANCH]"}
remote=${2:-origin}
branch=${3:-main}

if ! cd "$repo_dir"; then
  echo "ERROR: deployment repository directory is unavailable" >&2
  exit 1
fi
if [ "$(git rev-parse --is-inside-work-tree 2>/dev/null || true)" != "true" ]; then
  echo "ERROR: deployment directory is not a Git worktree" >&2
  exit 1
fi

rebase_merge=$(git rev-parse --git-path rebase-merge)
rebase_apply=$(git rev-parse --git-path rebase-apply)
rebase_head_name=""
for rebase_dir in "$rebase_merge" "$rebase_apply"; do
  if [ -f "$rebase_dir/head-name" ]; then
    IFS= read -r rebase_head_name < "$rebase_dir/head-name"
    break
  fi
done

current_branch=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)
if [ "$current_branch" != "$branch" ] && \
   [ "$rebase_head_name" != "refs/heads/$branch" ]; then
  echo "ERROR: deployment checkout is on the wrong branch" >&2
  exit 1
fi
if ! git remote get-url "$remote" >/dev/null 2>&1; then
  echo "ERROR: deployment checkout is missing the expected remote" >&2
  exit 1
fi

index_lock=$(git rev-parse --git-path index.lock)
if [ -e "$index_lock" ]; then
  echo "ERROR: deployment checkout has an index lock; inspect it manually" >&2
  exit 1
fi

echo "==> Fetching the public deployment branch..."
git fetch --no-tags "$remote" \
  "+refs/heads/$branch:refs/remotes/$remote/$branch"
target=$(git rev-parse --verify "refs/remotes/$remote/$branch^{commit}")

# Fetch succeeds before any tracked state is discarded. Abort stale operations
# quietly so generated paths cannot be copied into workflow logs.
if [ -f "$(git rev-parse --git-path MERGE_HEAD)" ]; then
  git merge --abort >/dev/null 2>&1 || true
fi
if [ -d "$rebase_merge" ] || [ -d "$rebase_apply" ]; then
  git rebase --abort >/dev/null 2>&1 || git am --abort >/dev/null 2>&1 || true
fi
if [ -f "$(git rev-parse --git-path CHERRY_PICK_HEAD)" ]; then
  git cherry-pick --abort >/dev/null 2>&1 || true
fi
if [ -f "$(git rev-parse --git-path REVERT_HEAD)" ]; then
  git revert --abort >/dev/null 2>&1 || true
fi

current_branch=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)
if [ "$current_branch" != "$branch" ]; then
  echo "ERROR: deployment checkout did not return to the expected branch" >&2
  exit 1
fi

local_commit_count=$(git rev-list --count "$target"..HEAD 2>/dev/null || echo 0)
if [ "$local_commit_count" -gt 0 ]; then
  echo "==> Discarding $local_commit_count VPS-local commit(s); runtime data is regenerated"
fi

git reset --hard "$target" >/dev/null

head_commit=$(git rev-parse HEAD)
if [ "$head_commit" != "$target" ]; then
  echo "ERROR: deployment checkout did not reach the fetched commit" >&2
  exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: deployment checkout has tracked changes after synchronization" >&2
  exit 1
fi
if [ -n "$(git ls-files -u)" ]; then
  echo "ERROR: deployment checkout still has unmerged entries" >&2
  exit 1
fi
for state_path in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  if [ -e "$(git rev-parse --git-path "$state_path")" ]; then
    echo "ERROR: deployment checkout still has an unfinished Git operation" >&2
    exit 1
  fi
done
if [ -d "$rebase_merge" ] || [ -d "$rebase_apply" ]; then
  echo "ERROR: deployment checkout still has an unfinished rebase" >&2
  exit 1
fi

read -r ahead behind < <(
  git rev-list --left-right --count "HEAD...refs/remotes/$remote/$branch"
)
if [ "$ahead" != "0" ] || [ "$behind" != "0" ]; then
  echo "ERROR: deployment checkout is not synchronized" >&2
  exit 1
fi

echo "==> Deployment checkout synchronized (ahead 0, behind 0)"
