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
