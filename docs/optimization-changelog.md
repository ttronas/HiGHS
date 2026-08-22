# HiGHS Optimization Changelog

Tracks optimization changes to HiGHS. Each entry maps to a benchmark result
version in `results/highs/{version}/`. Version format: `MAJOR.MINOR.PATCH.TWEAK`
where TWEAK increments by 1 per optimization commit.

**CRITICAL**: Changelog version MUST match `Version.txt` at time of commit.
Each optimization commit bumps `HIGHS_TWEAK` by 1. Never skip versions.

**Solver topology diagram**: `README.md` ("Solver topology") contains a mermaid
diagram of the HiGHS solver. **Keep it in sync** whenever a change adds, removes,
renames, or moves a solver component (MIP core, separators, heuristics, LP
solvers, parallel runtime). Update the diagram in the same commit as the code
change so the topology never drifts from the source.
**Mermaid label rule**: node labels must NOT contain `::`, `()`, or `.` — the
parser chokes on them (`got 'PS'`). Use `HighsMipSolver run` not
`HighsMipSolver::run()`.

## Current Status

| Version | Status | Description |
|---------|--------|-------------|
| 1.15.1.0 | ✅ Implemented | Baseline (upstream HiGHS 1.15.1) |
| 1.15.1.1 | ✅ Implemented | Tier 1 hotspot fixes (CHUZC, freeList, propagate, etc.) |
| 1.15.1.2 | ✅ Implemented | Heuristic effort tuning (0.05 → 0.1) |
| 1.15.1.3 | ✅ Implemented | Raw GMI cut `generateGmiCut`; **node presolve OFF** |
| 1.15.1.4 (parallel-redesign) | ❌ Rejected | Measured slower than 1.15.1.3 in 2 benchmark runs; kept on branch `parallel-redesign2` |
| 1.15.1.5 | ✅ Implemented | Raw GMI `generateGmiCut` + node LP presolve (threshold 200000) |
| 1.15.1.6 | ✅ Implemented | Idiomatic GMI `generateGomoryCut` + node LP presolve |

**Last updated**: Version 1.15.1.6 (HIGHS_TWEAK=6)

## Version matrix (feature focus)

| Version | GMI | Node presolve |
|---------|-----|---------------|
| 1.15.1.3 | raw `generateGmiCut` | OFF |
| 1.15.1.5 | raw `generateGmiCut` | ON |
| 1.15.1.6 | idiomatic `generateGomoryCut` | ON |

## Harness changes (no version bump — benchmark infra only)

Changes to the benchmark harness, not the solver. No `HIGHS_TWEAK` bump, no
`Version.txt` change, no solver optimization.

| Change | File | Effect |
|--------|------|--------|
| `--instances-file` support + canonical set names | `run_benchmark.py` | run a `.txt` instance list; result set auto-named (`fast`/`super-fast`/`miplib2017`) |
| Multi-root instance resolution | `run_benchmark.py` | list names resolved across examples + miplib set folders |
| Rebuilt baseline binary `highs-1.15.1` static | `binaries/` | old binaries were dynamically linked to missing `libhighs.so.1` and crashed; rebuilt from tag `v1.15.1` |
| `--solved-only` default in `compare_versions.py` | `compare_versions.py` | timeouts excluded from shared set + geomean (true solve time unknown; 60s is a lower bound). `--include-timeouts` restores fold-at-cap |
| Cross-solver compare | `compare_versions.py` | `solver:version` spec, e.g. `gurobi:12.0.3`, plus `--solver` |
| Gurobi runner: guard `ObjVal`/`ObjBound` | `gurobi_runner.py` | infeasible models have no `ObjVal`; unguarded access crashed the worker → false "error" status |

Full MIPLIB2017 clean run (240 inst, 60s limit) for all 5 HiGHS versions +
Gurobi recorded in `optimization-findings.md`.

## Rejected experiments

Ported upstream `parallel-redesign` MIP core onto 1.15.1.3 (12 files under
`highs/mip/`; worker count = num_threads, per-worker processedNodes stash,
all-workers heuristics, deterministic early termination). Built clean, ctest
160/168 (8 PDLP failures unrelated). **Rejected**: benchmarked twice, slower
than 1.15.1.3 on the MIPLIB2017 fast subset both times. Work preserved on
branch `parallel-redesign2` (commit `51c8819cc9`). Master stays on 1.15.1.3.

### 1.15.1.8 (aborted) — parallel-redesign port on GMI + node presolve

Re-ported the upstream `parallel-redesign` MIP core onto current master
(1.15.1.6), keeping the idiomatic GMI (`generateGomoryCut`) and node LP
presolve intact (merged only the 12 `highs/mip/` redesign files; GMI +
`mip_node_presolve_threshold` verified present post-merge). Batch-based search:
per-worker `preparedNodes`/`processedNodes` stash, `maxNodesPerWorkerLim=100`
batch commit, deterministic early termination. Built clean; ctest failures were
identical to baseline (pre-existing CHUZC iteration-count drift, not port
regressions). **Aborted — rejected.**

**Full-set benchmark (240 MIPLIB2017, 60s, 12 threads)** vs 1.15.1.6:
- shifted-geomean(10, timeouts folded) **27.965s → 35.003s, ratio 1.25**
- 240 shared, **23 faster / 217 slower**
- **Time-limit enforcement broken**: instances ran 30-44× over the 60s cap
  (s100 199→2637s, nw04 60→1907s, nursesched-medium 61→2191s, co-100
  62→384s); co-100 crashes in probing (exit 255).

**Verdict**: the redesign's batching saves sync cost but pays a massive
staleness cost + breaks time-limit checks inside the batch loop. On this
12-thread/60s workload it is a net regression. Rejected; work preserved on
branch `failed/parallel-redesign/1.15.1.8` (commit `fa1a771067`). Master
stays on 1.15.1.6.

### 1.15.1.7 (aborted) — `parallel=auto` worker-count scaling

Attempted to make parallelism adaptive. Added `kHighsAutoString="auto"` to
`parallel` option (default), validator acceptance, and two worker-count variants
in `HighsMipSolver::getMaxNumWorkers()` (baseline: fixed `ceil(1.7*threads)`=21
workers on 12 threads). **Aborted — never committed, all code reverted.**

Variant A (size-scaled): log-scale worker ceiling across nonzero count
`[1e3, 2e6]`, 1 → full. Variant B (contention cap): `min(num_threads, 1.7×)` =
12 workers.

**Full-set benchmark (240 MIPLIB2017, 60s, 12 threads)** vs 1.15.1.6:
- shifted-geomean(10) **5.283s → 8.921s, ratio 1.69** — regression
- 98 shared, **96 slower / 2 faster**

**Verdict**: both worker-count reductions regress on the full 240-set. MIPLIB
instances are *tree-search-bound*, not size-bound — a tiny matrix (e.g. `neos5`,
2016 nz) still branches into a huge tree and needs all 21 workers; `neos5`
solves in ~12s with `on` but times out with ~3 workers. The changelog's older
claim "parallel `on` hurts small instances" does **not** hold on the full
240-set. The 1.7× over-subscription is latency-hiding/load-balance headroom
across node-queue stalls, not wasted contention. Baseline `parallel="on"`
(1.7×) is empirically best; worker-count is the wrong lever.

## Version History

### 1.15.1.0 — Baseline

Upstream HiGHS 1.15.1 (commit `32f8319c5e`). No optimization changes.

### 1.15.1.1 — Tier 1 Hotspot Fixes

All changes verified with benchmark harness (smoke + subset).

| Change | File | Impact |
|--------|------|--------|
| CHUZC sort: enable heap path for `workCount >= 100` | `HEkkDualRow.cpp:159-164` | Eliminates O(n^2) sort on large dense candidate sets |
| freeList: replace `std::set` with packed vector + mark array | `HEkkDualRow.h:170`, `HEkkDualRow.cpp:568-612` | Cache-friendly iteration, O(1) membership test |
| propagate: cache reusable `HighsDomainChange` buffer | `HighsDomain.h:348`, `HighsDomain.cpp:2393-2394` | Eliminates per-call heap allocation on MIP hot path |
| `-march=native` opt-in build flag | `CMakeLists.txt:103-107,495-501` | Free 10-30% on CPU-bound loops; opt-in via `-DMARCH_NATIVE=ON` |
| `HighsCombinable::combine`: fix thread copy drop bug | `HighsCombinable.h:95-101` | Removes `break` that silently dropped copies >2 |
| Dead code: remove `exit(0)` in clique overload | `HighsCliqueTable.cpp:1716-1720` | Eliminates crash in unused code path |
| `parallel` default: "choose" -> "on" | `HighsOptions.h:762` | MIP uses 12 threads by default |

### 1.15.1.2 — Heuristic Effort Tuning

| Change | File | Impact |
|--------|------|--------|
| `mip_heuristic_effort`: raise default from 0.05 to 0.1 | `HighsOptions.h:1225` | Doubles heuristic effort budget; 35/38 instances improved, median 27% faster |

**Benchmark results (1.15.1.2 vs 1.15.1.1)**:
- 35 instances improved, 3 regressed, median improvement 27%
- Biggest: `nursesched-sprint02.mps` 440s → 45s (90% faster)
- Regressions: `piperout-27.mps` 46s → 61s (minor, still solves)

### 1.15.1.3 — Tier 1 fixes + raw GMI cut (node presolve OFF)

Reconstructed commit: Tier-1 hotspot fixes (CHUZC heap sort, freeList packed
vector, propagate buffer, HighsCombinable fix, march=native opt-in, dead code
cleanup, `parallel` default on, heuristic effort 0.1) plus a **raw Gomory
Mixed-Integer cut** `generateGmiCut` in the tableau separator. **Node LP
presolve is NOT enabled** (feature lands in 1.15.1.5).

| Change | File | Impact |
|--------|------|--------|
| Raw GMI cut `generateGmiCut`: fractional parts of integer-row coefficients, direct `cutpool.addCut` in original space, after each `generateCut` on the aggregated tableau row | `highs/mip/HighsTableauSeparator.cpp` | Strong single-row Gomory cut |
| Tier-1 hotspot fixes (see 1.15.1.1/1.15.1.2 rows) | `highs/simplex/`, `highs/mip/`, `highs/parallel/` | Eliminates O(n^2) sort, cache-hostile set, per-call alloc |
| Version plumbing: `HIGHS_TWEAK` parse + print in `--version` | `cmake/set-version.cmake`, `CMakeLists.txt`, `app/HighsRuntimeOptions.h` | Versioned result dirs |

**Note**: GMI is a *raw* fast path here (bypasses the transform/postprocess cut
pipeline). The idiomatic `generateGomoryCut` version is 1.15.1.6.

### 1.15.1.5 — Node LP presolve + raw GMI

Adds node LP presolve on top of 1.15.1.3 (raw `generateGmiCut` GMI unchanged).

| Change | File | Impact |
|--------|------|--------|
| Node/local LP presolve: for node solves whose relaxation has ≥ `mip_node_presolve_threshold` nonzeros (default 200000), run LP presolve and re-solve the reduced model from scratch (postsolve back); discards the parent warm-start basis | `highs/mip/HighsLpRelaxation.cpp` | Shrinks large node relaxations |
| New option `mip_node_presolve_threshold` (0 disables; default 200000) | `highs/lp_data/HighsOptions.h` | Tuning knob |

**Benchmark (super-fast, 135 instances, 15s limit)** — node-presolve effect on
raw GMI (1.15.1.3 vs 1.15.1.5):
- Overall shifted-geomean(10): **1.15.1.3 2.463s → 1.15.1.5 2.370s, ratio 0.962**
  (70 instances faster, 65 slower) — net slightly positive.
- **17 large instances (≥200k nz, where node presolve actually engages)**:
  shifted-geomean(10) **7.742s → 7.193s, ratio 0.929**; summed runtime
  **136.9s → 126.9s (−10.0s, −7.3%)**. 10 faster, 6 slower, 1 equal.
  Biggest wins: `rocII-5-11` −24%, `thor50dday` −21%, `ex9` −20%,
  `rd-rplusc-21` −15%, `neos-662469` −14%. Regressions: `sp98ar` +13.9%,
  `neos-5093327-huahum` +14.3%.
- Verdict: node presolve is a net positive specifically on the large-instance
  subset it targets; the mixed all-instance result reflects the ~17/135
  instances that actually trigger it.

### 1.15.1.6 — Idiomatic Gomory cut `generateGomoryCut` + node presolve

Swaps the raw `generateGmiCut` fast path for the idiomatic cut-pipeline version.
Node LP presolve unchanged from 1.15.1.5.

| Change | File | Impact |
|--------|------|--------|
| Add `HighsCutGeneration::generateGomoryCut`: transform row, complement via `preprocessBaseInequality`, generate pure Gomory cut as `cmirCutGenerationHeuristic(minEfficacy, true)` (MIR at delta=1, skipping cover/lifting/delta-search), untransform, `finalizeAndAddCut` for efficacy/violation/duplicate gating | `highs/mip/HighsCutGeneration.{h,cpp}` | Idiomatic single-row Gomory cut |
| Replace standalone `generateGmiCut` with `generateGomoryCut` (same structure: 2x `generateCut` + 2x Gomory) | `highs/mip/HighsTableauSeparator.cpp` | GMI flows through the standard cut pipeline |

**Benchmark (super-fast, 135 instances, 15s)** — GMI approach with node
presolve on (1.15.1.5 vs 1.15.1.6): shifted-geomean(10) **2.370s → 6.853s,
ratio 2.891**. The idiomatic `generateGomoryCut` is ~2.9x **slower** than the
raw `generateGmiCut` (15 faster, 120 slower). The transform/untransform +
postprocess + violation/duplicate-gating overhead dominates on the short
fractional rows the tableau separator feeds. **Verdict: idiomatic path is
correct but materially slower — keep raw GMI for performance; idiomatic is a
correctness-grade fallback.**

---

## Implemented Changes (for new agents)

### What's Done (Tier 1 + partial Tier 2)

| Item | Status | Version | Notes |
|------|--------|---------|-------|
| 1. CHUZC heap sort | ✅ Done | 1.15.1.1 | Enable heap path for `workCount >= 100` |
| 2. freeList replacement | ✅ Done | 1.15.1.1 | Packed vector + mark array + position map |
| 3. propagate buffer | ✅ Done | 1.15.1.1 | Cache reusable `HighsDomainChange` buffer |
| 4. `-march=native` | ✅ Done | 1.15.1.1 | Opt-in via `-DMARCH_NATIVE=ON` |
| 5. HighsCombinable bug | ✅ Done | 1.15.1.1 | Fix thread copy drop in `combine` |
| 6. Dead code cleanup | ✅ Done | 1.15.1.1 | Remove `exit(0)` in clique overload |
| 7. Node presolve | ✅ Done | 1.15.1.5 | Option-gated LP presolve on large node LPs |
| 8. Heuristic effort | ✅ Done | 1.15.1.2 | Raised from 0.05 to 0.1 |
| 9. GMI cuts | ✅ Done | 1.15.1.5 | GMI (delta=1) cut from each fractional tableau row (was falsely claimed in 1.15.1.3) |
| 10. Dual-implied-bound | ❌ Not done | — | Partially in flight (`probe-dual-fix`) |
| 11. Parallel MIP | ❌ Not done | — | Upstream `parallel-redesign` in progress |
| 12. Parallel strong branching | ❌ Not done | — | Serial today |

### What's NOT Implemented (do these next)

| Item | Priority | Effort | Location |
|------|----------|--------|----------|
| 10. Dual-implied-bound cuts | Medium | Medium | Partially in flight (`probe-dual-fix`) |
| 12. Parallelize strong branching | Medium | Medium | `HighsSearch.cpp:533-692` |
| 13. Harris ratio test | Low | Medium | Tier 3 simplex improvement |
| 14. BLAS for factor | Low | High | Large effort |
| 20. MIQP support | High | High | No hessian in `highs/mip/` (capability gap) |
| 21. Convex QCP/SOCP | Medium | Very High | No quadratic constraint code (capability gap) |

### In-flight upstream (don't duplicate)

`strongcg`, `flow-cover-cuts`, `persistent-clique-table`, `probe-dual-fix`,
`precedence-cons`, `parallel-redesign`, `tarjan`,
`keep-implications-between-restarts`, `local-mip`, `machine-schedule-sepa`,
`solver-select`

Check `git branch -r` before starting any Tier 2 item.

### Learnings

- **freeList replacement**: when using packed vector + mark array, `deleteFreelist(iVar)` takes a variable index, NOT a position. Must maintain a reverse-position array.
- **propagate buffer**: use `.resize()` not `.reserve()` — reserve leaves vector empty.
- **HighsCombinable::combine**: check ALL thread copies, not just first two.
- **CHUZC threshold**: 100 is a starting point; profile before adjusting.
- **parallel default**: changing from "choose" to "on" makes MIP use all threads by default; affects small instances negatively due to overhead.
- **worker-count ≠ performance (1.15.1.7)**: MIPLIB2017 is tree-search-bound, not size-bound. `getMaxNumWorkers()` ceiling is fixed at `ceil(1.7*threads)` regardless of matrix size; only the *actual* spawn is demand-driven by live open-node count (`HighsMipSolver.cpp:1000`). Both a size-scaled ceiling and a `num_threads` cap regressed the full 240-set (ratio 1.69). Keep `on` (1.7× over-subscription) — it is load-balancing headroom, not wasted contention. Do NOT gate worker count on matrix nonzeros.
- **sync less ≠ free**: batching cut/domain sync (parallel-redesign) trades sync cost for staleness (subtree redundancy + discarded buffered `processedNodes` on early termination). Batch size is a U-curve (`cost = c1/batch + c2*batch`), optimum unknown — sweep {1,10,50,100,500} on the large subset before trusting 100. Nodes are NOT generated blindly: children only branch after evaluation gates them (suboptimal→stash, pruned→backtrack).
- **parallel-redesign**: upstream's per-worker nodequeue → processedNodes batch stash, `maxNodesPerWorkerLim=100` ramp-up, and 1:1 thread mapping were **measured slower** than the vanilla 1.15.1.3 parallel path (2 benchmark runs). Benchmark any parallel-MIP change on a quiet machine with a real 1.15.1.3 baseline before adopting — do not cherry-pick upstream parallel redesign blindly.
- **parallel-redesign breaks time limits (1.15.1.8)**: the batch loop commits work in `maxNodesPerWorkerLim` chunks and only checks the clock at batch boundaries, so on long node batches the solver ignores `time_limit` for 30-44× the cap. ANY batched-parallel port MUST check time limit inside the per-node loop, not just at batch commit. Always A/B the port against the real baseline binary (`benchmark/binaries/highs-1.15.1.6`) — the 1.15.1.4 rejection was against a GMI-less 1.15.1.3 and was invalid; the 1.15.1.8 re-port (GMI+node presolve intact) is a genuine 1.25× regression.
