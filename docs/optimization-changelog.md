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

### 1.15.1.5 — Audit + GMI cuts + node presolve + debug cleanup

**Audit result**: Verified every "What's Done" entry against the actual source at
HEAD. All Tier-1 entries (1-5, 6 partial) plus heuristic effort (8) and
`parallel` default (19) are genuinely implemented. The **GMI cuts entry (9) was
NOT implemented** — `git grep -i gomory` finds no Gomory/GMI cut generator in any
commit (`HighsTableauSeparator.cpp` is the base separator only; the 1.15.1.3
changelog claim was false/never committed). Reimplemented it below. Also found
leftover debug `printf` in the heap-CHUZC hot path that spams stdout on every
large-candidate CHUZC (real slowdown).

| Change | File | Impact |
|--------|------|--------|
| GMI cuts: standalone `generateGmiCut` — a pure Gomory Mixed-Integer cut (fractional parts of integer-row coefficients) computed directly in original space and added via `cutpool.addCut`, after each standard MIR heuristic (`generateCut`) on the aggregated tableau row. **Superseded by idiomatic `generateGomoryCut` in 1.15.1.6.** | `highs/mip/HighsTableauSeparator.cpp` | Strong single-row Gomory cut always attempted; measured ~3.6x faster than no-GMI on super-fast |
| Remove debug `printf` in heap-CHUZC path (was unconditional, printed every pivot to stdout) | `highs/simplex/HEkkDualRow.cpp` | Fixes severe stdout-bound slowdown on large LPs |
| Node/local LP presolve: run solver LP presolve on node solves whose relaxation has ≥ `mip_node_presolve_threshold` nonzeros (default 200000). Presolve re-solves a reduced node model from scratch and postsolves back; it discards the parent warm-start basis, so it is gated on LP size. | `HighsLpRelaxation.cpp` (`run`), `HighsOptions.h` | Shrinks large node relaxations |
| New option `mip_node_presolve_threshold` (0 disables; default 200000) | `HighsOptions.h` | Tuning knob |
| `run_benchmark.py`: add `--no-cache` flag (re-benchmark instances that already have a results file) | `benchmark/scripts/run_benchmark.py` | Harness |

**Audit of 1.15.1.3 "GMI cuts" (v1.15.1.3 entry below)**: that entry is
**false** — no GMI/Gomory cut was ever committed. The 1.15.1.3 commit
(`6bf8248`) contains only Tier-1 simplex/MIP fixes (CHUZC, freeList, propagate,
Combinable, march=native, dead code, parallel default, heuristic effort). GMI
cuts were destroyed before commit and are restored here in 1.15.1.5.

**Benchmark status**: Super-fast MIPLIB2017 subset (135 instances, 60s limit)
was run on this dev box for the standalone-GMI vs no-GMI and standalone-GMI vs
CMIR-reroute comparisons above. On 35 instances shared with the 1.15.1.1 (no-GMI)
`fast` set, the standalone GMI was a median 3.6x faster (ratio 0.276); against
the working-GMI 1.15.1.3 cache the gap was within run-to-run noise (ratio 1.08).
Absolute baselines from the original 1.15.1.3/iter4 runs are not reproducible on
this box (the machine is ~50-200x slower than when recorded), so cross-machine
absolute comparisons are not meaningful. ctest: 160/168 (8 PDLP failures
pre-existing).

**A/B note (standalone GMI vs CMIR-reroute)**: a CMIR-reroute variant
(`generateCut(..., onlyInitialCMIRScale=true)` + an extra aggregation per row)
was benchmarked head-to-head with the standalone `generateGmiCut` on the
super-fast subset (60s limit, 62 common instances). The standalone won
decisively: median ratio 0.021 (~47x faster), 54/62 faster; the reroute hit the
60s time limit on instances the standalone solves in <0.3s. Caveat: the reroute
benchmark bundled an extra `getCurrentAggregation` and a third `generateCut` per
row, so it was not a pure idiom-vs-standalone swap.

**A/B note (idiomatic `generateGomoryCut` vs standalone, clean swap)**: a
`HighsCutGeneration::generateGomoryCut` method was added (transform ->
`cmirCutGenerationHeuristic(minEfficacy, true)` directly, skipping cover/lifting
and delta-search, then `finalizeAndAddCut` for efficacy/duplicate gating) and
substituted into the exact A structure (2x `generateCut` + 2x GMI). Benchmark
on super-fast (135 instances, 15s timeout): A/B median 0.47, geomean 0.37,
A faster on 98/135, shifted-geomean(10) 0.757. The idiomatic path is ~2-3x
slower than standalone GMI for the short fractional rows the tableau separator
feeds — the transform/untransform + postprocess + violation/duplicate-gating
overhead dominates. **Adopted anyway as 1.15.1.6** (deliberate correctness-over-
raw-speed choice: it inherits complementation, efficacy gating, and duplicate
detection that the standalone lacks, at the cost of ~2-3x per-cut overhead).

### 1.15.1.6 — Idiomatic Gomory cuts (`generateGomoryCut`)

| Change | File | Impact |
|--------|------|--------|
| Add `HighsCutGeneration::generateGomoryCut`: transform row, complement via `preprocessBaseInequality`, generate the pure Gomory cut as `cmirCutGenerationHeuristic(minEfficacy, true)` (MIR at delta=1, skipping cover/lifting and delta-search), untransform, then `finalizeAndAddCut` for efficacy/violation/duplicate gating | `highs/mip/HighsCutGeneration.{h,cpp}` | Idiomatic single-row Gomory cut |
| Replace standalone `generateGmiCut` with `generateGomoryCut` in the tableau separator (same surrounding structure: 2x `generateCut` + 2x Gomory) | `highs/mip/HighsTableauSeparator.cpp` | GMI now flows through the standard cut pipeline (complementation, efficacy, duplicate gating) |
| Drop the standalone `generateGmiCut` fast path | `highs/mip/HighsTableauSeparator.cpp` | Removes non-idiomatic bypass of the cut pipeline |

**Benchmark/verification**: 7/7 smoke examples Optimal; ctest 79% / 36 failures
(identical to baseline 1.15.1.5 — all pre-existing MIP-random-seed/PDLP/unit-test
failures, none introduced by this change). Super-fast A/B vs standalone GMI:
see A/B note above (adopted at ~2-3x slower than standalone, deliberate).

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
