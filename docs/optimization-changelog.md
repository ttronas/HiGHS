# HiGHS Optimization Changelog

Version history for benchmarked HiGHS optimizations on MIPLIB2017.

Every optimization commit bumps `HIGHS_TWEAK` in `Version.txt` (`1.15.1.x`)
and MUST add an entry here. Changelog version must match `Version.txt` at
commit time. Never skip versions.

## Current Status

| Version | Feature | Branch | Result |
|---------|---------|--------|--------|
| 1.15.1  | upstream baseline (`252ef77`) | `master` | reference |
| 1.15.1.1 | enable zi_round+shifting, heur_effort 0.08 | `feature/enable-zi-shifting-heur-effort/1.15.1.1` | merged — super-fast 0.873x, fast 0.995x, PASS |

## Version Entries

### 1.15.1.1 — enable zi_round+shifting, heuristic_effort 0.05→0.08, TWEAK plumbing
- Branch: feature/enable-zi-shifting-heur-effort/1.15.1.1
- Change: `highs/lp_data/HighsOptions.h:1224` `mip_heuristic_run_zi_round/shifting false→true`, `mip_heuristic_effort 0.05→0.08`; fix 4-part version: `Version.txt` `HIGHS_TWEAK=1`, `cmake/set-version.cmake` TWEAK parse, `highs/HConfig.h.*` `+TWEAK`, `highs/lp_data/Highs.cpp`/`app/HighsRuntimeOptions.h:157`/`highs/io/HighsIO.cpp:27`/`highs/HighsExternalApi.cpp:62` include `HIGHS_VERSION_TWEAK` so `highs --version` reports `1.15.1.1` and `benchmark/scripts/solvers.py` regex picks 4-part; `docs/optimization-roadmap.md` + `docs/optimization-findings.md` tiered backlog (21 items)
- Benchmark: set=super-fast (18 inst), geomean ratio vs 1.15.1 =0.873, faster/slower=17/1, saved +8.4s, mean diff -17.78%; set=fast (26 inst) geomean 0.995, 17/9, correctness PASS vs gurobi:12.0.3 (0 mismatches) on 12 threads 15s/60s
- Verdict: merged

_(none yet — add one entry per `HIGHS_TWEAK` bump — template below, keep)_

Entry format:

```
### 1.15.1.<x> — <feature name>
- Branch: feature/<feature>/<version>
- Change: <what was done, files touched>
- Benchmark: set=<super-fast|fast|full>, geomean ratio vs baseline=<r>,
  faster/slower=<n/m>, correctness vs ground truth=<PASS/FAIL>
- Verdict: merged | rejected (reason)
```

## Learnings

Recurring pitfalls and harness facts. Add entries as they are discovered.

- Bump `HIGHS_TWEAK` in `Version.txt` BEFORE building — the harness reads the
  version from the binary at runtime; results otherwise overwrite each other.
- `Version.txt` syntax is `HIGHS_TWEAK=1` (equals sign). CMake regex is
  `HIGHS_TWEAK=(.*)`.
- `highs/HConfig.h.in` must carry
  `#define HIGHS_VERSION_TWEAK @HIGHS_VERSION_TWEAK@`.
- Built binaries are cached at `benchmark/binaries/highs-<version>`; pass via
  `--highs-bin` to re-benchmark an old build.
- Node presolve is a runtime option (`mip_node_presolve_threshold`, 0 = off):
  toggling it needs no rebuild and no TWEAK bump.
- Fast subsets are machine-dependent: regenerate lists with
  `scripts/filter_sets.py` when the machine or baseline changes.
- Gurobi license lives at `benchmark/gurobi.lic` (gitignored, never commit).
