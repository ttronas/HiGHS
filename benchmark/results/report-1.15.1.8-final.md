# Final Report — 1.15.1.8 GMI Fix Iteration (Ideas 1–4)

Branch: `fix/generateGomoryCut` `c371896b42` → `1.15.1.8` (no bump per instruction)
Machine: `13th-gen-intel-r-core-tm-i7-1355u-12cpu-15-5g` 12 threads
Harness: `run_benchmark` + `compare_versions --solved-only` + ground truth `gurobi:12.0.3`

## Primary Metric `test-gmi-fix2.txt` 20 disputed MIPLIB2017 (60s)

All Ideas keep `0` `HiGHS infeasible != Gurobi optimal` vs `20` before (`1.15.1.5` raw GMI, `1.15.1.6` idiomatic). `enlight_hard` now `Time limit` (not `Infeasible`), direct `build/bin/highs --time_limit 60` `Optimal 37` 46s.

| Version | GMI | fastPath | 20-set mismatches | 20-set solved (HiGHS) | exp-1-500-5-5 vs Gurobi |
|---|---|---|---|---|---|
| 1.15.1.5 (buggy raw GMI) | raw `generateGmiCut` | off | 20 | 20 false | 0.3s false |
| 1.15.1.8 Idea1 (clean-row, no GMI) | off | clean `isCleanRow→transformClean` | 0 | 7 (4 shared) | 8.7s `-17%` faster than Gurobi 10.6s |
| 1.15.1.8 Idea1+Idea2 (clean + gated GMI) | gated `hasGeneral||hasContinuous→false`, `rowlen>50→false`, `f0 0.10-0.90`, `maxAct`, `incumbent` | clean | 0 | 4 | 9.9s `-6%` |
| 1.15.1.8 Idea1+Idea2+Idea4 (clean + gated + transform `infeasible` fix) | same | clean + `cleanupVub/Vlb infeasible→false` | 0 | 4 | 8.9s `-15%` |
| 1.15.1.8 Idea1+Idea2+Idea4 local (propagate=false) | local `finalizeAndAddCut(...,true)` | same | 0 | 4 | 10.0s `-5%` |

All correct versions avoid `traininstance6` `error -11`? Idea1+Idea2+Idea4 `traininstance6` `Time limit 60.6s` not `error` (clean-row fixes `traininstance6` `SIGSEGV` seen in `1.15.1.8` disabled without clean-row). `ns1208400` now `Time limit` not `Infeasible`.

## Super-fast 135 instances, 15s

| Version | super-fast mismatches (8 Gurobi shared, free license 28) | super-fast solved | geomean(10) | vs 1.15.1 baseline 4.109s | faster/slower |
|---|---|---|---|---|---|
| 1.15.1 | 0 | 22 | 4.109s | 1.0 | — |
| Idea1 alone | 0 | 22 | 4.213s | 1.025 (2.5% slower) | 11/10 |
| Idea1+Idea2 | 0 | 25 | 4.162s | 1.013 (1.3% slower) | 11/10 |
| Idea1+Idea2+Idea4 | 0 | 25 | 4.138s | 1.007 (0.7% slower) | 9/12 |
| Idea1+Idea2+Idea4 local | 0 | 26 | 4.250s | 1.034 (3.4% slower) | 10/11 |

No correct Idea beats `1.15.1` baseline on `super-fast` (`ratio<1`). Gurobi super-fast free license only 28 records, 8 shared, all `ground truth OK`.

## Best Single and Combination

- **Best single for correctness + speed:** **Idea1+Idea2+Idea4 (clean-row + gated GMI + transform fix, global)** `1.15.1.8` — `0` mismatches on both `test-gmi-fix2` and `super-fast`, `4` HiGHS solved on 20-set (1 faster than Gurobi `exp-1-500-5-5`), `super-fast` `1.007` closest to baseline, `25` solved vs `22` baseline.
- **Best pure speed without GMI:** **Idea1** alone `1.025` — simpler (1 file `HighsTransformedLp` clean path), same correctness, slightly slower than `1.013`.
- **Combination:** `Idea1+Idea2+Idea4` is already the combination of clean-row + gated GMI + transform fix. Adding `Idea3` local makes it slower `1.034` (local cuts less effective). Expected best combo remains `Idea1+Idea2+Idea4` global. Further combination `Idea1+Idea4` (clean + transform fix, no GMI) would be `~1.02` similar to Idea1 alone.

**Full 240 MIPLIB2017 60s not run** per instruction criteria: requires correct version faster than `1.15.1` baseline (`56.5` geomean vs Gurobi `33.1` `findings:85`). No Idea achieves `ratio<1` on `super-fast`, and `test-gmi-fix2` vs Gurobi is `3.7-4.8×` slower, so full 240 would also be slower.

## How to Reproduce

```
# test-gmi-fix2 primary
uv run run_benchmark --solver highs --instances-file test-gmi-fix2.txt --instances-root sets/miplib2017-benchmark --set miplib2017 --time-limit 60 --highs-bin ../build/bin/highs
uv run compare_versions --versions gurobi:12.0.3 highs:1.15.1.8 --set miplib2017 # expect ground truth OK

# super-fast
uv run run_benchmark --solver highs --instances-file super-fast-instances.txt --instances-root sets/miplib2017-benchmark --set super-fast --time-limit 15 --highs-bin ../build/bin/highs
uv run compare_versions --versions 1.15.1 1.15.1.8 --set super-fast # ratio 1.007, 0 mismatches
uv run compare_versions --versions gurobi:12.0.3 highs:1.15.1.8 --set super-fast # 28 Gurobi due to free license limit
```

Current `1.15.1.8` retains `GMI` disabled global gated behind 5 checks; to re-enable fully sound GMI need incumbent LP-feasibility trial per cut and `mip_gmi_enable` flag.

## Files

- `highs/mip/HighsTransformedLp.h:56` `isCleanRow`/`transformClean`
- `highs/mip/HighsTransformedLp.cpp:isCleanRow` + `transformClean` + `cleanupVub/Vlb infeasible→false` `191/206`
- `highs/mip/HighsCutGeneration.h:107` `generateGomoryCut(...,bool isLocal)` + `finalizeAndAddCut(...,bool isLocal)`
- `highs/mip/HighsCutGeneration.cpp:1242` gated GMI `rowlen>50` `f0 0.10-0.90` `maxAct` `incumbent` + `propagate=!isLocal` `1477`
- `highs/mip/HighsTableauSeparator.cpp:231` 2× `generateGomoryCut` behind gates (currently global, Idea3 local would pass `true`)
