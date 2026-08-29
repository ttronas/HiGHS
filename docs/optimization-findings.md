# HiGHS Optimization Findings

Structured optimization memory, organized like a taxonomy: each row is one
optimization strategy with its target component, the signal that tells us
whether it engaged, and its priority tier. Read this before changing solver
code. Companion docs:

- `docs/optimization-changelog.md` — per-version history + learnings
- `docs/optimization-roadmap.md` — planned features and priorities

## Priority Tiers

| Tier | Meaning |
|------|---------|
| 1 | Low risk, localized change, expected small-but-safe gain |
| 2 | Medium complexity or risk, needs careful correctness analysis |
| 3 | Large redesign; only with explicit user approval |

## Optimization Taxonomy

### 1 — Enable zi_round + shifting + heuristic_effort sweep
- Component: highs/mip/HighsPrimalHeuristics.cpp | highs/lp_data/HighsOptions.h:1224 | app/HighsRuntimeOptions.h:157 | highs/io/HighsIO.cpp:27
- Idea: Flip `mip_heuristic_run_zi_round`/`mip_heuristic_run_shifting` from false to true and sweep `mip_heuristic_effort` 0.05→0.08. Rounding heuristics close primal gap early; cheap vs sub-MIP. Also fix version plumbing (`HIGHS_TWEAK` 4-part).
- Expected signal: `heuristic_lp_iterations` up, `MipDivePrimalHeuristics`/`DiveRins/Rens` clocks move, incumbent found earlier (`numImprovingSols` up), `pruned_treeweight` faster
- Validation: `compare_versions.py` vs `gurobi:12.0.3` GT — zero mismatches; `ctest` pass; version `1.15.1.1` reports correctly
- Tier: 1
- Status: merged (1.15.1.1) — super-fast geomean 0.873 (17/18 faster, -17.78%, saved 8.4s), fast geomean 0.995 (17/26 faster, median -15.28%), correctness PASS. One regression neos859080 +56% (infeasible) justified.

### 2 — Tune cutpool age/soft limits
- Component: highs/lp_data/HighsOptions.h:1175-1193 | highs/mip/HighsCutPool.cpp | highs/mip/HighsLpRelaxation.cpp
- Idea: Grid `mip_pool_age_limit` 30, `mip_pool_soft_limit` 10000, `mip_lp_age_limit` 10. Retaining cuts helps bound but bloats LP.
- Expected signal: `Perform aging` time down with higher limits, `separation rounds` stable, `DuSimplexBasisSolveLp` iter/node tradeoff
- Validation: geomean on `super-fast`/`fast` at 60s; check `mip_pool_soft_limit` invariant `cutpools.size() ≤ soft_limit * factor`
- Tier: 1
- Status: rejected (1.15.1.2) — 30→35/10000→12000/10→12 gave geomean 1.36x slower (16/18), saved -22.9s. Defaults well-tuned.

### 3 — Fix CMIR min violation 0.001*feastol
- Component: highs/mip/HighsCutGeneration.cpp:603,637,682 | highs/mip/HighsTransformedLp.h
- Idea: Implement TODO: drop cuts with violation < 0.001*feastol + tighten efficacy/density filters. Filters weak cuts without correctness risk.
- Expected signal: `separation rounds up` or flat, `cutset.numCuts` filtered, `total_lp_iterations` down (less bloat)
- Validation: unit: cut violation ≥ threshold; `compare_versions.py` PASS
- Tier: 1
- Status: rejected (1.15.1.3) — `1e-3*feastol` filter gave 1.104x slower (14/18, +13.13%), efficacy filter `minEfficacy` already sufficient.

### 4 — Per-separator MIP profiling
- Component: highs/mip/HighsSeparation.cpp | highs/mip/HighsSeparator.cpp | highs/mip/MipTimer.h:164,316 | HighsImplications | HighsCliqueTable
- Idea: Uncomment `kImplboundSepa`/`kCliqueSepa`/`kTableauSepa`/`kPathAggrSepa`/`kModKSepa` clocks (hardcoded 990/991→proper `kMipClock*`) and guard with `profiling->mip_` so overhead 0 when not analyzing. Instrument only.
- Expected signal: `MipSeparation` clocks report per instance in `reportMipSeparationClock` when `highs_analysis_level` has `kHighsAnalysisLevelMipTime`
- Validation: `HighsMipSolver::run()` completes; `MipTimer` clocks non-zero when enabled; `compare_versions.py` PASS
- Tier: 1
- Status: merged (1.15.1.4) — wired 5 clocks, super-fast 1.10x (13/18 slower) overhead when profiling enabled, 0% when off (conditional). Needed for Tier2 cut efficacy.

### 5 — Batch flushDomain bound changes
- Component: highs/mip/HighsLpRelaxation.cpp:711 | highs/mip/HighsMipSolver.cpp
- Idea: Batch column-bound changes per `flushDomain` / `resolveLp` call to reduce simplex warm-start overhead. Already single `changeColsBounds` per flush.
- Expected signal: `Solve LP - du simplex basis` time down per node, `num_nodes` flat
- Validation: LP `Status kOptimal` count unchanged; `ctest -R HighsLpRelaxation`
- Tier: 1
- Status: merged (1.15.1.5) — investigated, already batched, 0.993 geomean (9/9) neutral, PASS. Added comment.

### 6 — Probing lifting / symmetry / root-presolve-only toggles
- Component: highs/presolve/HPresolve.cpp | highs/lp_data/HighsOptions.h:1159
- Idea: Sweep `mip_lifting_for_probing -1→0/1/2`, `mip_detect_symmetry false→true` (binary models), `mip_root_presolve_only false→true`. Cheap presolve diversity.
- Expected signal: `Probing - presolve` / `Enumeration - presolve` time up but `num integer cols` down, `num nodes` down on binaries
- Validation: `mip_detect_symmetry` only stabilizes orbitopes; check `symmetries.numGenerators` log
- Tier: 1
- Status: rejected (1.15.1.6) — `-1→1` gave 4 FAIL mismatches (infeasible vs optimal, wrong obj 243657 vs 65887) — cut off optimal. Keep -1.

### 7 — Tune pscost_minreliable + cliquetable parallelism threshold
- Component: highs/mip/HighsPseudocost.cpp | highs/lp_data/HighsOptions.h:1196
- Idea: Sweep `mip_pscost_minreliable 8→4/12` (reliability branching) and `mip_min_cliquetable_entries_for_parallelism 100000→50000/200000`. Trades strong-branch cost vs branching quality.
- Expected signal: `sb_lp_iterations` vs `total_lp_iterations` ratio moves; `getNumNeighbourhoodQueries` parallel path hit rate
- Validation: pseudocost update determinism; `HighsPseudocost` unit
- Tier: 1
- Status: rejected (1.15.1.7) — `8→4` gave 1.036x slower (10/18), neutral. Keep 8.

### 8 — Adaptive RENS/RINS fixing-rate
- Component: highs/mip/HighsPrimalHeuristics.cpp:249-273,627 | highs/mip/HighsMipSolverData.cpp:669
- Idea: Replace naive `low/highFixingRate 0.6` with observation-driven adaptation (`infeasObservations`/`successObservations`) already partially present but under-tuned; sweep sub-MIP leaf/node budgets `500 / 200+nodes/20 / stall 12`.
- Expected signal: `Sub-MIP solves` time vs `numImprovingSols` tradeoff, fixing-rate log moves toward observed success
- Validation: `solveSubMip` returns deterministic vs seed; check `worker.terminatorTerminated()` path
- Tier: 1
- Status: proposed

### 9 — GMI/Gomory separator
- Component: highs/mip/HighsTableauSeparator.* | highs/mip/HighsCutGeneration.*
- Idea: Implement Gomory mixed-integer cuts from tableau rows (add to `HighsSeparation::separators` at `HighsSeparation.cpp:38-41`). Gurobi "more aggressive Gomory" closes gap at root.
- Expected signal: root LP objective `firstobj→lastobj` gap closed up, `separation rounds up`, `sepa_lp_iterations` up modestly
- Validation: cut validity: `cutpool.separate` checks `feastol`; LP `addCuts` not cut off optimal integer
- Tier: 2
- Status: proposed

### 10 — Zero-half cuts
- Component: new highs/mip/HighsZeroHalfSeparator.* | highs/mip/HighsSeparation.*
- Idea: Mod-2 parity cuts via Gaussian elimination on binary rows. Covers Gurobi `ZeroHalfCuts` family.
- Expected signal: `ZeroHalf` pool entries, `num nodes` down on binary instance subset
- Validation: parity correctness: cut coeffs 0/0.5→int; check `HighsDomain::isFixed` not broken
- Tier: 2
- Status: proposed

### 11 — Flow-cover / GUB-cover cuts
- Component: new highs/mip/HighsFlowCoverSeparator.* | highs/mip/HighsPathSeparator.cpp
- Idea: Systematic flow-cover generation beyond single `PathSeparator` aggregation. Targets fixed-charge network structure.
- Expected signal: `PathAggrSepa` / new `FlowCover` clock time, knapsack violation detection up
- Validation: flow-cover lifting invariants
- Tier: 2
- Status: proposed

### 12 — Stronger c-MIR / master-knapsack + aggressive aggregation
- Component: highs/mip/HighsLpAggregator.* | highs/mip/HighsTransformedLp.*
- Idea: Replace single-row `cmirCutGenerationHeuristic` with multi-row aggregation (as Gurobi13 master-knapsack). Re-use `HighsTransformedLp` bound substitution via `implications.bestVub/Vlb`.
- Expected signal: stronger cut coefficients (lower density), stronger root bound `lp->getObjective()` vs `rootlpsolobj`
- Validation: aggregation `HighsLpAggregator` numerical stability; check coefficient magnitude `< kHighsInf`
- Tier: 2
- Status: proposed

### 13 — Infeasible-solution pool for RINS
- Component: highs/mip/HighsMipSolverData.cpp | highs/mip/HighsPrimalHeuristics::RINS | highs/mip/HighsPrimalHeuristics.h
- Idea: Keep rounded root-LP / dual-presolve-cutoff / rejected heuristic sols as infeasible seeds for RINS (Gurobi13 11% first-feasible). Currently only incumbent + relaxation used.
- Expected signal: `RINS` attempts up, first incumbent time down, `numImprovingSols` earlier
- Validation: pool solutions remain infeasible-allowed; verify `solutionRowFeasible` filter not leaking into incumbent
- Tier: 2
- Status: proposed

### 14 — Multi-reference RENS (mRENS)
- Component: highs/mip/HighsPrimalHeuristics::RENS:394
- Idea: RENS from multiple reference sols (root LP + incumbent + analytic centre) rather than single. SCIP mRENS 41% gap reduction.
- Expected signal: RENS sub-MIP solves up, but solutions per `solveSubMip` more diverse
- Validation: distinct `colLower/colUpper` per reference; sub-MIP not duplicate
- Tier: 2
- Status: proposed

### 15 — Degenerate moves + reliability branching
- Component: highs/mip/HighsSearch.cpp:selectBranchingCandidate | highs/mip/HighsPseudocost.* | highs/mip/HighsLpRelaxation::computeBasicDegenerateDuals
- Idea: Explore optimal face (`degenerate moves` / `computeBasicDegenerateDuals`) for fewer integer infeasibilities before heuristics; use Driebeek penalties more often. Mirrors Gurobi12 0.9% branching gain.
- Expected signal: `Dive` / `Evaluate node` heuristic success up, `pseudocost` degeneracyFactor scaling
- Validation: degenerate duals keep LP optimal basis; check `worker.getPseudocost()` sync
- Tier: 2
- Status: proposed

### 16 — OBBT + LU aggregator presolve
- Component: highs/presolve/HPresolve.cpp
- Idea: Add optimization-based bound tightening for on-off constraints + LU-based aggressive equality aggregation (Gurobi13). Requires presolve loop integration.
- Expected signal: `Run presolve` time up but model rows/cols reduction % up, `num nodes` down
- Validation: `HighsPostsolveStack` round-trip; `checkSolution` with analytic centre
- Tier: 2
- Status: proposed

### 17 — Fix FeasibilityJump 64-bit
- Component: highs/mip/HighsFeasibilityJump.cpp:19 | highs/mip/feasibilityjump.hh:745
- Idea: Port 32-bit-only FJ (`TODO 32-bit`) to 64-bit, add move types TODO 745. FJ already top heuristic at root `mip_heuristic_run_feasibility_jump true`.
- Expected signal: `Feasibility jump` clock active on x86-64, FJ incumbents up
- Validation: 64-bit integer overflow watch; `ctest -R feasibility`
- Tier: 2
- Status: proposed

### 18 — HiPO concurrent at root
- Component: highs/mip/HighsMipSolverData::startAnalyticCenterComputation:409 | highs/mip/HighsLpRelaxation.* | highs/lp_data/HighsOptions.h
- Idea: Race simplex vs HiPO/IPX at root (as analytic centre already races via `TaskGroup`). Pick first to finish; keep basis path warm for tree.
- Expected signal: `Solve LP: HiPO/IPX` clocks vs `DuSimplexBasisSolveLp`; root time down on dense models
- Validation: fallback to simplex on HiPO fail as in `HighsMipSolverData.cpp:474`; objective tolerance vs GT
- Tier: 2
- Status: proposed

### 19 — Parallel tree search (Tier 3, needs approval)
- Component: highs/mip/HighsMipSolver.cpp:272-350 | highs/mip/HighsMipWorker.* | highs/parallel/HighsParallel.h
- Idea: Work stealing, async cut/conflict sync, deterministic `parallelLockActive` sync. Biggest hardware-dependent gain.
- Expected signal: multi-core speedup 2-4x on >100s subset at 12 threads (Gurobi parallelism pdf)
- Validation: deterministic-vs-opportunistic mode via `mip_search_simulate_concurrency`; stress with `threads=12`
- Tier: 3
- Status: proposed

Row format (keep for new entries):

```
### <idea name>
- Component: highs/mip/... | highs/simplex/... | highs/lp_data/...
- Idea: <what to change and why it should help>
- Expected signal: <which timer/counter in HiGHS log should move>
    (e.g. "openMIPNodeLP time down", "separation rounds up")
- Validation: <how to check correctness beyond GT compare>
    (unit test, ctest target, invariant)
- Tier: 1|2|3
- Status: proposed | testing | merged (<version>) | rejected (<reason>)
```

Rules of engagement (Hawkeye-style):

1. Correctness is a precondition for performance signal. An instance whose
   objective/status disagrees with ground truth yields INVALID timing data:
   it is excluded from aggregates and fails the run.
2. A strategy counts only if BOTH the expected signal moved AND end-to-end
   geomean improved (or stayed flat within noise) on the benchmark set.
3. Iterate on `super-fast`/`fast` sets; `full` is a confirmation gate before
   merging — do not tune against full-set results.
4. Never modify harness logic (`benchmark/scripts/`) on a feature branch.
   The agent must not move its own goalposts.

## Idiomatic HiGHS Conventions

_(add code-level conventions discovered while implementing)_
