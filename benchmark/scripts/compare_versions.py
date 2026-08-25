"""Modular comparison of benchmark results (HiGHS versions, cross-solver).

Compares cached result sets against each other. Any comparison endpoint is a
``solver:version`` spec (bare versions default to ``--solver``, usually
``highs``), so one ground truth can serve many comparisons and variants can
be compared against each other in arbitrary pairs.

Comparison modes (--mode):
    baseline   every version vs one reference (--baseline, default: first).
               The reference may be another solver, e.g. gurobi:12.0.3,
               turning the ground truth into a performance reference too.
    neighbor   chain: b vs a, c vs b, ... (order of --versions)
    pairwise   explicit list, e.g. --pairs "highs:1.15.1>highs:1.15.1.3, ..."
               ('>' separates reference > candidate inside a pair)
    all        full grid: every ordered combination

Reported values are ABSOLUTE (seconds: mean/min/max/median, total saved_s)
and RELATIVE (delta %, speedup, shifted-geomean ratio, faster/slower counts).

Correctness gate (Hawkeye-style): whenever ground-truth results exist
(auto-discovered Gurobi cache by default), every candidate's status/objective
is checked against them. Instances that mismatch yield INVALID timing signal:
they are excluded from all aggregates and the tool exits 1. Perf numbers are
never computed over unvalidated results.

Output: human tables + a versions-x-versions geomean-ratio matrix on stdout;
machine-readable JSON via --json-out.

Exit codes: 0 ok | 1 correctness mismatch | 2 missing data / bad usage.

Usage examples (from benchmark/):
    uv run python scripts/compare_versions.py --set super-fast \\
        --versions 1.15.1 1.15.1.9
    uv run python scripts/compare_versions.py --set fast --mode neighbor \\
        --versions 1.15.1.9 1.15.1.10 1.15.1.11
    uv run python scripts/compare_versions.py --set super-fast \\
        --versions highs:1.15.1 highs:1.15.1.9 gurobi:12.0.3 \\
        --baseline gurobi:12.0.3
    uv run python scripts/compare_versions.py --set super-fast --mode all \\
        --versions 1.15.1 1.15.1.9 1.15.1.10 --json-out report.json
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import results_dir, utcnow_iso  # noqa: E402
from solvers import ground_truth_version  # noqa: E402

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results"

GROUND_TRUTH_ABS_TOL = 1e-5
GROUND_TRUTH_REL_TOL = 1e-6
GEOMEAN_SHIFT = 10.0


# ========================================================================
# Data layer: load result records keyed by instance name
# ========================================================================
def resolve_spec(spec: str, default_solver: str) -> tuple[str, str]:
    """'gurobi:12.0.3' -> ('gurobi','12.0.3'); '1.15.1' -> default_solver."""
    if ":" in spec:
        solver, version = spec.split(":", 1)
        return solver, version
    return default_solver, spec


def load_version(spec: str, inst_set: str, results_root: Path,
                 default_solver: str = "highs",
                 machine: str | None = None) -> dict[str, dict[str, Any]]:
    """Load {instance: record} for one solver/version/set (optionally one machine)."""
    solver, version = resolve_spec(spec, default_solver)
    pattern = results_root / solver / version
    if machine:
        pattern = pattern / machine
    out: dict[str, dict[str, Any]] = {}
    for f in glob.glob(str(pattern / "*" / inst_set / "*.json")):
        try:
            rec = json.loads(Path(f).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if rec.get("solver") and rec["solver"] != solver:
            continue
        out[rec.get("instance") or Path(f).stem] = rec
    return out


def load_version_any_set(spec: str, results_root: Path,
                         default_solver: str = "highs",
                         prefer_set: str | None = None,
                         machine: str | None = None,
                         ) -> dict[str, dict[str, Any]]:

    """Load {instance: record} ignoring the set tag (union over sets).

    Used for ground truth: correctness/reference data is per-instance, so a
    candidate benchmarked under set 'super-fast' can be checked against a
    ground-truth cache stored under 'miplib2017'. Records from ``prefer_set``
    win when an instance appears in several sets.
    """
    merged: dict[str, dict[str, Any]] = {}
    solver, _ = resolve_spec(spec, default_solver)
    pattern = results_root / solver / resolve_spec(spec, default_solver)[1]
    if machine:
        pattern = pattern / machine
    files = sorted(glob.glob(str(pattern / "*" / "*" / "*.json")))
    # two passes: other sets first so preferred set overwrites
    ordered = [f for f in files if f.split(os.sep)[-3] != prefer_set] + \
              [f for f in files if f.split(os.sep)[-3] == prefer_set]
    for f in ordered:
        try:
            rec = json.loads(Path(f).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if rec.get("solver") and rec["solver"] != solver:
            continue
        merged[rec.get("instance") or Path(f).stem] = rec
    return merged


# ========================================================================
# Metrics layer: pure functions over records
# ========================================================================
def is_solved(rec: dict[str, Any]) -> bool:
    status = (rec.get("status") or "").lower()
    return bool(status) and "limit" not in status and "unsolved" not in status


def solve_time(rec: dict[str, Any], time_limit_default: float) -> float:
    """Absolute solve time: repeats-aware mean for solved, limit for timeout."""
    status = (rec.get("status") or "").lower()
    limit = float(rec.get("time_limit") or time_limit_default)
    t = rec.get("runtime_mean_s", rec.get("runtime_s"))
    if t is None:
        return limit
    t = float(t)
    if "limit" in status or "unsolved" in status:
        return max(t, limit)
    return t


def shifted_geomean(values: list[float], shift: float = GEOMEAN_SHIFT) -> float:
    if not values:
        return float("inf")
    return math.exp(sum(math.log(v + shift) for v in values) / len(values)) - shift


@dataclass
class InstanceRow:
    instance: str
    t_a: float
    t_b: float

    @property
    def delta_s(self) -> float:
        return self.t_b - self.t_a

    @property
    def delta_pct(self) -> float:
        denom = self.t_a if abs(self.t_a) > 1e-12 else 1e-12
        return self.delta_s / denom * 100.0

    @property
    def speedup(self) -> float:
        denom = self.t_b if abs(self.t_b) > 1e-12 else 1e-12
        return self.t_a / denom


@dataclass
class PairResult:
    a: str
    b: str
    rows: list[InstanceRow] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)

    @property
    def n_faster(self) -> int:
        return sum(1 for r in self.rows if r.t_b < r.t_a - 1e-12)

    @property
    def n_slower(self) -> int:
        return sum(1 for r in self.rows if r.t_b > r.t_a + 1e-12)

    def aggregate(self) -> dict[str, Any]:
        ta = [r.t_a for r in self.rows]
        tb = [r.t_b for r in self.rows]
        if not ta:
            return {}
        deltas_pct = [r.delta_pct for r in self.rows]
        gma, gmb = shifted_geomean(ta), shifted_geomean(tb)
        return {
            "n_shared": len(self.rows),
            "abs": {
                "mean_a_s": round(statistics.fmean(ta), 4),
                "mean_b_s": round(statistics.fmean(tb), 4),
                "min_a_s": round(min(ta), 4),
                "max_a_s": round(max(ta), 4),
                "min_b_s": round(min(tb), 4),
                "max_b_s": round(max(tb), 4),
                "median_a_s": round(statistics.median(ta), 4),
                "median_b_s": round(statistics.median(tb), 4),
                "total_saved_s": round(sum(ta) - sum(tb), 4),
                "shifted_geomean_a_s": round(gma, 4),
                "shifted_geomean_b_s": round(gmb, 4),
            },
            "rel": {
                "shifted_geomean_ratio": round(gmb / gma, 6) if gma else float("inf"),
                "geomean_speedup": round(math.exp(statistics.fmean(
                    [math.log(r.speedup) for r in self.rows])), 6),
                "mean_delta_pct": round(statistics.fmean(deltas_pct), 4),
                "median_delta_pct": round(statistics.median(deltas_pct), 4),
                "faster": self.n_faster,
                "slower": self.n_slower,
                "equal": len(self.rows) - self.n_faster - self.n_slower,
            },
        }


def pair_stats(a_label: str, b_label: str,
               base: dict[str, dict[str, Any]],
               cur: dict[str, dict[str, Any]],
               time_limit_default: float,
               solved_only: bool = True,
               invalid_a: set[str] | None = None,
               invalid_b: set[str] | None = None) -> PairResult:
    """Compare two result sets; excludes unsolved/invalid instances with reasons."""
    invalid_a = invalid_a or set()
    invalid_b = invalid_b or set()
    result = PairResult(a=a_label, b=b_label)
    shared = sorted(set(base) & set(cur))
    for inst in sorted(set(base) - set(cur)):
        result.excluded.append((inst, "base-only"))
    for inst in sorted(set(cur) - set(base)):
        result.excluded.append((inst, "cur-only"))

    for inst in shared:
        ba, ca = base[inst], cur[inst]
        sa, sb = is_solved(ba), is_solved(ca)
        if solved_only and not (sa and sb):
            result.excluded.append((inst, "timeout-or-unsolved"))
            continue
        if inst in invalid_a or inst in invalid_b:
            reason = ("invalid-signal" if inst in invalid_a and inst in invalid_b
                      else f"invalid-signal ({'a' if inst in invalid_a else 'b'} vs ground truth)")
            result.excluded.append((inst, reason))
            continue
        result.rows.append(InstanceRow(inst, solve_time(ba, time_limit_default),
                                       solve_time(ca, time_limit_default)))
    return result


def correctness_mismatches(cand: dict[str, dict[str, Any]],
                           gt: dict[str, dict[str, Any]]) -> list[str]:
    """Instances where a solved candidate disagrees with ground truth.

    Only GT-decided instances (optimal/infeasible/unbounded) are checked, and
    only candidates claiming a solve; timeouts cannot be checked this way.
    Objectives are compared with the candidate's own configured MIP gap
    (record field ``mip_gap_tol``): stopping at that gap is by design and
    yields objectives slightly off the proven optimum.
    """
    out: list[str] = []
    for inst, crec in cand.items():
        grec = gt.get(inst)
        if grec is None:
            continue
        g_stat = (grec.get("status") or "").lower()
        if g_stat not in ("optimal", "infeasible", "unbounded"):
            continue
        c_stat = (crec.get("status") or "").lower()
        c_solved = (bool(c_stat) and "limit" not in c_stat
                    and "unsolved" not in c_stat and c_stat != "error")
        if not c_solved:
            continue
        if g_stat != c_stat:
            out.append(f"{inst}: status {c_stat!r} != ground truth {g_stat!r}")
            continue
        if g_stat == "optimal":
            go, co = grec.get("objective"), crec.get("objective")
            if go is None or co is None:
                continue
            try:
                gof, cof = float(go), float(co)
            except (TypeError, ValueError):
                continue
            scale = max(abs(gof), abs(cof), 1e-9)
            tol = max(GROUND_TRUTH_ABS_TOL + GROUND_TRUTH_REL_TOL * scale,
                      float(crec.get("mip_gap_tol") or 0.0) * scale)
            if abs(gof - cof) > tol:
                out.append(f"{inst}: objective {cof:.9g} != ground truth {gof:.9g} "
                           f"(diff {abs(gof - cof):.3g} > tol {tol:.3g})")
    return out


# ========================================================================
# Plan layer: which (reference, candidate) pairs to compare
# ========================================================================
def build_pairs(mode: str, specs: list[str], baseline: str | None,
                pairs_arg: str | None) -> list[tuple[str, str]]:
    """Raise ValueError on bad user input; return (reference, candidate) pairs."""
    if mode == "neighbor":
        return [(specs[i - 1], specs[i]) for i in range(1, len(specs))]
    if mode == "all":
        return [(a, b) for a in specs for b in specs if a != b]
    if mode == "pairwise":
        if not pairs_arg:
            raise ValueError("mode=pairwise requires --pairs \"REF>CAND[,REF>CAND...]\"")
        pairs: list[tuple[str, str]] = []
        for chunk in pairs_arg.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if ">" not in chunk:
                raise ValueError(f"bad pair {chunk!r}: expected REF>CAND")
            ref, cand = (s.strip() for s in chunk.split(">", 1))
            unknown = [s for s in (ref, cand) if s not in specs]
            if unknown:
                raise ValueError(f"pair endpoints not in --versions: {unknown}")
            pairs.append((ref, cand))
        if not pairs:
            raise ValueError("mode=pairwise produced no pairs")
        return pairs
    # baseline mode
    ref = baseline or specs[0]
    if ref not in specs:
        raise ValueError(f"baseline {ref!r} not in --versions")
    return [(ref, s) for s in specs if s != ref]


# ========================================================================
# Report layer: tables, matrix, JSON
# ========================================================================
def render_pair_table(pr: PairResult) -> list[str]:
    lines = [f"\n[{pr.a} -> {pr.b}]  ({len(pr.rows)} compared, "
             f"{pr.n_faster} faster, {pr.n_slower} slower/equal)"]
    if not pr.rows:
        lines.append("  no comparable instances")
    else:
        lines.append(f"{'instance':<40} {'a_s':>10} {'b_s':>10} {'diff_s':>10} "
                     f"{'diff_pct':>10} {'speedup':>8}")
        lines.append("-" * 94)
        for r in pr.rows:
            arrow = "<=" if r.delta_s < -1e-9 else ("=>" if r.delta_s > 1e-9 else " =")
            lines.append(f"{r.instance:<40} {r.t_a:>10.3f} {r.t_b:>10.3f} "
                         f"{r.delta_s:>+10.3f} {r.delta_pct:>+9.2f}% "
                         f"{r.speedup:>7.3f}x {arrow}")
        lines.append("-" * 94)
        agg = pr.aggregate()
        a, rel = agg["abs"], agg["rel"]
        lines.append(
            f"ABSOLUTE  mean a={a['mean_a_s']:.3f}s b={a['mean_b_s']:.3f}s  "
            f"min/max a={a['min_a_s']:.3f}/{a['max_a_s']:.3f}s "
            f"b={a['min_b_s']:.3f}/{a['max_b_s']:.3f}s  saved={a['total_saved_s']:+.1f}s")
        lines.append(
            f"RELATIVE  geomean ratio={rel['shifted_geomean_ratio']:.4f}  "
            f"geomean speedup={rel['geomean_speedup']:.4f}x  "
            f"mean diff={rel['mean_delta_pct']:+.2f}%  "
            f"median diff={rel['median_delta_pct']:+.2f}%")
    if pr.excluded:
        lines.append(f"-- excluded ({len(pr.excluded)}) --")
        for inst, reason in pr.excluded:
            lines.append(f"   {inst:<40} {reason}")
    return lines


def render_matrix(data: dict[str, dict[str, dict[str, Any]]],
                  specs: list[str], time_limit_default: float,
                  solved_only: bool) -> list[str]:
    """Versions x versions grid of shifted-geomean ratios: cell(i,j)=t_i/t_j."""
    lines = ["\nmatrix: cell(row, col) = shifted-geomean(row) / shifted-geomean(col)",
             "        <1 => row faster than col", ""]
    short = {s: s.replace("highs:", "") for s in specs}
    width = max(10, *(len(short[s]) for s in specs)) + 2
    header = " " * width + "".join(f"{short[s]:>{width}}" for s in specs)
    lines.append(header)
    gm: dict[str, float] = {}
    for s in specs:
        pr = pair_stats(s, s, data[s], data[s], time_limit_default, solved_only)
        agg = pr.aggregate()
        gm[s] = agg["abs"]["shifted_geomean_b_s"] if agg else float("nan")
    for ri, r in enumerate(specs):
        cells = []
        for ci, c in enumerate(specs):
            if ri == ci:
                cells.append(f"{'1.0000':>{width}}")
                continue
            pr = pair_stats(r, c, data[r], data[c], time_limit_default, solved_only)
            agg = pr.aggregate()
            ratio = agg["rel"]["shifted_geomean_ratio"] if agg else float("nan")
            cells.append(f"{ratio:>{width}.4f}" if math.isfinite(ratio) \
                         else f"{'n/a':>{width}}")
        lines.append(f"{short[r]:<{width}}" + "".join(cells))
    return lines


def build_json_report(meta: dict[str, Any],
                      correctness: dict[str, Any],
                      pair_results: list[PairResult],
                      data: dict[str, dict[str, dict[str, Any]]],
                      specs: list[str], time_limit_default: float,
                      solved_only: bool) -> dict[str, Any]:
    matrix: dict[str, dict[str, float | None]] = {}
    for r in specs:
        row: dict[str, float | None] = {}
        for c in specs:
            if r == c:
                row[c] = 1.0
                continue
            agg = pair_stats(r, c, data[r], data[c],
                             time_limit_default, solved_only).aggregate()
            row[c] = agg["rel"]["shifted_geomean_ratio"] if agg else None
        matrix[r] = row
    return {
        "meta": meta,
        "correctness": correctness,
        "pairs": [
            {
                "a": pr.a, "b": pr.b,
                "aggregate": pr.aggregate(),
                "excluded": [{"instance": i, "reason": r} for i, r in pr.excluded],
                "per_instance": [
                    {"instance": r.instance, "t_a_s": r.t_a, "t_b_s": r.t_b,
                     "delta_s": round(r.delta_s, 4),
                     "delta_pct": round(r.delta_pct, 4),
                     "speedup": round(r.speedup, 6)}
                    for r in pr.rows],
            } for pr in pair_results],
        "matrix": {"metric": "shifted_geomean_ratio row/col", "cells": matrix},
    }


# ========================================================================
# Main
# ========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Modular benchmark comparison (absolute + relative, gated "
                    "by ground truth)")
    ap.add_argument("--versions", nargs="+", required=True,
                    help="endpoints to compare: 'version' or 'solver:version'")
    ap.add_argument("--solver", default="highs",
                    help="solver assumed for bare versions (default highs)")
    ap.add_argument("--set", required=True, help="result-cache set tag")
    ap.add_argument("--machine", default=None,
                    help="restrict loading to one machine dir")
    ap.add_argument("--mode", choices=["baseline", "neighbor", "pairwise", "all"],
                    default="baseline")
    ap.add_argument("--baseline", default=None,
                    help="reference for mode=baseline (default: first --versions)")
    ap.add_argument("--pairs", default=None,
                    help='mode=pairwise: "REF>CAND[,REF>CAND...]"')
    ap.add_argument("--results-root", type=Path, default=results_dir())
    ap.add_argument("--time-limit", type=float, default=7200.0,
                    help="fallback limit when a record lacks one")
    ap.add_argument("--include-timeouts", action="store_true",
                    help="count timeouts at the time limit instead of excluding "
                         "(default: solved-only comparison)")
    ap.add_argument("--gt", default=None,
                    help="ground-truth spec (default: auto-discover latest "
                         "Gurobi cache; 'none' disables the check)")
    ap.add_argument("--json-out", type=Path, default=None,
                    help="also write the full machine-readable report here")
    args = ap.parse_args()

    specs: list[str] = []
    for s in args.versions:  # dedupe, preserve order
        if s not in specs:
            specs.append(s)
    # An explicit --baseline outside --versions is attached as a pure
    # reference endpoint (e.g. many variants vs one ground truth).
    if args.mode == "baseline" and args.baseline and args.baseline not in specs:
        specs.append(args.baseline)
    results_root = args.results_root
    solved_only = not args.include_timeouts

    data: dict[str, dict[str, dict[str, Any]]] = {}
    for s in specs:
        d = load_version(s, args.set, results_root, args.solver, args.machine)
        if not d:
            # Reference endpoints (GT cache) may store instances under a
            # different set tag; fall back to a union over sets.
            d = load_version_any_set(s, results_root, args.solver,
                                     prefer_set=args.set, machine=args.machine)
            if d:
                print(f"note: {s} has no set={args.set!r} records; "
                      f"using {len(d)} record(s) from other sets")
        data[s] = d
    missing = [s for s, d in data.items() if not d]
    if missing:
        print(f"error: no records for set={args.set!r}: {', '.join(missing)}")
        return 2

    # ---- ground truth + correctness gate -------------------------------
    correctness: dict[str, Any] = {}
    invalid: dict[str, set[str]] = {s: set() for s in specs}
    gate_failed = False
    gt_spec: str | None = None
    if args.gt != "none":
        gt_spec = args.gt
        if gt_spec is None:
            gt_ver = ground_truth_version(results_root=results_root)
            gt_spec = f"gurobi:{gt_ver}" if gt_ver else None
    if gt_spec is not None:
        gt_data = load_version(gt_spec, args.set, results_root, args.solver,
                               args.machine)
        if not gt_data:
            # Ground truth is per-instance: fall back to a union over sets
            # so e.g. super-fast runs can be checked against a cache stored
            # under the miplib2017 tag.
            gt_data = load_version_any_set(gt_spec, results_root, args.solver,
                                           prefer_set=args.set,
                                           machine=args.machine)
        if not gt_data:
            print(f"ground truth: {gt_spec} has no records for set={args.set!r} "
                  "- correctness check SKIPPED")
            correctness = {"ground_truth": gt_spec, "status": "skipped-no-data"}
        else:
            print(f"ground truth: {gt_spec} ({len(gt_data)} records, set={args.set})")
            correctness = {"ground_truth": gt_spec, "status": "ok", "candidates": {}}
            for s in specs:
                if s == gt_spec:
                    continue
                mism = correctness_mismatches(data[s], gt_data)
                invalid[s] = {m.split(":")[0].strip() for m in mism}
                correctness["candidates"][s] = {
                    "checked_gt_solved": sum(
                        1 for i, r in gt_data.items()
                        if i in data[s] and (r.get("status") or "").lower()
                        in ("optimal", "infeasible", "unbounded")),
                    "mismatches": mism,
                    "invalid_instances": sorted(invalid[s]),
                }
                if mism:
                    gate_failed = True
                    print(f"!! {s}: {len(mism)} ground-truth mismatch(es) - "
                          f"affected timings are INVALID SIGNAL:")
                    for m in mism:
                        print(f"   !! {m}")
                else:
                    print(f"   {s}: correctness OK")

    # ---- comparisons ----------------------------------------------------
    try:
        pairs = build_pairs(args.mode, specs, args.baseline, args.pairs)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    if not pairs:
        print("nothing to compare (need >= 2 versions for this mode)")
        return 2

    print(f"\nmode={args.mode} set={args.set} solved_only={solved_only} "
          f"endpoints: {', '.join(specs)}")
    pair_results: list[PairResult] = []
    for a_spec, b_spec in pairs:
        pr = pair_stats(a_spec, b_spec, data[a_spec], data[b_spec],
                        args.time_limit, solved_only,
                        invalid.get(a_spec), invalid.get(b_spec))
        pair_results.append(pr)
        for line in render_pair_table(pr):
            print(line)

    for line in render_matrix(data, specs, args.time_limit, solved_only):
        print(line)

    if args.json_out:
        report = build_json_report(
            meta={"set": args.set, "machine": args.machine,
                  "generated": utcnow_iso(),
                  "solved_only": solved_only,
                  "time_limit_default": args.time_limit,
                  "mode": args.mode},
            correctness=correctness, pair_results=pair_results,
            data=data, specs=specs, time_limit_default=args.time_limit,
            solved_only=solved_only)
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2))
        print(f"\njson report: {args.json_out}")

    if gate_failed:
        print("\nRESULT: FAIL - ground-truth mismatches (exit 1)")
        return 1
    print("\nRESULT: OK"
          + ("" if correctness.get("status") == "ok"
             else " (correctness not checked - no GT data)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
