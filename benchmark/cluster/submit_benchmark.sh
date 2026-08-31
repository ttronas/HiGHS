#!/bin/bash
# submit_benchmark.sh — frontend orchestrator for woody MIPLIB2017 full benchmark
# Phases:
#   1. Build Apptainer image if missing (woody.def -> highs-bench.sif, mounts repo)
#   2. Build all HiGHS versions inside container (benchmark/cluster/binaries/highs-*)
#   3. Spawn one Slurm job per version + one Gurobi reference (1 node, 4 cores, 60s, miplib2017)
#   4. Wait until all jobs finish, then compare versions (compare_versions.py + summarize.py) inside container
#
# Runs on frontend node. Each job uses container for dep isolation, writes to benchmark/results.
# Usage:
#   ./benchmark/cluster/submit_benchmark.sh [OPTIONS]
#   --versions-file PATH     default benchmark/cluster/versions.txt
#   --nodefile PATH          default benchmark/cluster/nodefile.tier1 (w14xx,w15xx)
#   --threads N              solver threads (default 4, 1 solver per node = 4 cores/node)
#   --time-limit SECS        per-instance limit (default 60)
#   --set NAME               results set tag (default miplib2017)
#   --timeperjob TIME        Slurm walltime per job (default 04:00:00 for 240*60s)
#   --force                  rebuild container + binaries + force benchmark rerun (ignores cache)
#   --force-container        force SIF rebuild
#   --force-build            force binary rebuild
#   --force-run              force run_benchmark --force (ignore result cache)
#   --no-build               skip phase 2
#   --no-submit              skip phase 3 (build + compare only)
#   --no-compare             skip phase 4
#   --dry-run                print what would be done, submit with --dry-run to workers
#   --instances-root PATH    default benchmark/instances
#   --results-root PATH      default benchmark/results
#   --with-gurobi            also submit Gurobi ref job (default: on, disable with --no-gurobi)
#   -h --help                show help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"
source "${SCRIPT_DIR}/common.sh"

# ── Defaults ────────────────────────────────────────────────────────────────
VERSIONS_FILE="${REPO_ROOT}/benchmark/cluster/versions.txt"
NODEFILE="${REPO_ROOT}/benchmark/cluster/nodefile.tier1"
THREADS=4
TIME_LIMIT=60
SET="miplib2017"
TIMEPERJOB="05:00:00"
FORCE=false
FORCE_CONTAINER=false
FORCE_BUILD=false
FORCE_RUN=false
NO_BUILD=false
NO_SUBMIT=false
NO_COMPARE=false
DRY_RUN=false
INSTANCES_ROOT="${REPO_ROOT}/benchmark/instances"
RESULTS_ROOT="${REPO_ROOT}/benchmark/results"
WITH_GUROBI=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --versions-file) VERSIONS_FILE="$2"; shift 2 ;;
    --nodefile) NODEFILE="$2"; shift 2 ;;
    --threads) THREADS="$2"; shift 2 ;;
    --time-limit) TIME_LIMIT="$2"; shift 2 ;;
    --set) SET="$2"; shift 2 ;;
    --timeperjob) TIMEPERJOB="$2"; shift 2 ;;
    --force) FORCE=true; FORCE_CONTAINER=true; FORCE_BUILD=true; FORCE_RUN=true; shift ;;
    --force-container) FORCE_CONTAINER=true; shift ;;
    --force-build) FORCE_BUILD=true; shift ;;
    --force-run) FORCE_RUN=true; shift ;;
    --no-build) NO_BUILD=true; shift ;;
    --no-submit) NO_SUBMIT=true; shift ;;
    --no-compare) NO_COMPARE=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --instances-root) INSTANCES_ROOT="$2"; shift 2 ;;
    --results-root) RESULTS_ROOT="$2"; shift 2 ;;
    --with-gurobi) WITH_GUROBI=true; shift ;;
    --no-gurobi) WITH_GUROBI=false; shift ;;
    -h|--help)
      sed -n '2,50p' "$0" | sed 's/^# //;s/^#//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [ "$FORCE" = true ]; then FORCE_CONTAINER=true; FORCE_BUILD=true; FORCE_RUN=true; fi

echo "════════════════════════════════════════════════════════════════════════"
echo " HiGHS MIPLIB2017 woody cluster benchmark"
echo " repo: $REPO_ROOT"
echo " set: $SET  threads: $THREADS  time_limit: ${TIME_LIMIT}s  timeperjob: $TIMEPERJOB"
echo " versions: $VERSIONS_FILE"
echo " nodefile: $NODEFILE (Tier1 w14xx,w15xx)"
echo " instances: $INSTANCES_ROOT  results: $RESULTS_ROOT"
echo " with_gurobi: $WITH_GUROBI  force: c=$FORCE_CONTAINER b=$FORCE_BUILD run=$FORCE_RUN"
echo "════════════════════════════════════════════════════════════════════════"

TIME_SECONDS=$(time_to_seconds "$TIMEPERJOB")
USR1_OFFSET=$(compute_usr1_offset "$TIME_SECONDS")
echo "Walltime: $TIMEPERJOB (${TIME_SECONDS}s)  USR1 offset: ${USR1_OFFSET}s"

if [ -f "$NODEFILE" ]; then echo "Nodefile: $NODEFILE"; cat "$NODEFILE"; else echo "WARNING: nodefile not found: $NODEFILE — Slurm will assign nodes" >&2; fi

# ── Phase 1: Container ──────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo " Phase 1: Apptainer image (frontend, idempotent)"
echo "════════════════════════════════════════════════════════════════════════"
if [ "$DRY_RUN" = true ]; then
  echo "[dry-run] would: build_container $REPO_ROOT $FORCE_CONTAINER"
else
  build_container "$REPO_ROOT" "$FORCE_CONTAINER"
fi

SIF_FILE="${REPO_ROOT}/benchmark/cluster/highs-bench.sif"
if [ "$DRY_RUN" = false ] && [ ! -f "$SIF_FILE" ]; then echo "SIF not found after build: $SIF_FILE" >&2; exit 1; fi

# ── Phase 1b: Instances ─────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo " Phase 1b: MIPLIB2017 instances"
echo "════════════════════════════════════════════════════════════════════════"
if [ "$DRY_RUN" = true ]; then
  echo "[dry-run] would: ensure_instances $REPO_ROOT"
else
  ensure_instances "$REPO_ROOT"
fi

# ── Phase 2: Build versions ─────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo " Phase 2: Build HiGHS versions inside container"
echo "════════════════════════════════════════════════════════════════════════"
if [ "$NO_BUILD" = true ]; then
  echo "Skipped (--no-build)"
else
  if [ "$DRY_RUN" = true ]; then
    echo "[dry-run] would: ${SCRIPT_DIR}/build_versions.sh --versions-file $VERSIONS_FILE $([ "$FORCE_BUILD" = true ] && echo --force)"
  else
    BUILD_ARGS=()
    if [ "$FORCE_BUILD" = true ]; then BUILD_ARGS+=(--force); fi
    BUILD_ARGS+=(--versions-file "$VERSIONS_FILE")
    "${SCRIPT_DIR}/build_versions.sh" "${BUILD_ARGS[@]}"
  fi
fi

if [ "$NO_SUBMIT" = true ]; then
  echo ""
  echo "Skipped phase 3 (--no-submit)"
  exit 0
fi

# ── Phase 3: Submit jobs ────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo " Phase 3: Submit Slurm jobs (1 per version + Gurobi)"
echo "════════════════════════════════════════════════════════════════════════"

# Parse versions
VERSIONS=()
while IFS= read -r line || [ -n "$line" ]; do
  [[ -z "$line" ]] && continue
  [[ "$line" =~ ^# ]] && continue
  v=$(echo "$line" | awk '{print $1}')
  [ -n "$v" ] && VERSIONS+=("$v")
done < "$VERSIONS_FILE"

if [ "${#VERSIONS[@]}" -eq 0 ]; then echo "No versions in $VERSIONS_FILE" >&2; exit 1; fi
echo "Versions to run: ${VERSIONS[*]}"

# Collect job IDs for wait
JOB_IDS=()
JOB_LABELS=()

submit_one() {
  local solver="$1" ver="$2"
  local label="${solver}:${ver:-gurobi}"
  local worker="${SCRIPT_DIR}/run_shard.sh"
  local extra=()
  extra+=(--solver "$solver")
  if [ "$solver" = "highs" ]; then extra+=(--version "$ver"); fi
  extra+=(--threads "$THREADS" --time-limit "$TIME_LIMIT" --set "$SET")
  extra+=(--repo-root "$REPO_ROOT" --nodefile "$NODEFILE")
  extra+=(--instances-root "$INSTANCES_ROOT" --results-root "$RESULTS_ROOT")
  extra+=(--timeperjob "$TIMEPERJOB" --signal-offset "$USR1_OFFSET")
  if [ "$FORCE_RUN" = true ]; then extra+=(--force); fi
  if [ "$DRY_RUN" = true ]; then extra+=(--dry-run); fi
  # 1 node, 4 cores via --cpus-per-task=4, 1 solver process (4 threads)
  # NPROCS=1 -> find_available_nodes needs 1 slot; submit_slurm_job sets -n 1 --cpus-per-task=4
  local out jobid node
  if [ "$DRY_RUN" = true ]; then
    jobid="DRY-$label"
    node="(dry-run)"
    out="$jobid $node"
    # Still show what would be submitted
    echo "  [dry-run] would submit $label: sbatch -n 1 --cpus-per-task=4 --time=$TIMEPERJOB --signal=B:USR1@${USR1_OFFSET} $worker ${extra[*]}"
  else
    out=$(submit_slurm_job "$REPO_ROOT" "$TIMEPERJOB" "$USR1_OFFSET" 1 "$NODEFILE" "$worker" "${extra[@]}")
    jobid=$(echo "$out" | awk '{print $1}')
    node=$(echo "$out" | awk '{print $2}')
  fi
  JOB_IDS+=("$jobid")
  JOB_LABELS+=("$label")
  echo "  submitted $label -> job $jobid node: $node"
  if [ "$DRY_RUN" = false ]; then sleep 1; fi
}

for ver in "${VERSIONS[@]}"; do
  submit_one highs "$ver"
done

if [ "$WITH_GUROBI" = true ]; then
  submit_one gurobi ""
fi

echo ""
echo "Submitted ${#JOB_IDS[@]} jobs: ${JOB_IDS[*]}"
echo "Monitor: squeue -u \$USER  or  squeue -j $(IFS=,; echo "${JOB_IDS[*]}")"

if [ "$DRY_RUN" = true ]; then
  echo "[dry-run] not waiting for jobs"
  exit 0
fi

# ── Phase 4: Wait + Compare ─────────────────────────────────────────────────
if [ "$NO_COMPARE" = true ]; then
  echo ""
  echo "Skipped phase 4 (--no-compare). Jobs submitted, exiting."
  echo "Compare later with: apptainer exec $SIF_FILE uv run python benchmark/scripts/compare_versions.py --set $SET --versions ${VERSIONS[*]}"
  exit 0
fi

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo " Phase 4: Wait for jobs, then compare"
echo "════════════════════════════════════════════════════════════════════════"
echo "Waiting for ${#JOB_IDS[@]} jobs... (poll every 30s)"

# Poll until all jobs are no longer in queue (COMPLETED/FAILED/CANCELLED)
# Use squeue + sacct fallback; print only pending IDs (not all)
poll_count=0
while true; do
  pending_ids=()
  for jid in "${JOB_IDS[@]}"; do
    # squeue shows PENDING/RUNNING/COMPLETING; after completion sacct is authoritative
    sq_out=$(squeue -j "$jid" -h -o "%i %T" 2>/dev/null | head -n1 || true)
    if echo "$sq_out" | grep -qw "$jid"; then
      state=$(echo "$sq_out" | awk '{print $2}' | tr -d ' ')
      # COMPLETING still counts as running for walltime, but we treat as pending until sacct confirms
      if [[ "$state" =~ ^(PENDING|RUNNING|CONFIGURING|COMPLETING|SUSPENDED)$ ]]; then
        pending_ids+=("$jid")
        continue
      fi
    fi
    # squeue empty or state not pending -> check sacct (authoritative after job leaves queue)
    # sacct may report PENDING/RUNNING for a short window even after squeue empty
    sacct_state=$(sacct -j "$jid" --format=State --noheader 2>/dev/null | head -n1 | tr -d ' ' || true)
    if [[ "$sacct_state" =~ PENDING|RUNNING|REQUEUED|RESIZING|COMPLETING ]]; then
      pending_ids+=("$jid")
    fi
  done
  pending=${#pending_ids[@]}
  if [ "$pending" -eq 0 ]; then break; fi
  # Print pending IDs, not all, and every 10th poll also show sacct states
  poll_count=$((poll_count+1))
  if [ $((poll_count % 20)) -eq 0 ]; then
    echo "  $(date +%H:%M:%S)  $pending jobs still queued/running: ${pending_ids[*]} (all: ${JOB_IDS[*]})"
    for pj in "${pending_ids[@]}"; do
      sq=$(squeue -j "$pj" -h -o "%i %T %R" 2>/dev/null | head -n1 || echo "not in squeue")
      sa=$(sacct -j "$pj" --format=JobID,State,Elapsed --noheader 2>/dev/null | head -n1 || echo "no sacct")
      echo "    $pj  squeue: $sq  sacct: $sa"
    done
  else
    echo "  $(date +%H:%M:%S)  $pending jobs still queued/running: ${pending_ids[*]}"
  fi
  sleep 30
done

echo "All jobs left queue — checking sacct states..."
all_ok=true
for idx in "${!JOB_IDS[@]}"; do
  jid="${JOB_IDS[$idx]}"; label="${JOB_LABELS[$idx]}"
  state=$(sacct -j "$jid" --format=State --noheader 2>/dev/null | head -n1 | awk '{print $1}' | tr -d ' ')
  echo "  $label job $jid state: $state"
  if [[ "$state" != *"COMPLETED"* ]]; then
    echo "    WARNING: $label not COMPLETED" >&2
    all_ok=false
  fi
done

echo ""
echo "────────────────────────────────────────────────────────"
echo " Compare versions inside container"
echo "────────────────────────────────────────────────────────"
# Ensure results exist
if [ ! -d "$RESULTS_ROOT" ]; then echo "No results dir: $RESULTS_ROOT" >&2; exit 1; fi

# Build versions list for compare_versions.py
CMPVERS=("${VERSIONS[@]}")
# compare_versions expects solver:version or bare version (defaults to highs)
# For full matrix, also include gurobi if requested
GT_FLAG=""
if [ "$WITH_GUROBI" = true ]; then
  # ground truth auto-discovers gurobi cache, no need to add to versions
  GT_FLAG=""
else
  GT_FLAG="--gt none"
fi

set +e
container_exec "$REPO_ROOT" uv run python benchmark/scripts/compare_versions.py \
  --set "$SET" \
  --versions "${CMPVERS[@]}" \
  --mode baseline --baseline "${CMPVERS[0]}" \
  --time-limit "$TIME_LIMIT" \
  $GT_FLAG \
  --json-out "${RESULTS_ROOT}/summary/cluster_report_${SET}_$(date +%Y%m%d-%H%M%S).json"
RC_CMP=$?
set -e

if [ "$RC_CMP" -eq 1 ]; then
  echo "Compare: FAIL — ground-truth mismatches (exit 1). See above." >&2
elif [ "$RC_CMP" -eq 2 ]; then
  echo "Compare: missing data / bad usage (exit 2)." >&2
else
  echo "Compare: OK (exit 0)"
fi

echo ""
echo "────────────────────────────────────────────────────────"
echo " Summarize (performance profile + table)"
echo "────────────────────────────────────────────────────────"
set +e
container_exec "$REPO_ROOT" uv run python benchmark/scripts/summarize.py --set "$SET"
RC_SUM=$?
set -e

echo ""
echo "════════════════════════════════════════════════════════════════════════"
if [ "$RC_CMP" -eq 0 ] && [ "$RC_SUM" -eq 0 ]; then
  echo " Done. Results: $RESULTS_ROOT  Summary: $RESULTS_ROOT/summary/"
  exit 0
else
  echo " Done with warnings (compare=$RC_CMP summarize=$RC_SUM). Check logs." >&2
  exit "$RC_CMP"
fi
