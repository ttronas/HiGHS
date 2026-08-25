# HiGHS Optimization Changelog

Version history for benchmarked HiGHS optimizations on MIPLIB2017.

Every optimization commit bumps `HIGHS_TWEAK` in `Version.txt` (`1.15.1.x`)
and MUST add an entry here. Changelog version must match `Version.txt` at
commit time. Never skip versions.

## Current Status

| Version | Feature | Branch | Result |
|---------|---------|--------|--------|
| 1.15.1  | upstream baseline (`252ef77`) | `master` | reference |

## Version Entries

_(none yet — add one entry per `HIGHS_TWEAK` bump)_

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
