#!/bin/bash
# run_shard.sh — Slurm worker for one HiGHS version (or Gurobi) on woody
# Submitted by submit_benchmark.sh. Runs on compute node inside Apptainer.
# 1 node, 1 solver, 4 threads (4 cores total), 60s per instance, full MIPLIB2017.
#
# Signals: USR1 10min/60s before walltime (per TIMEPERJOB), TERM 60s before — graceful exit.
# This script does NOT self-resubmit (benchmark is finite); partial results are kept and
# the frontend can resubmit via submit_benchmark.sh.
#
# Usage via sbatch (see common.sh:submit_slurm_job):
#   sbatch ... run_shard.sh --version 1.15.1 --solver highs --threads 4 --time-limit 60 --set miplib2017 --repo-root $REPO --nodefile ... --instances-root ...

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
SOLVER="highs"          # highs or gurobi
VERSION=""              # e.g. 1.15.1.8 (required for highs; ignored for gurobi)
THREADS=4
TIME_LIMIT=60
SET="miplib2017"
REPO_ROOT=""
NODEFILE=""
INSTANCES_ROOT=""
RESULTS_ROOT=""
TIMEPERJOB="05:00:00"
USR1_OFFSET=600
DRY_RUN=false
FORCE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)       VERSION="$2"; shift 2 ;;
    --solver)        SOLVER="$2"; shift 2 ;;
    --threads)       THREADS="$2"; shift 2 ;;
    --time-limit)    TIME_LIMIT="$2"; shift 2 ;;
    --set)           SET="$2"; shift 2 ;;
    --repo-root)     REPO_ROOT="$2"; shift 2 ;;
    --nodefile)      NODEFILE="$2"; shift 2 ;;
    --instances-root) INSTANCES_ROOT="$2"; shift 2 ;;
    --results-root)  RESULTS_ROOT="$2"; shift 2 ;;
    --timeperjob)    TIMEPERJOB="$2"; shift 2 ;;
    --signal-offset) USR1_OFFSET="$2"; shift 2 ;;
    --dry-run)       DRY_RUN=true; shift ;;
    --force)         FORCE=true; shift ;;
    --nprocs)        shift 2 ;; # compat, ignored (we use --cpus-per-task)
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$REPO_ROOT" ]; then echo "Error: --repo-root required" >&2; exit 1; fi
if [ "$SOLVER" = "highs" ] && [ -z "$VERSION" ]; then echo "Error: --version required for highs" >&2; exit 1; fi

SCRIPT_DIR="${REPO_ROOT}/benchmark/cluster"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

INSTANCES_ROOT="${INSTANCES_ROOT:-${REPO_ROOT}/benchmark/instances}"
RESULTS_ROOT="${RESULTS_ROOT:-${REPO_ROOT}/benchmark/results}"
SIF_FILE="${REPO_ROOT}/benchmark/cluster/highs-bench.sif"
BIN_DIR="${REPO_ROOT}/benchmark/cluster/binaries"

# Logging prefix
TAG="${SOLVER}:${VERSION:-gurobi}"
echo "[$TAG] worker start on $(hostname) threads=$THREADS time_limit=${TIME_LIMIT}s set=$SET"
echo "[$TAG] repo=$REPO_ROOT instances=$INSTANCES_ROOT results=$RESULTS_ROOT"
echo "[$TAG] TIMEPERJOB=$TIMEPERJOB USR1_OFFSET=$USR1_OFFSET"

# ── Signal handling ─────────────────────────────────────────────────────────
WALLTIME_HIT=false
GRACEFUL_EXIT=false

cleanup() {
  echo "[$TAG] cleanup..."
  # run_benchmark.py writes per-instance JSON atomically; no extra flush needed
}

on_usr1() {
  echo "[$TAG] USR1 received (${USR1_OFFSET}s before walltime) — graceful stop after current instance"
  WALLTIME_HIT=true
  # Let run_benchmark finish current instance; it checkpoints per instance, so safe to let run
  # but we mark for exit after.
}
on_term() {
  echo "[$TAG] TERM received"
  if [ "$WALLTIME_HIT" = true ]; then
    echo "[$TAG] TERM after USR1 — walltime kill"
  else
    # Distinguish scancel vs walltime via elapsed time (run_worker.sh pattern)
    local elapsed=0 time_s=0
    if [ -n "${WORKER_START:-}" ]; then
      elapsed=$(( $(date +%s) - WORKER_START ))
      time_s=$(time_to_seconds "$TIMEPERJOB")
      if [ "$elapsed" -ge $((time_s - 120)) ]; then
        echo "[$TAG] elapsed ${elapsed}s near walltime ${time_s}s — treat as walltime"
        WALLTIME_HIT=true
      else
        echo "[$TAG] scancel likely — exiting"
        GRACEFUL_EXIT=true
      fi
    fi
  fi
  cleanup
}

trap on_usr1 USR1
trap on_term TERM INT
WORKER_START=$(date +%s)

export http_proxy=http://proxy:80
export https_proxy=http://proxy:80

# ── Dry run ─────────────────────────────────────────────────────────────────
if [ "$DRY_RUN" = true ]; then
  echo "[$TAG] DRY RUN — would execute:"
  FORCE_FLAG=""; [ "$FORCE" = true ] && FORCE_FLAG="--force"
  if [ "$SOLVER" = "highs" ]; then
    echo "  container_exec $REPO_ROOT uv run python benchmark/scripts/run_benchmark.py --solver highs --highs-bin benchmark/cluster/binaries/highs-${VERSION} --threads $THREADS --time-limit $TIME_LIMIT --instances-root $INSTANCES_ROOT --results-root $RESULTS_ROOT --set $SET $FORCE_FLAG"
  else
    echo "  container_exec $REPO_ROOT uv run python benchmark/scripts/run_benchmark.py --solver gurobi --threads $THREADS --time-limit $TIME_LIMIT --instances-root $INSTANCES_ROOT --results-root $RESULTS_ROOT --set $SET $FORCE_FLAG"
  fi
  exit 0
fi

# ── Prechecks ───────────────────────────────────────────────────────────────
if [ ! -f "$SIF_FILE" ]; then echo "[$TAG] SIF not found: $SIF_FILE" >&2; exit 1; fi
if [ ! -d "$INSTANCES_ROOT" ] || ! ls "$INSTANCES_ROOT"/*.mps.gz >/dev/null 2>&1; then
  echo "[$TAG] instances missing in $INSTANCES_ROOT — trying fallback $REPO_ROOT/benchmark/sets/miplib2017-benchmark"
  fallback="${REPO_ROOT}/benchmark/sets/miplib2017-benchmark"
  if [ -d "$fallback" ] && ls "$fallback"/*.mps.gz >/dev/null 2>&1; then
    INSTANCES_ROOT="$fallback"
    echo "[$TAG] using fallback: $INSTANCES_ROOT"
  else
    echo "[$TAG] no instances found" >&2; exit 1
  fi
fi

if [ "$SOLVER" = "highs" ]; then
  BIN="${BIN_DIR}/highs-${VERSION}"
  if [ ! -x "$BIN" ]; then echo "[$TAG] binary not found: $BIN" >&2; exit 1; fi
  echo "[$TAG] binary: $BIN ($("$BIN" --version 2>&1 | head -n1))"
  HIGHS_ARGS=(--solver highs --highs-bin "$BIN")
else
  HIGHS_ARGS=(--solver gurobi)
  # Verify gurobi license inside container
  echo "[$TAG] checking Gurobi license inside container..."
  if ! container_exec "$REPO_ROOT" bash -c "uv run python -c 'import gurobipy; print(gurobipy.gurobi.version())' 2>&1 | tail -n 5"; then
    echo "[$TAG] WARNING: gurobipy check failed — will still attempt run" >&2
  fi
fi

# ── Run benchmark inside container (single process, 4 threads, 60s, full set) ──
# This fills results/${solver}/${version}/${machine}/${set}/*.json
# 1 node, 4 cores total via --threads $THREADS (solver internal parallelism).
# Instances run sequentially; no sharding needed. If WALLTIME_HIT, run_benchmark
# will exit after current instance and partial results remain valid for resume.

echo "[$TAG] launching benchmark..."
FORCE_FLAG=()
if [ "$FORCE" = true ]; then FORCE_FLAG=(--force); fi
set +e
if [ "$SOLVER" = "highs" ]; then
  container_exec "$REPO_ROOT" uv run python benchmark/scripts/run_benchmark.py \
    "${HIGHS_ARGS[@]}" \
    --threads "$THREADS" \
    --time-limit "$TIME_LIMIT" \
    --instances-root "$INSTANCES_ROOT" \
    --results-root "$RESULTS_ROOT" \
    --set "$SET" \
    "${FORCE_FLAG[@]}"
  RC=$?
else
  container_exec "$REPO_ROOT" uv run python benchmark/scripts/run_benchmark.py \
    "${HIGHS_ARGS[@]}" \
    --threads "$THREADS" \
    --time-limit "$TIME_LIMIT" \
    --instances-root "$INSTANCES_ROOT" \
    --results-root "$RESULTS_ROOT" \
    --set "$SET" \
    "${FORCE_FLAG[@]}"
  RC=$?
fi
set -e

echo "[$TAG] benchmark exit code: $RC"

if [ "$WALLTIME_HIT" = true ]; then
  echo "[$TAG] walltime hit — partial results kept, resubmit with submit_benchmark.sh to continue"
  # exit 0 so Slurm marks COMPLETED; frontend can check missing instances and resubmit if needed
  exit 0
fi

if [ "$RC" -ne 0 ]; then
  echo "[$TAG] benchmark failed with $RC" >&2
  exit "$RC"
fi

echo "[$TAG] done — results in $RESULTS_ROOT/$SOLVER/"
cnt=$(find "$RESULTS_ROOT/$SOLVER" -path "*/$SET/*.json" 2>/dev/null | wc -l || echo 0)
echo "[$TAG] result files for set $SET: $cnt"
