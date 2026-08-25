# HiGHS Optimization Roadmap

Planned features, priorities, and status. This is the forward-looking
companion to `docs/optimization-findings.md` (what was learned) and
`docs/optimization-changelog.md` (what shipped).

## How to use

- Pick the top unblocked item, create `feature/<name>/<next-version>` from
  `master`, bump `HIGHS_TWEAK`, follow `.opencode/skills/highs-optimize/SKILL.md`.
- Move items between Planned / In Progress / Done / Rejected as work proceeds.
- One roadmap item = one feature branch = one TWEAK version.

## Backlog

| # | Idea | Component | Tier | Status | Notes |
|---|------|-----------|------|--------|-------|
| 1 | _(add candidate optimizations here)_ | | | planned | |

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
