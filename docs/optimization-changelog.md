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
| 1.15.1.2 | tune cutpool age/soft limits | `failed/tune-cutpool-age/1.15.1.2` | rejected — 1.36x slower |
| 1.15.1.3 | CMIR viol 0.001*feastol | `failed/fix-cmir-violation/1.15.1.3` | rejected — 1.10x slower |

## Version Entries

### 1.15.1.1 — enable zi_round+shifting, heuristic_effort 0.05→0.08, TWEAK plumbing
- Branch: feature/enable-zi-shifting-heur-effort/1.15.1.1
- Change: `highs/lp_data/HighsOptions.h:1224` `mip_heuristic_run_zi_round/shifting false→true`, `mip_heuristic_effort 0.05→0.08`; fix 4-part version: `Version.txt` `HIGHS_TWEAK=1`, `cmake/set-version.cmake` TWEAK parse, `highs/HConfig.h.*` `+TWEAK`, `highs/lp_data/Highs.cpp`/`app/HighsRuntimeOptions.h:157`/`highs/io/HighsIO.cpp:27`/`highs/HighsExternalApi.cpp:62` include `HIGHS_VERSION_TWEAK` so `highs --version` reports `1.15.1.1` and `benchmark/scripts/solvers.py` regex picks 4-part; `docs/optimization-roadmap.md` + `docs/optimization-findings.md` tiered backlog (21 items)
- Benchmark: set=super-fast (18 inst), geomean ratio vs 1.15.1 =0.873, faster/slower=17/1, saved +8.4s, mean diff -17.78%; set=fast (26 inst) geomean 0.995, 17/9, correctness PASS vs gurobi:12.0.3 (0 mismatches) on 12 threads 15s/60s
- Verdict: merged

### 1.15.1.2 — tune cutpool age/soft limits (REJECTED)
- Branch: failed/tune-cutpool-age/1.15.1.2
- Change: `highs/lp_data/HighsOptions.h:1175-1193` `mip_lp_age_limit 10→12`, `mip_pool_age_limit 30→35`, `mip_pool_soft_limit 10000→12000` (keep cuts longer)
- Benchmark: set=super-fast geomean 1.360 (16/18 slower, 2 faster, +42.29%, saved -22.9s) vs 1.15.1.1; correctness PASS
- Verdict: rejected — retaining more cuts bloats LP, `DuSimplexBasisSolveLp` time up, `total_lp_iterations` up, no bound gain. Default 30/10000/10 is well-tuned.

### 1.15.1.3 — CMIR min violation 0.001*feastol (REJECTED)
- Branch: failed/fix-cmir-violation/1.15.1.3
- Change: `highs/mip/HighsCutGeneration.cpp:603,637,682` add `if (viol < 1e-3*feastol) continue` in 3 efficacy loops to filter weak CMIR cuts (TODO fix)
- Benchmark: set=super-fast geomean 1.104 (14/18 slower, 4 faster, +13.13%) vs 1.15.1.1; correctness PASS
- Verdict: rejected — filter too aggressive or scale mismatch removes useful cuts; efficacy filter already `minEfficacy` sufficient. Keep TODO for future tighter density check.

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

- Cutpool: defaults 30/10000/10 well-tuned; increasing 35/12000/12 bloats LP (1.36x slower on super-fast, HighsCutGeneration bloat).
- CMIR: `1e-3*feastol` violation filter (1.10x slower) redundant — `minEfficacy` already filters; low-viol high-efficacy cuts via small `sqrnorm` still useful.

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
