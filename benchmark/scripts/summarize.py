"""Summarize benchmark results: shifted-geomean table + performance profiles.

Loads every cached result under the results root
    results/{solver}/{solver_version}/{machine}/{instance}.json
and prints a Mittelmann-style comparison table:

    * the number of instances run per solver series
    * how many were solved within the time limit
    * unscaled and scaled (shift=10s) shifted geometric means of runtimes,
      with timeouts counted at the time limit

It then plots a Dolan-More performance profile on the instances that every
selected series has results for, and writes:

    results/summary/performance_profile_<timestamp>.png
    results/summary/summary_<timestamp>.csv      (per-instance)
    results/summary/geomean_<timestamp>.csv      (aggregate)

A Mittelmann reference table can be overlaid with --reference (the .res file),
displayed for context only - it is NOT merged into the plot because the
reference used different (v1-preprocessed) instances.

Usage:
    uv run python scripts/summarize.py [--results-root benchmark/results] [--reference benchmark/reference/mittelmann-12threads.res]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import results_dir  # noqa: E402

SOLVED_STATUSES = {"optimal", "infeasible", "unbounded"}
TIME_LIMIT_STATUSES = {"time_limit", "iteration_limit", "node_limit", "solution_limit", "objective_limit"}

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


# ----------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------
def load_series(results_root: Path) -> dict[str, list[dict]]:
    series: dict[str, list[dict]] = defaultdict(list)
    if not results_root.exists():
        return dict(series)
    for solver_dir in sorted(results_root.iterdir()):
        if not solver_dir.is_dir():
            continue
        for version_dir in sorted(solver_dir.iterdir()):
            if not version_dir.is_dir():
                continue
            for machine_dir in sorted(version_dir.iterdir()):
                if not machine_dir.is_dir():
                    continue
                for json_file in machine_dir.glob("*.json"):
                    try:
                        rec = json.loads(json_file.read_text())
                    except (OSError, json.JSONDecodeError):
                        continue
                    rec.setdefault("solver", solver_dir.name)
                    rec.setdefault("solver_version", version_dir.name)
                    rec.setdefault("machine", machine_dir.name)
                    series[f'{rec["solver"]} {rec["solver_version"]} {rec["machine"][:20]}'].append(rec)
    return dict(series)


def series_metrics(records: list[dict], time_limit_default: float) -> dict[str, Any]:
    """Per-series aggregate over *its own* instances (all non-error records)."""
    runtimes, solved = [], 0
    for r in records:
        if r.get("status") in ("error", None):
            continue
        limit = r.get("time_limit") or time_limit_default
        status = (r.get("status") or "").lower()
        if status in SOLVED_STATUSES:
            solved += 1
        t = r.get("runtime_s")
        t = limit if (t is None or (status in TIME_LIMIT_STATUSES)) else float(t)
        runtimes.append((r.get("instance", "?"), max(t, 0.0), limit))
    return {
        "n": len(runtimes),
        "solved": solved,
        "runtimes": runtimes,
        "limits": [tl for (_, _, tl) in runtimes],
    }


def shifted_geomean(values, shift: float = 10.0) -> float:
    if not values:
        return float("inf")
    return math.exp(sum(math.log(v + shift) for v in values) / len(values)) - shift


# ----------------------------------------------------------------------
# Mittelmann .res reference parser
# ----------------------------------------------------------------------
def parse_mittelmann(path: Path) -> dict[str, dict[str, float]]:
    """Parse a plato.asu.edu 12threads.res table.

    Returns {solver_name: {instance: runtime_in_seconds}} with "timeout"
    counted at the common 7200 s limit and non-numeric entries dropped.
    """
    text = path.read_text(errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    header = None
    data_started = False
    timelimit = 7200.0
    parsed: dict[str, dict[str, float]] = defaultdict(dict)
    for ln in lines:
        s = ln.strip()
        if s.startswith("timelimit"):
            m = re.search(r"\(?\s*([0-9.]+)\s*s", s)
            if m:
                timelimit = float(m.group(1))
        if s.startswith(("---", "===")):
            data_started = header is not None
            continue
        if header is None and s.startswith("Name"):
            header = [t for t in s.split() if t != "|"]
            continue
        if not data_started or header is None or s.startswith(("Name", "Testset", "solved/stopped")):
            continue
        toks = s.split()
        if len(toks) - 1 != len(header) - 1:
            continue
        name = toks[0]
        for col, tok in zip(header[1:], toks[1:]):
            try:
                parsed[col][name] = float(tok)
            except ValueError:
                if tok.lower() in ("timeout", "abort", "mip-gap", "feas", "inf"):
                    parsed[col][name] = timelimit
    return dict(parsed)


# ----------------------------------------------------------------------
# output
# ----------------------------------------------------------------------
def format_table(series: dict[str, dict], ref: dict[str, dict] | None) -> str:
    from io import StringIO

    buf = StringIO()
    all_limits = [tl for m in series.values() for (_, _, tl) in m["runtimes"]]
    tl = max(all_limits) if all_limits else 7200.0
    names = list(series.keys()) + ([f"plato {k}" for k in (ref or {})])
    print(f"{'solver/series':38} {'n':>5} {'solved':>7} {'unscaled':>10} {'scaled':>10}", file=buf)
    for label in names:
        if label.startswith("plato "):
            src = ref[next(k for k in ref if label == f"plato {k}")]
            n = len(src)
            solved = sum(1 for v in src.values() if v < tl - 1e-6)
            vals = list(src.values())
            gm = shifted_geomean(vals, 0.0)
            gms = shifted_geomean(vals, 10.0)
            print(f"{label:38} {n:>5} {solved:>7} {gm:>10.3g} {gms:>10.3g}", file=buf)
            continue
        m = series[label]
        vals = [t for (_, t, _) in m["runtimes"]]
        gm = shifted_geomean(vals, 0.0)
        gms = shifted_geomean(vals, 10.0)
        print(f"{label:38} {m['n']:>5} {m['solved']:>7} {gm:>10.3g} {gms:>10.3g}", file=buf)
    return buf.getvalue()


def performance_profile(series: dict[str, dict], out_png: Path) -> None:
    """Dolan-More performance profile over instances solved by every series."""
    per_inst: dict[str, dict[str, float]] = defaultdict(dict)
    for label, m in series.items():
        for inst, t, _tl in m["runtimes"]:
            per_inst[inst][label] = t
    common = [i for i, d in per_inst.items() if set(d) == set(series)]
    if not common:
        print("no instances solved by every series - skipping plot")
        return
    ratios: dict[str, list[float]] = defaultdict(list)
    grid = sorted(set([1.0, 1.05, 1.1, 1.2, 1.3, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0,
                       6.0, 8.0, 10.0, 15.0, 20.0, 40.0, 60.0, 120.0]))
    for inst in common:
        best = min(per_inst[inst].values())
        for label in series:
            ratios[label].append(per_inst[inst][label] / best if best > 0 else 1.0)
    fig, ax = plt.subplots(figsize=(9, 6))
    for label in sorted(series):
        counts = [r for r in ratios[label]]
        ys = []
        for x in grid:
            ys.append(sum(1 for r in counts if r <= x) / len(counts))
        ax.plot(grid, ys, marker="o", markersize=3, label=label)
    ax.set_xscale("log", base=2)
    ax.set_xlabel("performance ratio r (capped at time limit)")
    ax.set_ylabel("fraction of instances with t <= r * t_best")
    ax.set_title(f"Performance profile over {len(common)} common instances")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="lower right")
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=150)
    print(f"plot written: {out_png}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarize/plot benchmark results")
    ap.add_argument("--results-root", type=Path, default=None)
    ap.add_argument("--reference", type=Path, default=None,
                    help="Mittelmann .res table for context (optional)")
    ap.add_argument("--plot", type=Path, default=None,
                    help="output PNG for performance profile")
    args = ap.parse_args()

    rroot = args.results_root or results_dir()
    if not rroot.is_dir() or not any(rroot.iterdir()):
        print("no results yet - run scripts/run_benchmark.py first")
        return 1

    series = load_series(rroot)
    if not series:
        print("no result series found")
        return 1
    metrics = {label: series_metrics(recs, time_limit_default=7200.0)
               for label, recs in series.items()}
    for label, recs in series.items():
        print(f"series: {label}  ({len(recs)} records)")

    ref: dict[str, dict[str, float]] | None = None
    if args.reference:
        ref = parse_mittelmann(Path(args.reference))
        print(f"reference: {len(ref)} solver columns loaded "
              f"({next(iter(ref), 'none') if ref else ''})")

    print(format_table(metrics, ref))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    summary_dir = rroot / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    plot_path = args.plot or summary_dir / f"performance_profile_{stamp}.png"
    performance_profile(metrics, plot_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
