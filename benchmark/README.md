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
| `--solver highs gurobi` | `highs gurobi` | which solvers to run; both share the params below |
| `--threads` | 12 | solver threads (**identical for every solver**) |
| `--time-limit` | 7200.0 | seconds per instance |
| `--mip-gap` | 1e-4 | relative gap tolerance |
| `--subset N` | - | first N instances (smoke test) |
| `--instance NAME` | - | run only named instance(s), repeatable |
| `--instances-root DIR` | `benchmark/instances` | folder holding the problems (drop new ones here) |
| `--results-root DIR` | `benchmark/results` | root of the result caches |
| `--set NAME` | folder name of `--instances-root` | namespaced cache tag (see below) |
| `--prune` | off | delete cached results whose instance no longer exists in the folder |
| `--force` | off | ignore the cache and re-run |
| `--highs-bin` | build/bin/highs | HiGHS executable |
| `--highs-parallel` | on | pass `--parallel on|off` to the HiGHS binary |

## Try it now with the bundled examples

`benchmark/examples/` ships seven tiny MIPs (~10-30 binary/integer vars). They
solve in well under a second and fit even the size-limited Gurobi license, so
you can exercise the full pipeline with zero downloads:

```bash
cd benchmark
uv run python scripts/run_benchmark.py --instances-root examples --time-limit 60 --threads 4
uv run python scripts/summarize.py --set examples
```

## Drop your own problems in (drag & drop)

The harness treats `--instances-root` as an **inbox**: drop any number of
`.mps`, `.lp` (also `.gz`/`.zst`) files into it, run once, and the whole solver
suite solves and compares them. Files are re-read by content hash, so
overwriting a file re-runs that instance; `--prune` forgets results for files
that were removed.

```bash
mkdir -p my-problems            # or reuse benchmark/instances
cp rocket.mps my-problems/
uv run python scripts/run_benchmark.py --instances-root my-problems --time-limit 120

# per-instance table + performance profile + objective agreement check:
uv run python scripts/summarize.py --set my-problems
```

Everything you need for an *unexpected* ad-hoc problem - status, wall time,
objective, bound/gap, and a warning when two solvers both claim "optimal" but
disagree on the objective - shows up in `summarize.py`.

## Test sets (results namespacing)

Distinct experiments never overwrite each other's cache. Results live at

```
benchmark/results/{solver}/{solver_version}/{machine}/{set}/{instance}.json
```

where `{set}` is the name of the folder you pointed `--instances-root` at
(override with `--set NAME`). Drop a `rocket.mps` into `my-problems` and a
different `rocket.mps` into `experiment2`: both keep their own results, and
MIPLIB cache can never be clobbered by an ad-hoc problem with the same name.
`summarize.py --set NAME` focuses on one set (omit it to see everything).

## Results cache

Each run writes a JSON record per (solver, instance), namespaced by test set:

```
benchmark/results/{solver}/{solver_version}/{machine}/{set}/{instance}.json
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
cd benchmark
uv run python scripts/summarize.py --reference benchmark/reference/mittelmann-12threads.res
# ad-hoc sets:  uv run python scripts/summarize.py --set my-problems
```

Prints a Mittelmann-style table (solved count, unscaled and shifted-geomean
runtime means; timeouts counted at the limit) plus a **per-instance matrix** of
every series that shares instances (with objectives printed and a warning when
two "optimal" solvers disagree on the value), and writes a **performance
profile** (Dolan-More) plot:

```
benchmark/results/summary/performance_profile_<timestamp>.png
```

## Extending to another solver

Solvers are pluggable - Gurobi is just the reference example. Anything that
reads MPS/LP and reports a status/objective can be added (SCIP, HiGHS as a
service, MIQCP solvers, ...).

1. Subclass `Solver` in `benchmark/scripts/solvers.py` and implement
   `name`, `version()` and `solve(instance, params, workdir) -> record`.
   `record` must carry at least: `status`, `runtime_s`, `objective`,
   `dual_bound`, `gap`.
2. Register the class in the `make_solvers`/`KNOWN_SOLVERS` registry.
3. If the solver has a Python API add it to `benchmark/pyproject.toml` and
   let `uv sync` install it; otherwise drive it via subprocess like HiGHS.

Sketch for adding SCIP (`pip install pyscipopt` + `pyscipopt` in
`pyproject.toml`); this is documentation, not shipped code:

```python
# in solvers.py
import pyscipopt as scip

class SCIPSolver(Solver):
    name = "scip"

    def version(self) -> str:
        return scip.SCIPPy().getVersion()

    def solve(self, instance, params, workdir):
        t0 = time.monotonic()
        m = scip.readProblem(str(instance))
        m.setParam("limits/time", params.time_limit)
        m.setParam("threads", params.threads)
        m.setParam("limits/gap", params.mip_gap)
        m.optimize()
        record = self._base_record(instance, params)
        record["status"] = "optimal" if m.getStatus() == "optimal" else str(m.getStatus())
        record["runtime_s"] = time.monotonic() - t0
        record["objective"] = m.getObjVal() if m.getObjVal() is not None else None
        record["dual_bound"] = m.getObjBound()
        record["gap"] = abs(m.getGap())
        return record

# register in make_solvers():  "scip": SCIPSolver  (+ known in KNOWN_SOLVERS)
```

The harness gives every solver the same `RunParams` (threads, time limit,
MIP gap), keys its cache by `{solver}/{version}/{machine}/{set}`, and includes
it in `summarize.py` automatically (table, matrix, profile).

### Notes for the SCIP driver (if you enable it)

- `limits/gap` is SCIP's relative gap; objective agreement is then checked by
  `summarize.py` as usual.
- SCIP's `readProblem` accepts `.mps`/`.lp` (not `.gz`); the harness passes raw
  paths, so either ship uncompressed problems or add decompression in the
  driver.

## Notes / caveats

- Instances: official MIPLIB2017 **benchmark set v2** (`benchmark.zip`, 317 MB)
  from `miplib.zib.de`; instance-name lists and the `.solu` validation file are
  in `benchmark/reference/`.
- Fresh ad-hoc problems: put them in any folder, run with `--instances-root`
  and compare with `--set`; the bundled `benchmark/examples/` set is the
  quickest way to see the full pipeline.
- Model/row names in `.lp` files must not contain `-` (LP-format ambiguity;
  HiGHS rejects them, use `_` instead).
- The Mittelmann table (/`12threads.res`) used v1-preprocessed instances on a
  Ryzen 9 5900X. Use it only as a rough sanity anchor, never as a cross-machine
  measurement.
- Full runs (240 x 7200 s) take hours; use `--subset` for iteration and the
  full run for final numbers.
- Gurobi license check happens at container creation; if Gurobi prints a
  licensing error during a run, fix the license and rerun with `--force`.
  Mind the license type: the free/size-limited license caps model size at
  ~2000 vars - fine for `benchmark/examples/`, too small for most MIPLIB
  benchmark instances.
