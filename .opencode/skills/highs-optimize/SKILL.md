---
name: highs-optimize
description: >
  Optimization workflow for HiGHS solver fork. Guides agents through the
  build-benchmark-implement cycle for MIPLIB2017. Full feature tiers, version
  history, and idiomatic conventions live in the referenced docs — read them
  before changing solver code. Use when user says "optimize HiGHS",
  "run optimization", "benchmark HiGHS", "implement proposal", "Tier 1",
  "Tier 2", or invokes /highs-optimize.
---

Optimize HiGHS solver.

## Read these first (required)

- `docs/optimization-findings.md` — full findings, priority tiers, benchmark
  results, and idiomatic HiGHS coding conventions. **READ BEFORE changing code.**
- `docs/optimization-changelog.md` — version history, current status, and
  "Learnings" section (recurring pitfalls). Every optimization commit must add
  an entry here.

The optimization tiers are maintained in those two files, NOT inline in this
skill. Do not restate or duplicate tier tables here.

## Goal

Reduce MIP solution times on the MIPLIB2017 benchmark set. Every change must
show improvement (or no regression) in benchmark results. Primary metric is
shifted geomean runtime across instances. After each cycle, run
`benchmark/scripts/compare_versions.py` for a per-instance report and check for
regressions before proceeding.

## Version convention

Every optimization commit bumps `HIGHS_TWEAK` in `Version.txt` by 1
(format `MAJOR.MINOR.PATCH.TWEAK`); results land in per-version dirs. The
official `HIGHS_PATCH` is NOT changed.

**Before building**: increment `HIGHS_TWEAK`. Changelog version MUST match
`Version.txt` at commit time. Never skip versions. Each optimization commit =
one version bump = one changelog entry. Update the "Current Status" table in
`docs/optimization-changelog.md` after each commit.

## Workflow

```
0. Bump HIGHS_TWEAK in Version.txt (before building — harness reads version at runtime)
1. Build:           ./benchmark/scripts/build_highs.sh
2. Smoke (7 MIPs):  cd benchmark && uv run python scripts/run_benchmark.py --instances-root examples
3. Iteration bench: cd benchmark && uv run python scripts/run_benchmark.py \
                        --instances-file super-fast-instances.txt --time-limit 15
4. Summarize:       cd benchmark && uv run python scripts/summarize.py
5. Compare:         cd benchmark && uv run python scripts/compare_versions.py \
                        --versions <base> <cur> --set iterN
6. Unit tests:      cd build && ctest
7. Update changelog + findings, then commit
```

## Commit policy (success vs failure)

Do NOT stash or delete tested feature files — keep them for future analysis.

- **Not successful / performance decrease**: commit the *feature code* to a
  separate branch `failed/<feature-name>/<version>` (note: git disallows `:`
  in branch names, use `/` instead). Do NOT merge. Add the learning + status to
  `docs/optimization-findings.md` and `docs/optimization-changelog.md` on the
  **master** branch, then commit those doc changes to master.
- **Successful**: bump the version (per Version convention) and commit the new
  version to the **master** branch; also update `docs/optimization-changelog.md`
  and `docs/optimization-findings.md`.
- Never stash or revert tested feature work — it is analysis fodder. Always land
  it on a branch and document it.

Single-instance debug: `--instance <NAME>`. Re-run cached: `--force`. Full
240-run: only on explicit request.

## Comparison method (defaults)

- `compare_versions.py` defaults to `--solved-only`: instances where either
  solver times out are **excluded** from the shared set and geomean. A 60s
  timeout is a lower bound, not an estimate — counting it at 60s would
  underestimate the true gap. Use `--include-timeouts` to fold timeouts in at
  the cap (old behavior).
- Cross-solver compare via `solver:version`, e.g.
  `compare_versions.py --versions gurobi:12.0.3 highs:1.15.1.3 --baseline gurobi:12.0.3`.
- Result set names are canonical: `fast-instances.txt` → `fast`,
  `super-fast-instances.txt` → `super-fast`, `sets/miplib2017-benchmark` →
  `miplib2017`. Passed via `--instances-file` or `--instances-root`;
  `--set` override only for ad-hoc sources.

## Pitfalls (also in changelog Learnings)

- Version bump BEFORE build, or results overwrite.
- `Version.txt`: `HIGHS_TWEAK=1` (equals sign). CMake regex `HIGHS_TWEAK=(.*)`.
- `HConfig.h.in` must carry `#define HIGHS_VERSION_TWEAK @HIGHS_VERSION_TWEAK@`.
- Binary cache: `benchmark/binaries/highs-X`; pass via `--highs-bin`.
- Node presolve is a runtime option (`mip_node_presolve_threshold`, 0 = off);
  toggling does not need a rebuild.
- Fast subset is machine-dependent; recreate via discovery + filter_fast.py.
- Gurobi license at `benchmark/gurobi.lic` (gitignored).

## Reference

- `docs/optimization-findings.md` — findings, tiers, idioms (READ THIS)
- `docs/optimization-changelog.md` — version history + learnings
- `benchmark/README.md` — harness docs
- `benchmark/super-fast-instances.txt` — machine-dependent fast subset
- `benchmark/binaries/` — cached built binaries
- `benchmark/scripts/run_benchmark.py` — benchmark CLI (multi-run, set tracking)
- `benchmark/scripts/summarize.py` — shifted-geomean + performance profiles
- `benchmark/scripts/compare_versions.py` — per-instance version comparison
- `benchmark/scripts/build_highs.sh` — release build (ccache)
- `highs/mip/` — MIP solver source
- `highs/simplex/` — simplex source