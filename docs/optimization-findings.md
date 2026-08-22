# HiGHS Optimization Findings & Priority Plan

Research session findings for optimizing HiGHS in this repository. Written to be
picked up by a fresh session for implementation. All paths relative to repo root
`/workspaces/HiGHS`.

## Idiomatic HiGHS conventions (READ FIRST)

General coding conventions for touching HiGHS core. Following these avoids
non-idiomatic dead-ends (e.g. a fast-but-wrong ad-hoc GMI that bypasses the
cut pipeline).

### Cut generation pipeline (MIP)

All cutting planes flow through `HighsCutGeneration` — do NOT bypass it. The
full chain is (see `highs/mip/HighsCutGeneration.cpp`):

```
transLp.transform()            # bound substitution + slack vars, per row
preprocessBaseInequality()     # complementation, integrality, scaling
tryGenerateCut()               # cover/lifting (knapsack, mixed-binary,
                               #   mixed-integer) then CMIR heuristics
removeComplementation()
transLp.untransform()
postprocessCut()               # scale + small-coef removal
violation check                # reject if <= 10*feastol
tightenCoefficients()
cutpool.addCut(...)            # returns -1 if duplicate -> cut rejected
```

- **`HighsTransformedLp transLp` is constructed ONCE per separation call**
  (`HighsSeparation.cpp:132`) and shared across rows. Do NOT rebuild it per row;
  the remaining per-row cost is `transform()`, not construction.
- **Efficacy/violation gating and duplicate detection live in the pipeline.**
  `cutpool.addCut` returns `-1` for duplicates; callers use that to decide
  whether the cut was accepted.
- **A cut that skips the pipeline** (direct `cutpool.addCut`) gains speed but
  loses: continuous-variable handling, complementation, efficacy/violation
  check, scaling, duplicate detection. That is acceptable only for a verified,
  purpose-built fast path (see `generateGmiCut` in `HighsTableauSeparator.cpp`).
- **GMI is `generateCut(..., onlyInitialCMIRScale=true)`**: MIR at initial
  scale = the classic Gomory cut (`cmirCutGenerationHeuristic`). Prefer routing
  GMI through this path rather than hand-rolling fractional rounding, unless a
  measured speed gap justifies a lean fast path.
- **Measured: the idiomatic GMI path is ~2-3x slower than standalone GMI.** A
  `HighsCutGeneration::generateGomoryCut` (transform -> CMIR-at-initial-scale
  directly, no cover/lifting/delta-search, then `finalizeAndAddCut`) was A/B'd
  on super-fast (135 inst, 15s): A/B median 0.47, A faster 98/135. The
  transform/untransform + postprocess + violation/duplicate-gating overhead
  outweighs the saved lifting work for the short fractional rows the tableau
  separator feeds. **Adopted as 1.15.1.6** (deliberate: idiomatic path trades
  raw speed for correctness — complementation, efficacy/violation gating, and
  duplicate detection). A design gap remains: make the idiomatic path skip
  transform/postprocess when the row needs none (a "clean-row fast path") to
  reclaim standalone speed with idiomatic gating.

### Simplex / LP

- Default solver is serial dual revised simplex (`solver="choose"` -> simplex).
- The CHUZC heap path (`chooseFinalWorkGroupHeap`) should be selected for large
  dense candidate sets; a hard-coded quadratic sort is an anti-pattern.
- `std::set` for a free-list / hot iteration structure is cache-hostile;
  prefer packed vector + mark array + reverse-position map for O(1) removal.
- `HighsCombinable::combine` must fold ALL thread copies, not break after the
  first; mark consumed copies `initialized_ = false`.

### Build / version

- `Version.txt` format: `HIGHS_TWEAK=5` (equals sign, CMake regex expects
  `HIGHS_TWEAK=(.*)`). `HConfig.h.in` must carry `#define HIGHS_VERSION_TWEAK`.
- Bump `HIGHS_TWEAK` BEFORE building: the harness reads `highs --version` at
  runtime to namespace results. Unbumped builds overwrite a prior set.
- One optimization commit = one TWEAK bump = one changelog entry.

## Implementation Status (for new agents)

**Current version**: 1.15.1.6 (see `Version.txt`)

### Full MIPLIB2017 benchmark (240 instances, 60s limit, 12 threads)

Clean run on the full 240-instance MIPLIB2017 benchmark set (set tag
`miplib2017`, per-instance 60s time limit, 12 threads, 1e-4 MIP gap), all
five HiGHS versions + Gurobi 12.0.3, single-solver sequential (no overlap).

Solved counts (shifted-geomean(10) in parentheses):

| solver/version | n | solved | scaled geomean |
|---|---|---|---|
| gurobi 12.0.3 | 240 | 98 (96 opt + 2 infeasible) | 33.1 |
| highs 1.15.1 (baseline) | 240 | 34 | 56.5 |
| highs 1.15.1.3 (raw GMI) | 238 | 161 | 17.3 |
| highs 1.15.1.4 (parallel-redesign) | 236 | 34 | 55.9 |
| highs 1.15.1.5 (raw GMI + node presolve) | 240 | 157 | 18.2 |
| highs 1.15.1.6 (idiomatic GMI) | 238 | 117 | 27.7 |

**vs baseline 1.15.1** (solved-only, both-solved shared instances):
- 1.15.1.3: ratio **0.19** (29 faster / 2 slower, 31 shared)
- 1.15.1.4: ratio **4.25** (rejected — parallel-redesign slower)
- 1.15.1.5: ratio **0.32** (28/7, 35 shared)
- 1.15.1.6: ratio **1.65** (52/60, 112 shared) — idiomatic GMI slower than raw

**vs Gurobi 12.0.3** (solved-only):
- 1.15.1.3: **0.49** (55/24, 79 shared)
- 1.15.1.5: **0.52** (49/28, 77 shared)
- 1.15.1.6: **0.79** (38/30, 68 shared)
- 1.15.1 / 1.15.1.4: 4.0 / 3.6 — far behind Gurobi

Verdict: raw-GMI versions (.3/.5) beat Gurobi ~2x on the solved subset and
roughly halve shifted-geomean vs baseline. The idiomatic `.6` GMI is correct
but slower. `.4` (parallel-redesign) is rejected.

### 1.15.1.7 (aborted) — `parallel=auto` worker-count scaling

Negative result, not committed (code reverted). Added `parallel="auto"` default
and two worker-count variants in `getMaxNumWorkers()`, then ran the full
240-set (60s, 12 threads) vs 1.15.1.6:

- shifted-geomean(10) **5.283s → 8.921s, ratio 1.69** — regression
- 98 shared, **96 slower / 2 faster**

Key lesson for any future parallel work: **worker count must NOT be gated on
matrix size.** `getMaxNumWorkers()` is a fixed ceiling (`ceil(1.7*threads)`=21);
the *actual* spawn is demand-driven by live open-node count
(`HighsMipSolver.cpp:1000-1016`), not matrix nonzeros. MIPLIB instances are
tree-search-bound — a 2016-nz `neos5` still needs all 21 workers (solves ~12s
with `on`, times out with ~3). The 1.7× over-subscription is load-balancing
headroom across node-queue stalls, not wasted contention. Do not reduce it.

Corollary for the parallel-redesign re-port: its value is **fewer/batched
syncs** (staleness trade), not worker count — batch size is an unmeasured
U-curve (`sync=c1/batch`, `staleness=c2*batch`); sweep {1,10,50,100,500} on the
large subset. Nodes are evaluation-gated (not generated blindly). Judge the
redesign on the **large-instance subset** (≥120k nz), where sync cost
dominates; a blended all-instance geomean hides its signal.

### 1.15.1.8 (aborted) — parallel-redesign re-port (GMI + node presolve intact)

Re-ported `parallel-redesign` onto master (1.15.1.6) keeping `generateGomoryCut`
+ node presolve; merged only the 12 `highs/mip/` files. Full 240-set (60s,
12 threads) vs 1.15.1.6:

- shifted-geomean(10, timeouts folded) **27.965s → 35.003s, ratio 1.25**
- 240 shared, **23 faster / 217 slower**
- **time-limit enforcement broken**: instances ran 30-44× over the 60s cap
  (s100 199→2637s, nw04 60→1907s, co-100 62→384s); co-100 crashes in probing.

Follow-up: reduced `maxNodesPerWorkerLim` 100→10→5 and added per-batch/per-node
global time checks (`mipdata->checkLimits()` / `timer_.read()`). co-100
384s→150s→140s vs baseline 62s; s100 still >120s wall for 60s limit. **Still
2.3× slower than baseline, no speedup on broken instances** (tested s100, nw04,
ns1760995, nursesched-medium, co-100). Second fix attempted, still rejected.

**Verdict**: the batching's sync savings are outweighed by staleness + broken
time-limit checks on this 12-thread/60s workload. The earlier optimistic
"judge on large subset" hypothesis was WRONG — even node-heavy instances
regressed. Rejected. See branch `failed/parallel-redesign/1.15.1.8` (commits
`fa1a771067`, `568611fc05`).

**Note on comparison method**: `compare_versions.py` now defaults to
`solved-only` — timeouts are excluded from the shared set and geomean (their
true solve time is unknown; 60s is a lower bound, not an estimate). Use
`--include-timeouts` to fold timeouts in at the cap (old behavior). This
changes which instances are compared, so ratios here are solved-only.

### Version matrix (reconstructed clean history)

| Version | GMI | Node presolve | Commit |
|---------|-----|---------------|--------|
| 1.15.1.3 | raw `generateGmiCut` | OFF | Tier-1 + raw GMI |
| 1.15.1.5 | raw `generateGmiCut` | ON (threshold 200000) | + node LP presolve |
| 1.15.1.6 | idiomatic `generateGomoryCut` | ON | swap GMI to pipeline |

### Benchmark results (super-fast, 135 instances, 15s limit)

**Node presolve effect** (1.15.1.3 → 1.15.1.5, same raw GMI):
- All 135: shifted-geomean(10) 2.463s → 2.370s (**ratio 0.962**, 70 faster).
- On the 17 large instances (≥200k nz) node presolve targets: 7.742s → 7.193s
  (**ratio 0.929**), summed 136.9s → 126.9s (**−10.0s, −7.3%**). 10 faster /
  6 slower / 1 equal. Node presolve is a net positive on the big subset it
  targets.

**GMI approach effect** (1.15.1.5 → 1.15.1.6, node presolve on):
- shifted-geomean(10) 2.370s → 6.853s (**ratio 2.891**). Idiomatic
  `generateGomoryCut` is ~2.9x **slower** than raw `generateGmiCut` (15 faster /
  120 slower). Transform + postprocess + violation/duplicate-gating overhead
  dominates on short rows.

**Verdict**: raw `generateGmiCut` (1.15.1.5) is the performance winner. Node
presolve helps specifically on large instances. Idiomatic GMI is correctness-
grade but materially slower.

### What's Implemented

| Item | Version | Change | Impact |
|------|---------|--------|--------|
| 1. CHUZC heap sort | 1.15.1.1 | Enable heap path for `workCount >= 100` | Eliminates O(n^2) sort |
| 2. freeList | 1.15.1.1 | Packed vector + mark array + position map | Cache-friendly, O(1) membership |
| 3. propagate buffer | 1.15.1.1 | Cache reusable `HighsDomainChange` buffer | No per-call heap alloc |
| 4. `-march=native` | 1.15.1.1 | Opt-in via `-DMARCH_NATIVE=ON` | Free 10-30% CPU-bound |
| 5. HighsCombinable bug | 1.15.1.1 | Fix thread copy drop in `combine` | Removes silent bug |
| 6. Dead code cleanup | 1.15.1.1 | Remove `exit(0)` in clique overload | Eliminates crash |
| 8. Heuristic effort | 1.15.1.2 | Raise from 0.05 to 0.1 | 35/38 instances improved, 27% median |
| 9. GMI cuts | 1.15.1.6 | Idiomatic `HighsCutGeneration::generateGomoryCut` in tableau separator (replaces standalone fast path) | Correct GMI via standard cut pipeline; ~2-3x slower than standalone (deliberate); see idioms section |
| 19. parallel default | 1.15.1.1 | "choose" → "on" | MIP uses 12 threads |

### What's NOT Implemented (do these next)

| Item | Priority | Effort | Location |
|------|----------|--------|----------|
| 7. Node presolve | High | High | `HighsMipSolverData.cpp:2034-2054` |
| 10. Dual-implied-bound | Medium | Medium | Partially in flight (`probe-dual-fix`) |
| 12. Parallel strong branching | Medium | Medium | `HighsSearch.cpp:533-692` |
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

### Quick reference for new agents

1. Read this file for full context
2. Read `docs/optimization-changelog.md` for version history and learnings
3. Check "What's NOT Implemented" above for next tasks
4. Follow workflow in `.opencode/skills/highs-optimize/SKILL.md`
5. Every change must pass benchmark (no regressions)
