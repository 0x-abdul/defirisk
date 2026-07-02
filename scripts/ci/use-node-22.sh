#!/usr/bin/env bash
# Source this from VPS maintenance shells before running site npm commands.
set -euo pipefail

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "ERROR: source this script so PATH updates persist: . scripts/ci/use-node-22.sh" >&2
  exit 1
fi

node_major="${DEPLOY_NODE_MAJOR:-22}"
node_min_version="${DEPLOY_NODE_MIN_VERSION:-22.22.3}"
node_cache="${DEPLOY_NODE_CACHE:-/opt/riskdashboard/.node}"

version_ge() {
  python3 -c '
import sys

current = [int(part) for part in sys.argv[1].split(".")]
required = [int(part) for part in sys.argv[2].split(".")]
width = max(len(current), len(required))
current += [0] * (width - len(current))
required += [0] * (width - len(required))
sys.exit(0 if current >= required else 1)
' "$1" "$2"
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required to select a Node ${node_major} release." >&2
  exit 1
fi

if command -v node >/dev/null 2>&1; then
  current_node_version="$(node -p 'process.versions.node' 2>/dev/null || true)"
  if [ -n "$current_node_version" ] && version_ge "$current_node_version" "$node_min_version"; then
    echo "==> Using system Node $(node --version) at $(command -v node)"
    return 0
  fi
fi

machine_arch="$(uname -m)"
case "$machine_arch" in
  x86_64) node_arch="x64" ;;
  aarch64|arm64) node_arch="arm64" ;;
  *)
    echo "ERROR: unsupported Node architecture: ${machine_arch}" >&2
    exit 1
    ;;
esac

node_version="$(
  curl -fsSL https://nodejs.org/dist/index.json |
    python3 -c '
import json
import sys

arch = sys.argv[1]
major = sys.argv[2]
for release in json.load(sys.stdin):
    if release["version"].startswith(f"v{major}.") and f"linux-{arch}" in release["files"]:
        print(release["version"])
        break
else:
    raise SystemExit(f"No Node v{major} release found for linux-{arch}")
' "$node_arch" "$node_major"
)"

node_dir="${node_cache}/node-${node_version}-linux-${node_arch}"
if [ ! -x "${node_dir}/bin/node" ]; then
  echo "==> Installing Node ${node_version} for linux-${node_arch} under ${node_cache}"
  download_dir="${node_cache}/.downloads"
  node_tarball="node-${node_version}-linux-${node_arch}.tar.xz"

  mkdir -p "$download_dir"
  curl -fsSLo "${download_dir}/${node_tarball}" \
    "https://nodejs.org/dist/${node_version}/${node_tarball}"
  curl -fsSLo "${download_dir}/SHASUMS256.txt" \
    "https://nodejs.org/dist/${node_version}/SHASUMS256.txt"

  (
    cd "$download_dir"
    grep "  ${node_tarball}$" SHASUMS256.txt | sha256sum -c -
  )

  rm -rf "${node_dir}.tmp"
  mkdir -p "${node_dir}.tmp"
  tar -xJf "${download_dir}/${node_tarball}" -C "${node_dir}.tmp" --strip-components=1
  rm -rf "$node_dir"
  mv "${node_dir}.tmp" "$node_dir"
fi

export PATH="${node_dir}/bin:${PATH}"
resolved_node_version="$(node -p 'process.versions.node')"
if ! version_ge "$resolved_node_version" "$node_min_version"; then
  echo "ERROR: expected Node >=${node_min_version}, got v${resolved_node_version}" >&2
  exit 1
fi

echo "==> Using Node $(node --version) at $(command -v node)"
