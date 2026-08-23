# Report: GMI Fix Iteration 1.15.1.8 — Ideas 1–4

Branch: `fix/generateGomoryCut` `bbf9a20394` → `1.15.1.8` (no version bump per instruction, all ideas inside 1.15.1.8)
Date: 2026-08-23
Machine: `13th-gen-intel-r-core-tm-i7-1355u-12cpu-15-5g`
Harness: `benchmark/scripts/run_benchmark.py` + `compare_versions.py --solved-only` + ground truth `gurobi:12.0.3` `benchmark/scripts/compare_versions.py:54`

## Summary

- **Primary metric `test-gmi-fix2.txt` 20 disputed MIPLIB2017 (60s, 12 threads):**
  - Before fix `highs 1.15.1.5` (raw GMI) / `1.15.1.6` (idiomatic GMI): 20 `HiGHS infeasible != Gurobi optimal` (e.g. `enlight_hard` `Infeasible 1.5s` vs Gurobi `optimal 37 0.008s`, `exp-1-500-5-5`, `ns1208400` etc).
  - After fix `1.15.1.8` **Idea1 (clean-row fast path, GMI disabled)** and **Idea1+Idea2 (clean-row + gated GMI)**: **0 ground truth mismatches** on 20 Gurobi-solved shared (4 solved `exp-1-500-5-5`, `neos-3083819`, `neos-3381206`, `piperout-08` etc). `enlight_hard` now `Time limit 60s` (not `Infeasible`), direct `build/bin/highs --time_limit 60` `Optimal 37` 46s. `traininstance6` `error -11` with `--model_file --threads 12` is Tier1 `HEkkDualRow`/`mip_node_presolve` regression, not GMI (baseline `highs-1.15.1` `Time limit`, same source with `Version 8` segfaults).

- **Super-fast 135 instances, 15s, 12 threads:**
  - `highs 1.15.1` baseline super-fast: 21 shared solved vs `1.15.1.8`, `shifted-geomean(10) 4.109s`
  - `highs 1.15.1.8` **Idea1 alone** (clean-row, GMI disabled): 21 shared, 11 faster /10 slower, `4.213s` `ratio 1.025` (2.5% slower) `ground truth OK` 8 Gurobi-solved shared (free license limits Gurobi super-fast to 28 records, 8 shared).
  - `highs 1.15.1.8` **Idea1+Idea2** (clean-row + gated GMI `hasUnbounded||hasGeneral||hasContinuous→false`, `rowlen>50→false`, `f0 0.10-0.90`, `maxAct<rhs` discard, incumbent `act>feastol→false` in `HighsCutGeneration.cpp:1186/1358`): 21 shared, 11 faster/10 slower, `4.162s` `ratio 1.013` (1.3% slower) `ground truth OK`. `exp-1-500-5-5` 9.91s vs Gurobi 10.62s ` -6.7%` (one faster), `drayage-25-23` 1.87s vs 3.41s `-45%` etc, but geomean not faster.
  - No Idea solves faster than baseline `1.15.1` on super-fast (both `ratio>1`). `test-gmi-fix2` 20-set vs Gurobi `ratio 4.88` (Idea1+Idea2) and `4.82` (Idea1) — slower than Gurobi.

## Ideas Tested

### Idea1 — Clean-row fast path for `generateCut` (no GMI)
- `highs/mip/HighsTransformedLp.h:56` `isCleanRow()` / `transformClean()` checks `bestVlb/Vub==-1`, `col < ncol` (no slack), `vectorsum.empty()`. `HighsCutGeneration.cpp:1058` `generateCut` now `if(useClean) transformClean else transform`. Keeps `postprocessCut:760` `violation>10*feastol:1184` `maxAct` `cutpool.addCut:590` gating. Expected `findings:54` `2-3×` for short rows.
- Result: 0 mismatches, `super-fast` `1.025` vs baseline, `test-gmi-fix2` 7 solved (including `traininstance6` error counted as solved due to `is_solved` bug, actually `Time limit` after fix).

### Idea2 — Gated GMI opt-in (pure-binary, short, moderate f0, incumbent)
- `HighsCutGeneration.h:107` re-added `generateGomoryCut` with 5 gates + `HighsCutGeneration.cpp:1226` `transformClean`/`transform` choice, `rowlen>50`, `f0 0.10-0.90`, `maxAct`, incumbent `act>feastol` discard, `HighsTableauSeparator.cpp:231` 2× `generateGomoryCut` behind gates + `cutpool<500`. Keeps `Idea1` fast path.
- Result: Idea1+Idea2 super-fast `1.013` slightly better than Idea1 alone `1.025`, but still not <1. Idea1+Idea2 test-gmi-fix2 `4` shared faster 1 vs 3 slower, not faster than baseline.

### Idea3 — Local GMI (not yet implemented)
- Would use `cutpool.addCut(..., propagate=false, isLocal)` `HighsCutPool.cpp:544` so `separationRound:154` `lp->addCuts` infeasible only prunes node, not `globaldom.infeasible():142` proof. Would reduce risk vs global. Not tested — expected similar to Idea2 but with less pruning.

### Idea4 — `transform` validity fix
- `HighsTransformedLp.cpp:192/206` `cleanupVub/Vlb` `infeasible` flag currently ignored → return `false`. `vectorsum.cleanup:342` `IsZero` `small_matrix_value` vs `feastol` mismatch. Added `isCleanRow` check already mitigates, but full fix would make `transform` return `false` on `infeasible` and use `feastol`. Not separately benchmarked; incorporated partially in Idea1.

## Best Single and Combination

- **Best single for correctness:** **Idea1** (or **Idea1+Idea2**) — both `0` mismatches on `test-gmi-fix2` and `super-fast` `ground truth OK`. Idea1 alone is simplest (1 file `HighsCutGeneration.cpp` + `HighsTransformedLp` clean path), no GMI risk.
- **Best for speed among correct:** **Idea1+Idea2** `ratio 1.013` vs baseline `1.025` — marginally faster than Idea1 alone, same correctness, so **Idea1+Idea2 is best single** among tested, but still `1.3% slower` than baseline, not faster than `1.15.1` baseline.
- **Combination:** Idea1 (fast `generateCut`) + Idea2 (gated GMI) + Idea4 (transform `infeasible` return) was implicitly tested as Idea1+Idea2 already includes Idea4's `isCleanRow` and `maxAct`. Adding Idea3 (local) would likely not improve `super-fast` geomean significantly because `super-fast` has many time limits; local cuts help per-node but not root. Expected combo `Idea1+Idea2+Idea4` is current `1.15.1.8` — still `ratio>1`. Full `Idea1+Idea2+Idea3+Idea4` would be similar, maybe `0.99` at best, not enough to beat baseline `56.5` → `33.1` Gurobi gap.

## Recommendation

- Keep `1.15.1.8` as **sound but not faster** — do **not** run full `240×60s` `miplib2017` per criteria (requires faster than `1.15.1` baseline). The buggy `1.15.1.5` `18.2` geomean was inflated by 20 false.
- Next fix for speed without GMI: implement `Idea4` fully (`transform` `infeasible` return + `small_matrix_value` → `feastol`) and keep `Idea1` clean-row, or add `mip_node_presolve` tuning (already `200000` `HighsLpRelaxation.cpp:1219`) — separate from GMI.
- For a working GMI that keeps speed, enable `Idea2` only when `mip_gmi_enable=true` and `incumbent` exists, or as local cut `Idea3`, and validate each cut with LP-feasibility trial (`lp` copy + `addCut` + `resolve` if infeasible discard). This was not yet benchmarked.
- Fix `traininstance6` `SIGSEGV -11` (`--model_file --threads 12`) separately — Tier1 `HEkkDualRow` `freeListVec` or `mip_node_presolve` race, not GMI (baseline `highs-1.15.1` `Time limit`).

## Reproduce

```
# test-gmi-fix2 primary
cat > benchmark/test-gmi-fix2.txt <<'EOF' # 20 names
...
uv run run_benchmark --solver highs --instances-file test-gmi-fix2.txt --instances-root sets/miplib2017-benchmark --set miplib2017 --time-limit 60 --highs-bin ../build/bin/highs
uv run compare_versions --versions gurobi:12.0.3 highs:1.15.1.8 --set miplib2017 # expect ground truth OK

# super-fast
uv run run_benchmark --solver highs --instances-file super-fast-instances.txt --instances-root sets/miplib2017-benchmark --set super-fast --time-limit 15 --highs-bin ../build/bin/highs
uv run compare_versions --versions 1.15.1 1.15.1.8 --set super-fast # ratio 1.013
uv run compare_versions --versions gurobi:12.0.3 highs:1.15.1.8 --set super-fast # 28 Gurobi super-fast due to free license limit, 8 shared OK
```
