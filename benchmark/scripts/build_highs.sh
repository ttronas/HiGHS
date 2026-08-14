#!/usr/bin/env bash
# Build a release HiGHS binary used for benchmarking.
#   scripts/build_highs.sh [--debug]
# Binary lands in <repo>/build/bin/highs (or build-debug/bin/highs with --debug).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

MODE="${1:---release}"
case "$MODE" in
  --debug)  BUILD_TYPE=Debug;   BUILD_DIR="$REPO_ROOT/build-debug";;
  --release|*) BUILD_TYPE=Release; BUILD_DIR="$REPO_ROOT/build";;
esac

echo "==> CMake configure ($BUILD_TYPE) -> $BUILD_DIR"
cmake -S "$REPO_ROOT" -B "$BUILD_DIR" -G Ninja \
      -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
      -DCMAKE_RULE_MESSAGES=OFF \
      -DBUILD_SHARED_LIBS=OFF

echo "==> Build"
cmake --build "$BUILD_DIR" --parallel

echo "==> Binary: $BUILD_DIR/bin/highs"
"$BUILD_DIR/bin/highs" --version
