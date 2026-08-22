"""Compare HiGHS solver versions across benchmark results.

Reads result records from `results/highs/{version}/{machine}/{set}/{instance}.json`
and reports, per instance, the absolute runtime and the percentage difference
between each version and a reference. The reference is either an explicit
baseline version or the next neighbour in the version list.

Usage examples
--------------
Compare each version against an explicit baseline (e.g. no-GMI):

    uv run python scripts/compare_versions.py \\
        --versions 1.15.1.3 1.15.1.5 1.15.1.6 --baseline 1.15.1.3 \\
        --set super-fast

Compare each version against its predecessor (next-neighbour chain):

    uv run python scripts/compare_versions.py \\
        --versions 1.15.1.3 1.15.1.5 1.15.1.6 --mode neighbor \\
        --set super-fast

For every shared instance the report prints:

    <instance>  <base_s>  <cur_s>   <diff_s>   <diff_pct>

with a trailing aggregate (shifted geomean over the shared instances) for each
column. Instances solved by only one of the two compared versions are listed
separately (solved-vs-timeout) and not folded into the ratio.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
from pathlib import Path
from typing import Any

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results"

GROUND_TRUTH_ABS_TOL = 1e-5
GROUND_TRUTH_REL_TOL = 1e-6


def _discover_gurobi_version(results_root: Path) -> str | None:
    g_dir = results_root / "gurobi"
    if not g_dir.is_dir():
        return None
    vers = sorted(p.name for p in g_dir.iterdir() if p.is_dir())
    return vers[-1] if vers else None


def _ground_truth_mismatches(
    hi: dict[str, dict[str, Any]],
    gt: dict[str, dict[str, Any]],
) -> list[str]:
    out: list[str] = []
    for inst, hrec in hi.items():
        grec = gt.get(inst)
        if grec is None:
            continue
        g_stat = (grec.get("status") or "").lower()
        h_stat = (hrec.get("status") or "").lower()
        if g_stat not in ("optimal", "infeasible", "unbounded"):
            continue
        h_solved = "limit" not in h_stat and "unsolved" not in h_stat and h_stat not in ("error", "")
        if not h_solved:
            continue
        if g_stat != h_stat:
            out.append(f"{inst}: HiGHS {h_stat} != Gurobi {g_stat} (gurobi obj={grec.get('objective')})")
            continue
        if g_stat == "optimal":
            go = grec.get("objective")
            ho = hrec.get("objective")
            if go is not None and ho is not None:
                try:
                    diff = abs(float(go) - float(ho))
                except (TypeError, ValueError):
                    continue
                tol = GROUND_TRUTH_ABS_TOL + GROUND_TRUTH_REL_TOL * max(abs(float(go)), abs(float(ho)), 1e-9)
                if diff > tol:
                    out.append(f"{inst}: objective mismatch HiGHS {ho:.9g} != Gurobi {go:.9g} diff={diff:.3g}")
    return out


def shifted_geomean(values: list[float], shift: float = 10.0) -> float:
    if not values:
        return float("inf")
    return math.exp(sum(math.log(v + shift) for v in values) / len(values)) - shift


def load_version(version: str, inst_set: str, results_root: Path,
                 solver: str = "highs") -> dict[str, dict[str, Any]]:
    """Load {instance: record} for one solver version across all machine dirs."""
    out: dict[str, dict[str, Any]] = {}
    for f in glob.glob(str(results_root / solver / version / "*" / inst_set / "*.json")):
        try:
            rec = json.loads(Path(f).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if rec.get("solver") and rec["solver"] != solver:
            continue
        out[rec["instance"]] = rec
    return out


def is_solved(rec: dict[str, Any]) -> bool:
    status = (rec.get("status") or "").lower()
    return bool(status) and "limit" not in status and "unsolved" not in status


def solve_time(rec: dict[str, Any], time_limit_default: float) -> float:
    """Absolute solve time: runtime for solved, time-limit for timeout/unsolved."""
    status = (rec.get("status") or "").lower()
    limit = float(rec.get("time_limit") or time_limit_default)
    t = rec.get("runtime_s")
    if t is None:
        return limit
    t = float(t)
    if "limit" in status or "unsolved" in status:
        return max(t, limit)
    return t


def compare_versions_core(
    base: dict[str, dict[str, Any]],
    cur: dict[str, dict[str, Any]],
    time_limit_default: float,
    solved_only: bool = False,
) -> tuple[list[str], list[str], list[float], int, int]:
    """Compare cur against base. Returns report lines, only-version lines,
    cur runtimes, #shared, #cur-faster."""
    shared = sorted(set(base) & set(cur))
    if solved_only:
        shared = [i for i in shared if is_solved(base[i]) and is_solved(cur[i])]
    report: list[str] = []
    times: list[float] = []
    n_cur_faster = 0
    for inst in shared:
        tb = solve_time(base[inst], time_limit_default)
        tc = solve_time(cur[inst], time_limit_default)
        times.append(tc)
        diff = tc - tb
        pct = (diff / tb * 100.0) if tb > 0 else float("inf")
        arrow = " <=" if tc < tb - 1e-9 else (" =>" if tc > tb + 1e-9 else "  =")
        report.append(f"{inst:<40} {tb:>10.3f} {tc:>10.3f} {diff:>+10.3f} {pct:>+9.2f}% {arrow}")
        if tc < tb - 1e-9:
            n_cur_faster += 1
    only: list[str] = []
    for inst in sorted(set(base) - set(cur)):
        only.append(f"{inst:<40} base-only  base={solve_time(base[inst], time_limit_default):.3f}s")
    for inst in sorted(set(cur) - set(base)):
        only.append(f"{inst:<40} cur-only   cur={solve_time(cur[inst], time_limit_default):.3f}s")
    if solved_only:
        both = set(base) & set(cur)
        skipped = sorted(b for b in both if not (is_solved(base[b]) and is_solved(cur[b])))
        for inst in skipped:
            only.append(f"{inst:<40} timeout    base={solve_time(base[inst], time_limit_default):.3f}s "
                        f"cur={solve_time(cur[inst], time_limit_default):.3f}s")
    return report, only, times, len(shared), n_cur_faster


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-version HiGHS result comparison")
    ap.add_argument("--versions", nargs="+", required=True,
                    help="solver versions to compare, in order")
    ap.add_argument("--solver", default="highs",
                    help="solver whose results to load (default highs)")
    ap.add_argument("--baseline", default=None,
                    help="version to compare every other against (default: first "
                         "in --versions for mode=baseline)")
    ap.add_argument("--set", required=True, help="result cache set tag (e.g. super-fast)")
    ap.add_argument("--results-root", type=Path, default=RESULTS_ROOT)
    ap.add_argument("--mode", choices=["baseline", "neighbor"], default="baseline",
                    help="baseline: all vs one; neighbor: each vs previous")
    ap.add_argument("--time-limit", type=float, default=7200.0,
                    help="default time limit when records lack one")
    ap.add_argument("--solved-only", action="store_true", default=True,
                    help="compare only instances solved by both solvers "
                         "(default on; timeouts excluded)")
    ap.add_argument("--include-timeouts", dest="solved_only", action="store_false",
                    help="include timeout/unsolved instances (counted at time limit)")
    args = ap.parse_args()

    versions = args.versions
    def split_spec(spec: str) -> tuple[str, str]:
        if ":" in spec:
            solver, version = spec.split(":", 1)
            return solver, version
        return args.solver, spec
    specs = [split_spec(v) for v in versions]
    data = {v: load_version(version, args.set, args.results_root, solver)
            for v, (solver, version) in zip(versions, specs)}

    gt_version = _discover_gurobi_version(args.results_root)
    gt_data: dict[str, dict[str, Any]] = {}
    if gt_version is not None:
        gt_data = load_version(gt_version, args.set, args.results_root, "gurobi")
        if gt_data:
            print(f"ground truth: gurobi {gt_version} ({len(gt_data)} records, set={args.set})")
            for ver, (solver, _) in zip(versions, specs):
                if solver != "highs":
                    continue
                mism = _ground_truth_mismatches(data.get(ver, {}), gt_data)
                if mism:
                    print(f"\n!! ground truth mismatches for {ver} vs gurobi {gt_version} ({len(mism)} instances):")
                    for m in mism:
                        print(f"  !! {m}")
                    print(f"  -> {len(mism)} mismatches: HiGHS verdict/objective disagrees with Gurobi")
                else:
                    hi_solved = sum(1 for r in data.get(ver, {}).values() if is_solved(r))
                    gt_solved = sum(1 for k, r in gt_data.items() if k in data.get(ver, {}) and (r.get("status") or "").lower() in ("optimal", "infeasible", "unbounded"))
                    print(f"  ground truth OK for {ver}: no status/objective mismatches on {gt_solved} Gurobi-solved shared instances ({hi_solved} HiGHS solved)")
        else:
            print(f"ground truth: gurobi {gt_version} has no records for set={args.set} — skipping check")
    else:
        print("ground truth: no gurobi results found — skipping check (run gurobi benchmark first)")

    if args.mode == "neighbor":
        pairs = [(versions[i - 1], versions[i]) for i in range(1, len(versions))]
    else:
        base = args.baseline or versions[0]
        if base not in versions:
            print(f"error: baseline {base} not in --versions")
            return 1
        pairs = [(base, v) for v in versions if v != base]

    print(f"mode={args.mode}  set={args.set}  versions: {', '.join(versions)}")
    for base_v, cur_v in pairs:
        base = data.get(base_v, {})
        cur = data.get(cur_v, {})
        if not base or not cur:
            print(f"\n[{base_v} -> {cur_v}] missing results "
                  f"(base={len(base)}, cur={len(cur)})")
            continue
        report, only, times, n_shared, n_faster = compare_versions_core(
            base, cur, args.time_limit, args.solved_only)
        if not times:
            print(f"\n[{base_v} -> {cur_v}] no shared instances")
            continue
        shared_insts = sorted(set(base) & set(cur))
        if args.solved_only:
            shared_insts = [i for i in shared_insts
                            if is_solved(base[i]) and is_solved(cur[i])]
        gmb = shifted_geomean([solve_time(base[i], args.time_limit)
                               for i in shared_insts])
        gmc = shifted_geomean(times)
        print(f"\n{base_v} -> {cur_v}  ({n_shared} shared, {n_faster} cur-faster, "
              f"{n_shared - n_faster} cur-slower/equal)")
        print(f"{'instance':<40} {'base_s':>10} {'cur_s':>10} {'diff_s':>10} {'diff_pct':>10}  flag")
        print("-" * 92)
        for line in report:
            print(line)
        print("-" * 92)
        print(f"shifted-geomean(10)  base={gmb:.3f}s  cur={gmc:.3f}s  "
              f"ratio={gmc / gmb if gmb else float('inf'):.4f}")
        if only:
            label = "instances excluded (timeout/unsolved or one version only)" \
                if args.solved_only else "instances present in only one version"
            print(f"\n-- {label} --")
            for line in only:
                print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())