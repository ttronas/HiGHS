# HiGHS vs Gurobi benchmark

Reproduces the setup of [H. Mittelmann's MIP benchmark](https://plato.asu.edu/ftp/milp.html)
(MIPLIB2017 benchmark set, 240 instances, 12 threads, 7200 s time limit) on
your own machine, inside a devcontainer, so you can **benchmark your HiGHS
build against Gurobi** as you develop.

The reference table (`benchmark/reference/mittelmann-12threads.res`) is the
upstream result set for context. It is **not** comparable byte-for-byte with
local runs: Mittelmann used the *preprocessed* v1 instances on specific
hardware. All local HiGHS-vs-Gurobi comparisons below are apples-to-apples
because both solvers run the same instances, threads, time limit and gap.

> Gurobi is commercial software. It is **installed** inside the devcontainer
> (via the `gurobipy` pip wheel, which bundles the full solver) and licensed at
> runtime, but the software and license are never committed. What is committed
> is the per-instance **result cache** under `benchmark/results/gurobi/`.

---

## Requirements

- Docker Desktop (or another Docker daemon) - verified working in `.devcontainer`
- VS Code with the "Dev Containers" extension
- A Gurobi license: free [academic](https://www.gurobi.com/academia/for-universities/)
  or [free trial](https://www.gurobi.com/free-trial/) licenses work
- `gh` (GitHub CLI), if you want to pull upstream: `gh repo sync` / PRs

## Setup

1. **License**: Gurobi is needed only if you run the `gurobi` solver.
   - Named-user: place `gurobi.lic` at `benchmark/gurobi.lic` **or**
     `.devcontainer/gurobi.lic`
   - WLS: copy `benchmark/.env.example` to `benchmark/.env` and fill
     `GRB_WLSACCESSID` / `GRB_WLSPASSWORD` / `GRB_LICENSEID`
   Both files are gitignored. `postCreate.sh` picks them up when the container
   is created. If you add the license **after** the container exists, rerun:
   ```bash
   bash .devcontainer/postCreate.sh
   ```
   (or restart with a rebuild).

2. **Open the devcontainer**: `code .` -> Cmd/Ctrl+Shift+P ->
   "Dev Containers: Reopen in Container". The first build:
   - installs the C++ toolchain (CMake/Ninja/ccache/clang)
   - creates the benchmark Python env with `uv` (`gurobipy`, `matplotlib`)
   - builds a **release** HiGHS binary at `build/bin/highs`

## Download instances (once)

```bash
cd benchmark
uv run python scripts/download_instances.py            # ~317 MB -> benchmark/instances/
uv run python scripts/download_instances.py --fetch-reference   # refresh benchmark/reference/
```

## Run a benchmark

Workflow: edit <solver changes in HiGHS> -> rebuild -> run -> summarize.

```bash
# rebuild after editing HiGHS source
./scripts/build_highs.sh                    # release; ./scripts/build_highs.sh --debug for dev

# smoke test (3 instances, both solvers)
uv run python scripts/run_benchmark.py --subset 3

# single instance
uv run python scripts/run_benchmark.py --instance p_air05

# full benchmark (matches Mittelmann: 12 threads, 7200 s, 240 instances)
uv run python scripts/run_benchmark.py

# Gurobi only, ignoring cache:
uv run python scripts/run_benchmark.py --solver gurobi --force --subset 1
```

| flag | default | meaning |
|---|---|---|
| `--solver highs gurobi` | `highs gurobi` | which solvers to run; both share `/`params below |
| `--threads` | 12 | solver threads (**identical for every solver**) |
| `--time-limit` | 7200.0 | seconds per instance |
| `--mip-gap` | 1e-4 | relative gap tolerance |
| `--subset N` | - | first N instances (smoke test) |
| `--instance NAME` | - | run only named instance(s), repeatable |
| `--force` | off | ignore the cache and re-run |
| `--highs-bin` | build/bin/highs | HiGHS executable |
| `--highs-parallel` | on | pass `--parallel on|off` to the HiGHS binary |

## Results cache

Each run writes a JSON record per (solver, instance):

```
benchmark/results/{solver}/{solver_version}/{machine}/{instance}.json
```

The version indirection means Gurobi is **run once per version per machine**:
when you iterate on HiGHS (same version bump aside) Gurobi results are reused
and you never re-run Gurobi. The cache is invalidated by checking the instance
file hash and the options hash (`threads`/`time-limit`/`mip-gap`/`parallel`).

- `results/gurobi/` is **committed** - the Gurobi reference you compare against.
- `results/highs/` is gitignored (churns as you develop); commit a snapshot
  explicitly with `git add -f benchmark/results/highs` if you want it tracked.
- `results/summary/` (plots/CSVs, generated) is gitignored.

Run times are not portable: results are per-`machine` (CPU model + core/RAM
fingerprint), so rerunning on different hardware lands in a different machine
folder and is never mixed.

## Compare & plot

```bash
uv run python scripts/summarize.py --reference benchmark/reference/mittelmann-12threads.res
```

Prints a Mittelmann-style table (solved count, unscaled and shifted-geomean
runtime means; timeouts counted at the limit) for every available solver series
and writes a **performance profile** (Dolan-More) plot of all series that
share instances:

```
benchmark/results/summary/performance_profile_<timestamp>.png
```

## Extending to another solver

Solvers are pluggable - Gurobi is just the reference example.

1. Subclass `Solver` in `benchmark/scripts/solvers.py` and implement
   `name`, `version()` and `solve(instance, params, workdir) -> record`.
   `record` must carry at least: `status`, `runtime_s`, `objective`,
   `dual_bound`, `gap`.
2. Register the class in the `make_solvers`/`KNOWN_SOLVERS` registry.
3. If the solver has a Python API add it to `benchmark/pyproject.toml` and
   let `uv sync` install it; otherwise drive it via subprocess like HiGHS.

The harness gives every solver the same `RunParams` (threads, time limit,
MIP gap), keys its cache by `{solver}/{version}/{machine}`, and includes it in
`summarize.py` automatically.

## Notes / caveats

- Instances: official MIPLIB2017 **benchmark set v2** (`benchmark.zip`, 317 MB)
  from `miplib.zib.de`; instance-name lists and the `.solu` validation file are
  in `benchmark/reference/`.
- The Mittelmann table (/`12threads.res`) used v1-preprocessed instances on a
  Ryzen 9 5900X. Use it only as a rough sanity anchor, never as a cross-machine
  measurement.
- Full runs (240 x 7200 s) take hours; use `--subset` for iteration and the
  full run for final numbers.
- Gurobi license check happens at container creation; if Gurobi prints a
  licensing error during a run, fix the license and rerun with `--force`.
