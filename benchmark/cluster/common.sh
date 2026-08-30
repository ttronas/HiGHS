#!/bin/bash
# common.sh — shared helpers for woody HiGHS MIPLIB2017 cluster benchmark
# Adapted from benchmark/scripts/common.sh (diss project) — stripped Optuna/DB logic,
# kept container + Slurm + node selection. HiGHS-specific: no MPI, 1 solver per node.
#
# Source: source "${SCRIPT_DIR}/common.sh"
# Provides:
#   find_available_nodes, build_container, submit_slurm_job,
#   time_to_seconds, compute_usr1_offset, ensure_instances

set -u

# Ensure python available on compute nodes (woody)
module load python 2>/dev/null || true

# ── Node Selection ──────────────────────────────────────────────────────────

# find_available_nodes NODEFILE [NEEDED_COUNT] [NPROCS]
#   Finds available nodes respecting tier hierarchy.
#   Returns comma-separated list.
find_available_nodes() {
    local nodefile="${1:?Usage: find_available_nodes NODEFILE [NEEDED_COUNT] [NPROCS]}"
    local needed="${2:-999999}"
    local nprocs="${3:-1}"

    if [ ! -f "$nodefile" ]; then
        echo "Error: Nodefile not found: $nodefile" >&2
        return 1
    fi

    declare -A NODE_STATE
    declare -A NODE_IDLE
    while IFS= read -r line; do
        node=$(echo "$line" | awk '{print $1}')
        state=$(echo "$line" | awk '{print $2}')
        cpus=$(echo "$line" | awk '{print $3}')
        idle_cpus=$(echo "$cpus" | cut -d/ -f2)
        NODE_STATE["$node"]="$state"
        NODE_IDLE["$node"]="$idle_cpus"
    done < <(sinfo -N -h -o "%N %T %C" 2>/dev/null | tr -d '\r')

    local available=""
    local count=0
    declare -A SELECTED

    while IFS= read -r tier; do
        [ -z "$tier" ] && continue
        [[ "$tier" =~ ^# ]] && continue
        tier_nodes=$(scontrol show hostnames "$tier" 2>/dev/null | tr -d '\r' || true)
        [ -z "$tier_nodes" ] && continue

        # idle first
        while IFS= read -r node; do
            [ -z "$node" ] && continue
            [ "$count" -ge "$needed" ] && break
            [ "${SELECTED[$node]:-}" = "1" ] && continue
            if [ "${NODE_STATE[$node]:-}" = "idle" ]; then
                idle=${NODE_IDLE[$node]:-0}
                if [ "$idle" -ge "$nprocs" ]; then
                    if [ -n "$available" ]; then available="${available},${node}"; else available="$node"; fi
                    SELECTED["$node"]=1; count=$((count + 1))
                fi
            fi
        done <<< "$tier_nodes"

        # then mix
        while IFS= read -r node; do
            [ -z "$node" ] && continue
            [ "$count" -ge "$needed" ] && break
            [ "${SELECTED[$node]:-}" = "1" ] && continue
            if [ "${NODE_STATE[$node]:-}" = "mix" ]; then
                idle=${NODE_IDLE[$node]:-0}
                if [ "$idle" -ge "$nprocs" ]; then
                    if [ -n "$available" ]; then available="${available},${node}"; else available="$node"; fi
                    SELECTED["$node"]=1; count=$((count + 1))
                fi
            fi
        done <<< "$tier_nodes"

        if [ "$count" -gt 0 ]; then break; fi
    done < "$nodefile"

    echo "$available"
}

# ── Container ───────────────────────────────────────────────────────────────

# build_container REPO_ROOT [FORCE]
#   Builds Apptainer SIF from woody.def if missing or force=true.
build_container() {
    local repo_root="${1:?Usage: build_container REPO_ROOT [FORCE]}"
    local force="${2:-false}"
    local def_file="${repo_root}/benchmark/cluster/woody.def"
    local sif_file="${repo_root}/benchmark/cluster/highs-bench.sif"

    if [ ! -f "$def_file" ]; then
        echo "Error: Def not found: $def_file" >&2; return 1
    fi
    if [ -f "$sif_file" ] && [ "$force" = false ]; then
        echo "[container] exists: $sif_file"
        return 0
    fi
    echo "[container] building $sif_file from $def_file ..."
    cd "$repo_root"
    if command -v apptainer >/dev/null 2>&1; then
        apptainer build --fakeroot "$sif_file" "$def_file"
    elif command -v singularity >/dev/null 2>&1; then
        singularity build --fakeroot "$sif_file" "$def_file"
    else
        echo "Error: neither apptainer nor singularity found" >&2; return 1
    fi
    echo "[container] built: $sif_file"
}

# container_exec REPO_ROOT CMD...
#   Thin wrapper: apptainer exec with repo bind + proxy env.
container_exec() {
    local repo_root="${1:?Usage: container_exec REPO_ROOT CMD...}"; shift
    local sif_file="${repo_root}/benchmark/cluster/highs-bench.sif"
    if [ ! -f "$sif_file" ]; then echo "Error: SIF not found: $sif_file (run build_container)" >&2; return 1; fi
    local rt="apptainer"
    command -v apptainer >/dev/null 2>&1 || rt="singularity"
    "$rt" exec \
        --bind "${repo_root}:/workspaces/HiGHS" \
        --pwd /workspaces/HiGHS \
        --env LC_ALL=C \
        --env PYTHONUNBUFFERED=1 \
        --env http_proxy=http://proxy:80 \
        --env https_proxy=http://proxy:80 \
        --env CCACHE_DIR=/workspaces/HiGHS/.ccache \
        "$sif_file" "$@"
}

# ── Slurm ───────────────────────────────────────────────────────────────────

# submit_slurm_job REPO_ROOT TIMEPERJOB USR1_OFFSET NPROCS NODEFILE WORKER_SCRIPT [EXTRA_ARGS...]
#   Echoes "<jobid> <node>"
submit_slurm_job() {
    local repo_root="$1" timeperjob="$2" usr1_offset="$3" nprocs="$4" nodefile="$5" worker_script="$6"; shift 6
    local extra_args=("$@")
    local sched_args=() available=""
    if [ -f "$nodefile" ]; then
        available=$(find_available_nodes "$nodefile" 1 "$nprocs" 2>/dev/null || true)
        if [ -n "$available" ]; then sched_args+=(--nodelist="$available"); fi
    fi
    local node_desc; if [ -n "$available" ]; then node_desc="$available"; else node_desc="(Slurm assigns)"; fi
    if ! command -v sbatch >/dev/null 2>&1; then
        echo "Error: sbatch not found (not on cluster frontend?)" >&2
        echo "DRY-0 $node_desc"
        return 1
    fi
    local sbatch_output jobid
    sbatch_output=$(sbatch \
        --chdir="$repo_root" \
        --time="$timeperjob" \
        --signal=B:USR1@${usr1_offset} \
        -n "$nprocs" \
        --cpus-per-task=4 \
        --nodes=1 \
        "${sched_args[@]}" \
        "$worker_script" \
        "${extra_args[@]}")
    jobid=$(echo "$sbatch_output" | grep -oE '[0-9]+$')
    echo "$jobid $node_desc"
}

# ── Helpers ─────────────────────────────────────────────────────────────────

time_to_seconds() {
    local t="$1"
    if [[ "$t" =~ ^([0-9]+):([0-9]+):([0-9]+)$ ]]; then
        echo $(( ${BASH_REMATCH[1]}*3600 + ${BASH_REMATCH[2]}*60 + ${BASH_REMATCH[3]} ))
    elif [[ "$t" =~ ^([0-9]+):([0-9]+)$ ]]; then
        echo $(( ${BASH_REMATCH[1]}*60 + ${BASH_REMATCH[2]} ))
    else
        echo $(( ${t%%[^0-9]*} * 60 ))
    fi
}

compute_usr1_offset() {
    local s="$1" offset=600
    if [ "$s" -lt 600 ]; then
        if [ "$s" -le 60 ]; then offset=10; else offset=60; fi
    fi
    echo "$offset"
}

# ensure_instances REPO_ROOT
#   Downloads MIPLIB2017 instances if missing (317MB zip -> 240 .mps.gz)
ensure_instances() {
    local repo_root="${1:?Usage: ensure_instances REPO_ROOT}"
    local inst_dir="${repo_root}/benchmark/instances"
    if [ -d "$inst_dir" ] && ls "$inst_dir"/*.mps.gz >/dev/null 2>&1; then
        echo "[instances] present: $(ls "$inst_dir"/*.mps.gz 2>/dev/null | wc -l) files"
        return 0
    fi
    echo "[instances] missing — downloading via download_instances.py inside container..."
    container_exec "$repo_root" uv run python benchmark/scripts/download_instances.py
}

