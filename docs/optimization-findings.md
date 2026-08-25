# HiGHS Optimization Findings

Structured optimization memory, organized like a taxonomy: each row is one
optimization strategy with its target component, the signal that tells us
whether it engaged, and its priority tier. Read this before changing solver
code. Companion docs:

- `docs/optimization-changelog.md` — per-version history + learnings
- `docs/optimization-roadmap.md` — planned features and priorities

## Priority Tiers

| Tier | Meaning |
|------|---------|
| 1 | Low risk, localized change, expected small-but-safe gain |
| 2 | Medium complexity or risk, needs careful correctness analysis |
| 3 | Large redesign; only with explicit user approval |

## Optimization Taxonomy

_(none yet — add rows as ideas are identified)_

Row format:

```
### <idea name>
- Component: highs/mip/... | highs/simplex/... | highs/lp_data/...
- Idea: <what to change and why it should help>
- Expected signal: <which timer/counter in HiGHS log should move>
    (e.g. "openMIPNodeLP time down", "separation rounds up")
- Validation: <how to check correctness beyond GT compare>
    (unit test, ctest target, invariant)
- Tier: 1|2|3
- Status: proposed | testing | merged (<version>) | rejected (<reason>)
```

Rules of engagement (Hawkeye-style):

1. Correctness is a precondition for performance signal. An instance whose
   objective/status disagrees with ground truth yields INVALID timing data:
   it is excluded from aggregates and fails the run.
2. A strategy counts only if BOTH the expected signal moved AND end-to-end
   geomean improved (or stayed flat within noise) on the benchmark set.
3. Iterate on `super-fast`/`fast` sets; `full` is a confirmation gate before
   merging — do not tune against full-set results.
4. Never modify harness logic (`benchmark/scripts/`) on a feature branch.
   The agent must not move its own goalposts.

## Idiomatic HiGHS Conventions

_(add code-level conventions discovered while implementing)_
