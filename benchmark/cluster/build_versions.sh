#!/bin/bash
# build_versions.sh — build all HiGHS versions listed in versions.txt inside the Apptainer container
# Runs on frontend node, but compilation happens inside container for cluster ABI consistency.
#
# Usage:
#   ./benchmark/cluster/build_versions.sh [--force] [--versions-file PATH] [--jobs N]
#   --force        rebuild even if binary exists
#   --jobs N       parallel cmake builds (default: 4, capped by nproc)
#
# Prereqs: SIF exists (via common.sh:build_container), git worktree support, ccache bind.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "${SCRIPT_DIR}/common.sh"

VERSIONS_FILE="${REPO_ROOT}/benchmark/cluster/versions.txt"
FORCE=false
JOBS=4

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=true; shift ;;
    --versions-file) VERSIONS_FILE="$2"; shift 2 ;;
    --jobs) JOBS="$2"; shift 2 ;;
    -h|--help) echo "Usage: $0 [--force] [--versions-file PATH] [--jobs N]"; exit 0 ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

if [ ! -f "$VERSIONS_FILE" ]; then echo "versions file not found: $VERSIONS_FILE" >&2; exit 1; fi
BIN_DIR="${REPO_ROOT}/benchmark/cluster/binaries"
mkdir -p "$BIN_DIR"
SIF_FILE="${REPO_ROOT}/benchmark/cluster/highs-bench.sif"

if [ ! -f "$SIF_FILE" ]; then
  echo "[build] SIF missing — building..."
  build_container "$REPO_ROOT" false
fi

# Ensure uv venv inside container (idempotent)
echo "[build] syncing benchmark venv inside container..."
container_exec "$REPO_ROOT" bash -c "cd benchmark && uv sync --frozen 2>&1 | tail -n 5 || uv sync 2>&1 | tail -n 5"

MANIFEST="${BIN_DIR}/manifest.json"
echo "{" > "${MANIFEST}.tmp"

first=true
while IFS= read -r line || [ -n "$line" ]; do
  [[ -z "$line" ]] && continue
  [[ "$line" =~ ^# ]] && continue
  # split on whitespace
  ver=$(echo "$line" | awk '{print $1}')
  ref=$(echo "$line" | awk '{print $2}')
  [ -z "$ver" ] || [ -z "$ref" ] && continue

  bin="${BIN_DIR}/highs-${ver}"
  if [ -f "$bin" ] && [ "$FORCE" = false ]; then
    echo "[build] $ver exists: $bin — skip (--force to rebuild)"
    sha=$(sha256sum "$bin" | awk '{print $1}')
    if [ "$first" = true ]; then first=false; else echo "," >> "${MANIFEST}.tmp"; fi
    printf '  "%s": "%s"' "$ver" "$sha" >> "${MANIFEST}.tmp"
    continue
  fi

  echo "────────────────────────────────────────────────────────"
  echo "[build] $ver  ref=$ref"

  # Resolve ref to SHA (tag or commit)
  sha_ref=$(git -C "$REPO_ROOT" rev-parse --verify "$ref" 2>/dev/null || git -C "$REPO_ROOT" rev-parse --verify "refs/tags/$ref" 2>/dev/null || echo "")
  if [ -z "$sha_ref" ]; then
    echo "  error: cannot resolve ref $ref" >&2; exit 1
  fi
  echo "  resolved: $ref -> $sha_ref"

  # Use git worktree (clean, no checkout pollution). Fallback to tarball.
  WT_DIR=$(mktemp -d -p /tmp "highs-build-${ver}-XXXX")
  # shellcheck disable=SC2064
  trap "rm -rf '$WT_DIR'; git -C '$REPO_ROOT' worktree prune 2>/dev/null || true" EXIT

  # worktree add detached
  if git -C "$REPO_ROOT" worktree add --detach "$WT_DIR" "$sha_ref" 2>&1 | tail -n 3; then
    echo "  worktree: $WT_DIR"
  else
    echo "  worktree failed, falling back to archive..."
    git -C "$REPO_ROOT" archive "$sha_ref" | tar -x -C "$WT_DIR"
  fi

  # Build inside container: share worktree via bind
  # We bind WT_DIR into container at /tmp/build and output to BIN_DIR via bind of REPO
  echo "  cmake configure + build (jobs=$JOBS) inside container..."
  # Need to make WT_DIR visible inside container: bind it explicitly
  RT="apptainer"; command -v apptainer >/dev/null 2>&1 || RT="singularity"
  # Create build dir
  mkdir -p "$WT_DIR/build"

  # Run cmake configure + build inside container with extra bind for WT_DIR
  "$RT" exec \
    --bind "${REPO_ROOT}:/workspaces/HiGHS" \
    --bind "${WT_DIR}:/tmp/buildtree" \
    --bind "${REPO_ROOT}/benchmark/cluster/binaries:/tmp/out" \
    --pwd /tmp/buildtree \
    --env CCACHE_DIR=/workspaces/HiGHS/.ccache \
    --env http_proxy=http://proxy:80 --env https_proxy=http://proxy:80 \
    "$SIF_FILE" bash -c "
      set -e
      cmake -S /tmp/buildtree -B /tmp/buildtree/build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
        -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
        -DCMAKE_RULE_MESSAGES=OFF 2>&1 | tail -n 20
      cmake --build /tmp/buildtree/build --parallel $JOBS 2>&1 | tail -n 20
      cp /tmp/buildtree/build/bin/highs /tmp/out/highs-${ver}
      /tmp/out/highs-${ver} --version || true
    "

  # Verify + hash
  if [ ! -f "$bin" ]; then echo "  error: binary not produced: $bin" >&2; exit 1; fi
  chmod +x "$bin"
  sha=$(sha256sum "$bin" | awk '{print $1}')
  echo "  built: $bin  sha256=$sha  ver=$("$bin" --version 2>&1 | head -n 1)"
  if [ "$first" = true ]; then first=false; else echo "," >> "${MANIFEST}.tmp"; fi
  printf '  "%s": "%s"' "$ver" "$sha" >> "${MANIFEST}.tmp"

  # cleanup worktree
  rm -rf "$WT_DIR"
  git -C "$REPO_ROOT" worktree prune 2>/dev/null || true
  trap - EXIT

done < "$VERSIONS_FILE"

echo "" >> "${MANIFEST}.tmp"
echo "}" >> "${MANIFEST}.tmp"
mv "${MANIFEST}.tmp" "$MANIFEST"
echo "────────────────────────────────────────────────────────"
echo "[build] manifest: $MANIFEST"
cat "$MANIFEST"
echo "[build] binaries:"
ls -lh "$BIN_DIR"/highs-* 2>/dev/null || true
