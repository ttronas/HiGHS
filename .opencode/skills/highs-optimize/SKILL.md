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

- `docs/optimization-findings.md` — optimization taxonomy (idea rows:
  component, expected signal, validation), priority tiers. **READ BEFORE
  changing code.**
- `docs/optimization-changelog.md` — version history, current status,
  Learnings. Every optimization commit adds an entry here.
- `docs/optimization-roadmap.md` — planned features and promotion gates.
  Pick work from here; record outcomes back into it.

The tiers are maintained in those files, NOT inline in this skill.

## Goal

Reduce MIP solution times on the MIPLIB2017 benchmark set. Every change must
show improvement (or no regression) in benchmark results WITHOUT ever
compromising correctness. Primary metric: shifted geomean runtime across
instances (from `compare_versions.py`). Correctness vs ground truth is
non-negotiable — see gate below.

## Version convention

Every optimization commit bumps `HIGHS_TWEAK` in `Version.txt` by 1
(`MAJOR.MINOR.PATCH.TWEAK`, e.g. 1.15.1 -> 1.15.1.9); official `HIGHS_PATCH`
never changes. Bump BEFORE building — the harness reads the version from the
binary at runtime. One commit = one bump = one changelog entry. Never skip.

## Branching workflow (mandatory)

- Develop ONLY in `feature/<feature-name>/<version>` branches off `master`.
- Never commit feature work directly to `master`.
- **Harness immutability**: a feature branch may change `highs/` (and tests)
  only. Never modify `benchmark/scripts/`, compare logic, instance lists, or
  tolerance constants on a feature branch — the agent must not move its own
  goalposts. Harness changes land separately on `master` first.
- Failed feature (regression or correctness fail): rename branch to
  `failed/<feature>/<version>`, never delete or stash it — it is analysis
  fodder. Document the learning in findings + changelog ON master.

## Test-set ladder

| set | definition | command |
|-----|------------|---------|
| smoke-test | bundled examples (7 tiny MIPs) | `--instances-root examples --set smoke-test` |
| miplib2017-super-fast | baseline solves < 10 s | `--instances-file sets/subsets/miplib2017-super-fast-instances.txt --time-limit 60` |
| miplib2017-fast | baseline solves < 60 s | `--instances-file sets/subsets/miplib2017-fast-instances.txt --time-limit 60` |
| miplib2017 (full) | all instances @ 60 s cap | default instances root |
| lp-mittelmann | 49 LP (Mittelmann public), 60 s cap | `--instances-root sets/lp-mittelmann --set lp-mittelmann` |
| lp-mittelmann-fast | LP solves < 60 s | `--instances-file sets/subsets/lp-mittelmann-fast-instances.txt --time-limit 60` |

Lists are machine-dependent: regenerate with
`uv run python scripts/filter_sets.py` (miplib) or `... --set lp-mittelmann` after machine/baseline changes.
Iterate on super-fast, confirm on fast; run full ONLY as merge gate
(anti-overfit: do not tune against full-set results). All benches 60s cap, CPU only, `solver=choose` (production).

Solves faster than 5 s are automatically repeated 5x and averaged by the
runner (`runs[]`, `runtime_mean_s`; `runtime_s` = mean). Force with
`--repeats N`.

## Workflow

```
0. git checkout -b feature/<feature>/<next-version> master
   Bump HIGHS_TWEAK in Version.txt
1. Build:           ./benchmark/scripts/build_highs.sh        # ccache-accelerated
2. Smoke:           cd benchmark && uv run python scripts/run_benchmark.py \
                       --instances-root examples --set smoke-test
3. Unit tests:      cd build && ctest   (and uv run pytest scripts/test_compare_metrics.py)
4. Iteration bench: uv run python scripts/run_benchmark.py \
                       --instances-file sets/subsets/miplib2017-super-fast-instances.txt --time-limit 60
5. Gate+compare:    uv run python scripts/compare_versions.py --set miplib2017-super-fast \
                       --versions highs:<base> highs:<cur>
6. Confirm:         same with --set miplib2017-fast (sets/subsets/miplib2017-fast-instances.txt, 60 s)
7. Update changelog + findings + roadmap, then commit per Commit policy
```

Cached builds live in `benchmark/binaries/highs-<version>` (`--highs-bin`).
Re-bench an old build without rebuilding. Runner skips already-cached
instances automatically; `--force` re-runs.

## Correctness gate (non-negotiable)

`compare_versions.py` checks every candidate against the committed Gurobi
ground truth (`results/gurobi/`, license at `benchmark/gurobi.lic`). Rules:

- Any status/objective mismatch beyond tolerance => those instances are
  INVALID SIGNAL: excluded from all aggregates, run exits 1, version FAILS.
- Objectives within the candidate's configured `mip_gap_tol` of ground truth
  are acceptable (stopping at the gap is by design).
- No ground-truth coverage for a set? The comparator unions GT sets by
  instance name; if still uncovered it says so — treat uncovered results as
  provisional, never claim success from them.
- Exit codes: 0 ok | 1 mismatch | 2 missing data.

## Comparison CLI (modular)

```bash
# N candidates vs one reference (reference may be cross-solver):
compare_versions.py --set super-fast --versions highs:A highs:B --baseline gurobi:12.0.3
# chain b<->a, c<->b:
compare_versions.py --set fast --mode neighbor --versions A B C
# arbitrary pairs / full grid:
compare_versions.py --set fast --mode pairwise --versions A B C --pairs "A>B,B>C"
compare_versions.py --set fast --mode all --versions A B C
# machine-readable report for automation:
... --json-out cmp.json
```

Reports absolute (mean/min/max/median s, saved_s) AND relative (delta %,
speedup, shifted-geomean ratio) values per pair, plus a versions-x-versions
ratio matrix. `--include-timeouts` folds timeouts in at the cap (default:
excluded — a timeout is a lower bound, not an estimate).

## Commit policy

- Success (geomean <= baseline, zero mismatches, gates passed): merge feature
  branch to master; update changelog/findings/roadmap on master.
- Failure: `git branch -m feature/<f>/<v> failed/<f>/<v>`; document learning
  on master; revert master to last good state.
- Changelog entry MUST include: set used, geomean ratio, faster/slower
  counts, correctness verdict.

## Pitfalls (also in changelog Learnings)

- Version bump BEFORE build, or results overwrite.
- `Version.txt`: `HIGHS_TWEAK=1` (equals sign); CMake regex `HIGHS_TWEAK=(.*)`.
- `HConfig.h.in` must carry `#define HIGHS_VERSION_TWEAK @HIGHS_VERSION_TWEAK@`.
- Binary hash catches un-bumped edits (cache miss forces rerun) — don't fight
  it, bump the version.
- Node presolve is a runtime option (`mip_node_presolve_threshold`, 0 = off):
  toggling needs no rebuild/TWEAK bump.
- Gurobi license at `benchmark/gurobi.lic` (gitignored, NEVER commit).

## Hyperparameter tuning (no rebuild)

1. `uv run python scripts/sample_train.py --source sets/subsets/miplib2017-super-fast-instances.txt --k 8 --seed 0` — deterministic (same 8 across all workers); `--k all` uses entire super-fast.
2. Edit `benchmark/configs/tune/*.yaml` — any `HighsOptions.h` param (all changeable). Omit = default.
3. `uv run python scripts/tune.py --train-set sets/subsets/miplib2017-super-small-instances.txt --search-space configs/tune/example.yaml --n-trials 100 --time-limit 60` — per-trial `workdir/trial_*.opts` via `--options_file`, isolated per worker; no rebuild. `--n-trials` any integer (100 small, 1000-5000 large).
   Locked scoring: wrong vs GT `-1e6`, timeout `-1e3`, optimal `1000/(t+10)`; study mean, `direction=maximize`.
4. Validate best on full set: re-run `run_benchmark` with `best_params.yaml` or `tune.py --test-set` then `compare_versions`.

## Reference

- `docs/optimization-findings.md` / `-changelog.md` / `-roadmap.md`
- `benchmark/README.md` — harness docs incl. full flag tables
- `benchmark/scripts/run_benchmark.py` — runner (cache, repeats, `--highs-options*` no rebuild)
- `benchmark/scripts/compare_versions.py` — modular comparator + GT gate
- `benchmark/scripts/filter_sets.py` — set classification (<10s/<60s)
- `benchmark/scripts/sample_train.py` — deterministic train sampler (`--k 8|all --seed 0`)
- `benchmark/scripts/tune.py` — Optuna tuning (yaml search space, locked magnitudes)
- `benchmark/scripts/build_highs.sh` — release build (ccache)
- `highs/mip/`, `highs/simplex/` — MIP/simplex source
