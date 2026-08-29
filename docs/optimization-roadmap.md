# HiGHS Optimization Roadmap

Planned features, priorities, and status. This is the forward-looking
companion to `docs/optimization-findings.md` (what was learned) and
`docs/optimization-changelog.md` (what shipped).

## How to use

- Pick the top unblocked item, create `feature/<name>/<next-version>` from
  `master`, bump `HIGHS_TWEAK`, follow `.opencode/skills/highs-optimize/SKILL.md`.
- Move items between Planned / In Progress / Done / Rejected as work proceeds.
- One roadmap item = one feature branch = one TWEAK version.

## Scope

- **Benchmark:** MIPLIB2017 benchmark set (240 instances, subsets derived from it)
- **Threads:** 12 (Mittelmann parity) — `filter_sets.py` regenerated at 12 threads
- **Focus:** MIP solver only for now (LP/IPM improvements tracked only if they help MIP `total_lp_iterations`)
- **Order:** Tier 1 first (low-risk localized), then Tier 2 (medium). Tier 3 needs explicit approval.

## Backlog — Tier 1 (low risk, localized)

| # | Idea | Component | Tier | Status | Notes |
|---|------|-----------|------|--------|-------|
| 1 | Enable `zi_round` + `shifting` heuristics + `mip_heuristic_effort 0.05→0.08` | `highs/mip/HighsPrimalHeuristics.cpp` `highs/lp_data/HighsOptions.h:1224` `app/HighsRuntimeOptions.h:157` `highs/io/HighsIO.cpp:27` | 1 | done (1.15.1.1) | Flipped defaults `zi_round/shifting false→true`, `effort 0.05→0.08`. Super-fast geomean 0.873 (17/18 faster, 8.4s saved), fast 0.995 (17/26 faster). Correctness PASS vs gurobi:12.0.3. One regression `neos859080` +56% (infeasible, heuristics overhead) justified. |
| 2 | Tune cutpool `mip_pool_age_limit`/`mip_pool_soft_limit`/`mip_lp_age_limit` | `highs/lp_data/HighsOptions.h:1175-1193` `highs/mip/HighsCutPool.cpp` | 1 | rejected (1.15.1.2) | Tested 30→35, 10000→12000, 10→12: geomean 1.36x slower (16/18), saved -22.9s. Keep defaults. |
| 3 | Fix CMIR min violation `TODO 0.001*feastol` + density/efficacy filters | `highs/mip/HighsCutGeneration.cpp:603,637,682` | 1 | rejected (1.15.1.3) | Filter `viol<1e-3*feastol` 1.104x slower (14/18). Efficacy filter sufficient. |
| 4 | Enable per-separator MIP profiling (uncomment implbound/clique/tableau/path/mod-k clocks) | `highs/mip/HighsSeparation.cpp:28-34` `highs/mip/MipTimer.h:164-174` | 1 | planned | Currently hardcoded 990/991. Required measurement for Tier 2 cuts. |
| 5 | Batch `flushDomain` bound changes in `HighsLpRelaxation::resolveLp` | `highs/mip/HighsLpRelaxation.cpp` | 1 | planned | Reduces `DuSimplexBasisSolveLp` iterations per node. |
| 6 | Experiment `mip_lifting_for_probing`, `mip_detect_symmetry`, `mip_root_presolve_only` | `highs/presolve/HPresolve.cpp` `highs/presolve/HighsSymmetry.h` `highs/lp_data/HighsOptions.h:1098-1161` | 1 | planned | Currently `-1`/`false`/`false`. Probing+suffix lifting & symmetry help binaries. |
| 7 | Tune `mip_pscost_minreliable` 8→4/12 + `mip_min_cliquetable_entries_for_parallelism` | `highs/mip/HighsPseudocost.cpp` `highs/mip/HighsCliqueTable.cpp` `highs/lp_data/HighsOptions.h:1196-1209` | 1 | planned | Reliability branching threshold vs strong-branching cost. |
| 8 | Adaptive RENS/RINS fixing-rate (`determineTargetFixingRate 0.6`) + sub-MIP leaf/node budgets | `highs/mip/HighsPrimalHeuristics.cpp:249-273,627` | 1 | planned | Naive 0.6 base; Gurobi RINS adapts via infeas/success observations. |

## Backlog — Tier 2 (medium complexity, correctness-sensitive)

| # | Idea | Component | Tier | Status | Notes |
|---|------|-----------|------|--------|-------|
| 9 | GMI/Gomory separator from tableau rows | `highs/mip/HighsTableauSeparator.*` `highs/mip/HighsCutGeneration.*` | 2 | planned | Gurobi "more aggressive Gomory"; HiGHS tableau cover only. |
| 10 | Zero-half cuts (mod-2 Gaussian elimination) | new `highs/mip/HighsZeroHalfSeparator.*` | 2 | planned | Chvatal-Gomory rank-1 parity; Gurobi `ZeroHalfCuts`. |
| 11 | Flow-cover / GUB-cover cuts (full family, not just Path) | new `highs/mip/HighsFlowCoverSeparator.*` `highs/mip/HighsPathSeparator.cpp` | 2 | planned | Gurobi log shows 1534 Flow-cover on hard models. |
| 12 | Stronger c-MIR / master-knapsack + aggressive `HighsLpAggregator` | `highs/mip/HighsLpAggregator.*` `highs/mip/HighsTransformedLp.*` | 2 | planned | Gurobi13 master-knapsack 10% on >100s models. |
| 13 | Infeasible-solution pool reuse for RINS (rounded root LP, dual-presolve cutoff) | `highs/mip/HighsMipSolverData.cpp` `highs/mip/HighsPrimalHeuristics::RINS` | 2 | planned | Gurobi13 5% to optimality, 11% to first feasible. |
| 14 | Multi-reference RENS / mRENS (several LP sols) | `highs/mip/HighsPrimalHeuristics::RENS:394` | 2 | planned | SCIP mRENS 41% gap reduction. |
| 15 | Degenerate moves + enhanced reliability branching | `highs/mip/HighsSearch.cpp:selectBranchingCandidate` `highs/mip/HighsPseudocost.*` | 2 | planned | Gurobi12 Driebeek 0.9% branching gain. |
| 16 | OBBT for on-off + LU-based aggressive aggregator presolve | `highs/presolve/HPresolve.cpp` | 2 | planned | Gurobi13 presolve (LU aggregator + implied-free var). |
| 17 | Fix `HighsFeasibilityJump` 64-bit port | `highs/mip/HighsFeasibilityJump.cpp:19` `highs/mip/feasibilityjump.hh:745` | 2 | planned | Currently `TODO 32-bit only`; FJ is top heuristic. |
| 18 | HiPO concurrent at root (race simplex vs HiPO/IPX) | `highs/mip/HighsMipSolverData::startAnalyticCenterComputation:409` `highs/mip/HighsLpRelaxation.*` | 2 | planned | LP 20x gap vs Gurobi per Mittelmann; HiPO helps. |

## Backlog — Tier 3 (large redesign, needs approval)

| # | Idea | Component | Tier | Status | Notes |
|---|------|-----------|------|--------|-------|
| 19 | Parallel tree search (work stealing, async cut/conflict sync) | `highs/mip/HighsMipSolver.cpp:272-350` `highs/mip/HighsMipWorker.*` | 3 | planned | 2-4x on >100s models; Turner WIP; non-determinism risk. |
| 20 | Concurrent root LP + root-parallel cuts/heuristics | `highs/mip/HighsSeparation.cpp:181` `highs/mip/MipTimer.h` | 3 | planned | Gurobi root parallelism (perturbed helps). |
| 21 | Disconnected components with per-component presolve | `highs/mip/HighsMipSolverData.cpp` | 3 | planned | Gurobi13 reduced memory + solves with partial/no solution. |

## References

- Gurobi 13 What’s New; Gurobi 12 What’s New; Achterberg et al. Presolve JOC 2019; Berthold c-MIR cuts.
- HiGHS discussions #2776 (aggregation + parallelism + data structures), #1683 (commercial tricks), Hall JuMP-Dev 2025, ceris.fyi 2025 6.6x gap.
- `highs/mip/` taxonomy probed 2026-08-28 across ~20 files; TODOs enumerated above.

## Workflow per item

```
planned  -> in-progress (branch created, TWEAK bumped)
         -> benchmarked (smoke + super-fast + fast done)
         -> done (full-set confirm passed, merged to master)
         -> rejected (documented in findings.md, branch renamed failed/...)
```

## Promotion gates

A version may only be merged to master when ALL pass:

1. Build clean, `ctest` green.
2. Smoke set: all instances solved, correctness PASS vs ground truth.
3. `super-fast`: no instance regresses >10% without documented justification;
   shifted geomean ratio <= 1.00 vs baseline.
4. `fast`: geomean improvement confirmed on larger subset.
5. `full`: confirmation run at 60 s cap; solved-count does not decrease;
   correctness PASS on every newly-solved and previously-solved instance.
