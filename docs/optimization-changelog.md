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

## Rejected experiments

### 1.15.1.4 — Parallel MIP redesign (`parallel-redesign` branch port)

Ported upstream `parallel-redesign` MIP core onto 1.15.1.3 (12 files under
`highs/mip/`; worker count = num_threads, per-worker processedNodes stash,
all-workers heuristics, deterministic early termination). Built clean, ctest
160/168 (8 PDLP failures unrelated). **Rejected**: benchmarked twice, slower
than 1.15.1.3 on the MIPLIB2017 fast subset both times. Work preserved on
branch `parallel-redesign2` (commit `51c8819cc9`). Master stays on 1.15.1.3.

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

**Benchmark focus**: node presolve only triggers on instances whose LP
relaxation exceeds the nonzero threshold. On the super-fast subset, ~17/128
instances qualify. Compare 1.15.1.3 (no node presolve) vs 1.15.1.5 (node
presolve) to isolate the effect on those instances.

### 1.15.1.6 — Idiomatic Gomory cut `generateGomoryCut` + node presolve

Swaps the raw `generateGmiCut` fast path for the idiomatic cut-pipeline version.
Node LP presolve unchanged from 1.15.1.5.

| Change | File | Impact |
|--------|------|--------|
| Add `HighsCutGeneration::generateGomoryCut`: transform row, complement via `preprocessBaseInequality`, generate pure Gomory cut as `cmirCutGenerationHeuristic(minEfficacy, true)` (MIR at delta=1, skipping cover/lifting/delta-search), untransform, `finalizeAndAddCut` for efficacy/violation/duplicate gating | `highs/mip/HighsCutGeneration.{h,cpp}` | Idiomatic single-row Gomory cut |
| Replace standalone `generateGmiCut` with `generateGomoryCut` (same structure: 2x `generateCut` + 2x Gomory) | `highs/mip/HighsTableauSeparator.cpp` | GMI flows through the standard cut pipeline |

**Note**: idiomatic path trades raw speed (~2-3x slower per-cut on short rows)
for correctness — complementation, efficacy gating, duplicate detection. See
`docs/optimization-findings.md` for the A/B measurement.

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
- **parallel-redesign**: upstream's per-worker nodequeue → processedNodes batch stash, `maxNodesPerWorkerLim=100` ramp-up, and 1:1 thread mapping were **measured slower** than the vanilla 1.15.1.3 parallel path (2 benchmark runs). Benchmark any parallel-MIP change on a quiet machine with a real 1.15.1.3 baseline before adopting — do not cherry-pick upstream parallel redesign blindly.
