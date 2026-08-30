# Woody cluster benchmark — HiGHS 1.15.1 .. 1.15.1.8 + Gurobi (full MIPLIB2017)

Frontend orchestrator lives in `benchmark/cluster/`. Woody `w14xx,w15xx` Tier1 only, homogeneous, 4 cores = 4 threads per solver, `60s` per instance, `miplib2017` set.

## Layout

- `woody.def` — Apptainer def derived from `.devcontainer/Dockerfile` + `uv` + `ccache`. Proxy `http://proxy:80` baked.
- `nodefile.tier1` — `w14[0-9][0-9]` + `w15[0-9][0-9]` only (homogeneous throughput nodes, 4 cores).
- `versions.txt` — `1.15.1 v1.15.1` .. `1.15.1.8 4c2f9b6f63` (tag or commit per version).
- `common.sh` — `find_available_nodes` (idle→mix, tier-priority), `build_container`, `container_exec`, `submit_slurm_job` (`-n 1 --cpus-per-task=4 --nodes=1`), `ensure_instances`.
- `build_versions.sh` — inside-container builds: `git worktree` per version → `cmake -G Ninja Release` with `ccache` → `benchmark/cluster/binaries/highs-<ver>` + `manifest.json`.
- `run_shard.sh` — Slurm worker: 1 node, 1 solver, 4 threads, 60s, containerized `run_benchmark.py`. Handles `USR1/TERM`, `Gurobi` license check, `--force` passthrough.
- `submit_benchmark.sh` — frontend 4-phase orchestrator (see below).

All paths are `$HOME` (`benchmark/instances`, `benchmark/results`, `benchmark/cluster/highs-bench.sif`).

## Phases (submit_benchmark.sh)

```
1. Container   build_container $REPO (woody.def -> highs-bench.sif) if missing / --force
1b.Instances  ensure_instances $REPO (download_instances.py inside container, 317MB zip -> 240 .mps.gz)
2. Builds     build_versions.sh --versions-file versions.txt (inside container, ccache, worktrees)
3. Submit     1 Slurm job per version (9) + 1 Gurobi =10 jobs, each:
                sbatch --time=05:00:00 --signal=B:USR1@600 -n 1 --cpus-per-task=4 --nodes=1
                       [--nodelist=<idle Tier1>] run_shard.sh --version X --solver highs --threads 4 --time-limit 60 --set miplib2017
4. Wait+Compare poll squeue until all done, then inside container:
                compare_versions.py --set miplib2017 --versions 1.15.1 ..1.15.1.8 --mode baseline --time-limit 60
                summarize.py --set miplib2017
              writes cluster_report_*.json + performance_profile_*.png under results/summary/
```

`run_benchmark.py` cache `results/{solver}/{version}/{machine}/{set}/*.json` keyed by `options_hash(threads,time_limit,mip_gap)` + `binary_sha256`; reruns skip cached (use `--force-run` to invalidate). Gurobi token server `license.rrze.de:1790` reachable via proxy.

## Usage on woody frontend

```bash
# 1. Clone already at $HOME/HiGHS (or wherever $REPO is) — cd there
cd $HOME/HiGHS  # or $(git rev-parse --show-toplevel)

# Preview (no Slurm submission)
./benchmark/cluster/submit_benchmark.sh --dry-run --no-build

# Full run (container + builds + submit + wait + compare)
./benchmark/cluster/submit_benchmark.sh

# Faster walltime / force
./benchmark/cluster/submit_benchmark.sh --timeperjob 05:00:00 --force-run

# Only rebuild binaries
./benchmark/cluster/build_versions.sh --force

# Only compare after jobs finished (no submit)
./benchmark/cluster/submit_benchmark.sh --no-build --no-submit

# Check versions
cat benchmark/cluster/versions.txt
cat benchmark/cluster/binaries/manifest.json
ls -lh benchmark/cluster/binaries/highs-*

# Monitor after submit
squeue -u $USER
sacct -j <jobid> --format=JobID,State,Elapsed,NodeList

# Inspect results after
apptainer exec --bind $HOME/HiGHS:/workspaces/HiGHS benchmark/cluster/highs-bench.sif \
  uv run python benchmark/scripts/compare_versions.py --set miplib2017 --versions 1.15.1 1.15.1.8 --time-limit 60
```

## Model

- Each version =1 Slurm job =1 node =1 containerized solver process. 1 solver uses 4 threads (4 cores) sequentially over 240 instances (240×60s=4h + overhead → 5h walltime). 10 nodes in parallel for all versions. No sharding / no oversubscription.
- Container: `apptainer exec --bind $REPO:/workspaces/HiGHS --pwd /workspaces/HiGHS --env http_proxy=... SIF uv run ...` — deps isolated, repo mounted read-write so results land on shared FS.
- Resume: if walltime hit, partial `results/.../*.json` kept; resubmit same command continues from cache (missing instances only). Use `--force-run` to ignore cache.
- Homogeneity: limit to `w14xx,w15xx` via `nodefile.tier1`; `find_available_nodes` picks idle first, stops at first tier with nodes.

## Troubleshooting

- `sbatch: command not found` → not on woody frontend.
- `SIF not found` → run `benchmark/cluster/build_versions.sh` or `submit_benchmark.sh` (phase1).
- `binary not found` → check `benchmark/cluster/binaries/highs-<ver> --version`.
- `gurobipy not importable` → `apptainer exec SIF uv run python -c "import gurobipy"`; ensure `benchmark/gurobi.lic` or `benchmark/.env` (GRB_WLS*) present and proxy reachable.
- `no instances` → `ensure_instances` downloads to `benchmark/instances` (fallback `benchmark/sets/miplib2017-benchmark`).
- Time estimate too short → increase `--timeperjob` (default `05:00:00`); `USR1@600` gives 10min graceful window.
